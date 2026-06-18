"""Build a QA royalties export from raw POS files.

The output matches the royalty export shape consumed by the comparison stage:
one selected-period row per store/category, with debit/credit entries for the
royalty, national media, and corporate advertising accruals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from scripts.financial.pos_audit.audit_scripts import common
from scripts.financial.pos_audit.audit_scripts import royalty_fee

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - fallback for minimal envs
    def tqdm(iterable=None, **_: object):  # type: ignore
        return iterable if iterable is not None else _NoopTqdm()


class _NoopTqdm:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.total = kwargs.get("total")

    def __enter__(self) -> "_NoopTqdm":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def update(self, _: int = 1) -> None:
        return None

    def set_postfix_str(self, _: str) -> None:
        return None


DEFAULT_ROYALTY_RATE = 0.065
DEFAULT_ADVERTISING_RATE = 0.010
DEFAULT_MEDIA_RATE = 0.040
DEFAULT_STATE_ID_BY_STATE = {"OH": "2"}

ROYALTY_EXPORT_COLUMNS = [
    "DateRange",
    "Class",
    "NetSales",
    "Transaction Category",
    "Account Number",
    "Account Name",
    "Debit",
    "Credit",
    "Memo",
    "IsBalanced",
    "Export Status",
]

ROYALTY_CATEGORY_MAP = [
    {
        "category": "Royalty Fee",
        "amount_col": "royalty_fee",
        "debit": True,
        "account_number": "651000",
        "account_name": "Royalties",
    },
    {
        "category": "Royalties Bank Acct Entry",
        "amount_col": "royalty_fee",
        "debit": False,
        "account_number": "217000",
        "account_name": "Accrued Royalties",
    },
    {
        "category": "National Media Fee",
        "amount_col": "media_fee",
        "debit": True,
        "account_number": "560000",
        "account_name": "Advertising-National",
    },
    {
        "category": "National Media Bank Entry",
        "amount_col": "media_fee",
        "debit": False,
        "account_number": "217000",
        "account_name": "Accrued Royalties",
    },
    {
        "category": "Corporate Advertising Fee",
        "amount_col": "advertising_fee",
        "debit": True,
        "account_number": "560001",
        "account_name": "Advertising-Production Fund",
    },
    {
        "category": "Corp Advertising Bank Acct Entry",
        "amount_col": "advertising_fee",
        "debit": False,
        "account_number": "217000",
        "account_name": "Accrued Royalties",
    },
]


@dataclass(frozen=True)
class RoyaltyVerifierConfig:
    pos_data_dir: Path
    stores: list[str]
    start_date: date
    end_date: date
    output_csv_path: Path
    detail_csv_path: Path | None = None
    summary_csv_path: Path | None = None
    skipped_csv_path: Path | None = None
    include_cross_date_lookahead: bool = True
    royalty_rate: float = DEFAULT_ROYALTY_RATE
    advertising_rate: float = DEFAULT_ADVERTISING_RATE
    media_rate: float = DEFAULT_MEDIA_RATE
    state_id_by_state: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_STATE_ID_BY_STATE)
    )


def _date_list(start: date, end: date) -> list[date]:
    out: list[date] = []
    current = start
    while current <= end:
        out.append(current)
        current += timedelta(days=1)
    return out


def _scan_dates(config: RoyaltyVerifierConfig) -> list[date]:
    if not config.include_cross_date_lookahead:
        return _date_list(config.start_date, config.end_date)
    return _date_list(
        config.start_date - timedelta(days=royalty_fee.LOOKBACK_DAYS),
        config.end_date + timedelta(days=royalty_fee.LOOKAHEAD_DAYS),
    )


def _format_date_range(start_date: date, end_date: date) -> str:
    return f"{start_date.isoformat()} - {end_date.isoformat()}"


def _export_royalty_sales_column(detail_df: pd.DataFrame) -> str:
    return "royalty_sales_raw" if "royalty_sales_raw" in detail_df.columns else "royalty_sales"


def _build_export_df(
    detail_df: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    royalty_rate: float,
    advertising_rate: float,
    media_rate: float,
) -> pd.DataFrame:
    period = _format_date_range(start_date, end_date)
    royalty_sales_col = _export_royalty_sales_column(detail_df)
    store_summary = (
        detail_df.groupby("store_number", as_index=False)
        .agg(
            royalty_sales=(royalty_sales_col, "sum"),
        )
        .sort_values("store_number", key=lambda s: s.astype(str).str.zfill(8))
    )
    store_summary["royalty_sales"] = store_summary["royalty_sales"].round(2)
    store_summary["royalty_fee"] = (
        store_summary["royalty_sales"] * royalty_rate
    ).round(2)
    store_summary["advertising_fee"] = (
        store_summary["royalty_sales"] * advertising_rate
    ).round(2)
    store_summary["media_fee"] = (
        store_summary["royalty_sales"] * media_rate
    ).round(2)

    rows: list[dict[str, object]] = []
    for _, store_row in store_summary.iterrows():
        for category in ROYALTY_CATEGORY_MAP:
            amount = round(float(store_row[category["amount_col"]]), 2)
            if amount == 0:
                continue
            rows.append(
                {
                    "DateRange": period,
                    "Class": str(store_row["store_number"]),
                    "NetSales": round(float(store_row["royalty_sales"]), 2),
                    "Transaction Category": category["category"],
                    "Account Number": category["account_number"],
                    "Account Name": category["account_name"],
                    "Debit": amount if category["debit"] else 0.0,
                    "Credit": 0.0 if category["debit"] else amount,
                    "Memo": "",
                    "IsBalanced": True,
                    "Export Status": "",
                }
            )

    return pd.DataFrame(rows, columns=ROYALTY_EXPORT_COLUMNS)


def _write_summary(
    config: RoyaltyVerifierConfig,
    detail_df: pd.DataFrame,
    *,
    missing_dates: list[str],
    skipped_count: int,
) -> None:
    if config.summary_csv_path is None:
        return

    amount_cols = [
        "taxable_sales",
        "non_taxable_sales",
        "tax_exempt_sales",
        "third_party_tax_exempt_sales",
        "total_sales",
        "surcharge_sales",
        "non_third_party_surcharge_sales",
        "royalty_sales",
        "royalty_fee",
        "advertising_fee",
        "media_fee",
    ]
    rows: list[dict[str, object]] = [
        {"metric": "start_date", "value": config.start_date.isoformat()},
        {"metric": "end_date", "value": config.end_date.isoformat()},
        {"metric": "configured_stores", "value": len(config.stores)},
        {"metric": "stores_with_rows", "value": detail_df["store_number"].nunique()},
        {"metric": "store_day_rows", "value": len(detail_df)},
        {"metric": "missing_date_folders", "value": len(missing_dates)},
        {"metric": "skipped_store_days", "value": skipped_count},
        {"metric": "royalty_rate", "value": config.royalty_rate},
        {"metric": "advertising_rate", "value": config.advertising_rate},
        {"metric": "media_rate", "value": config.media_rate},
    ]
    if missing_dates:
        rows.append({"metric": "missing_dates", "value": ",".join(missing_dates)})
    for col in amount_cols:
        if col in detail_df.columns:
            rows.append({"metric": col, "value": round(float(detail_df[col].sum()), 2)})

    royalty_sales_col = _export_royalty_sales_column(detail_df)
    export_summary = (
        detail_df.groupby("store_number", as_index=False)
        .agg(royalty_sales=(royalty_sales_col, "sum"))
    )
    export_summary["royalty_sales"] = export_summary["royalty_sales"].round(2)
    rows.extend(
        [
            {
                "metric": "export_royalty_fee",
                "value": round(float((export_summary["royalty_sales"] * config.royalty_rate).round(2).sum()), 2),
            },
            {
                "metric": "export_advertising_fee",
                "value": round(float((export_summary["royalty_sales"] * config.advertising_rate).round(2).sum()), 2),
            },
            {
                "metric": "export_media_fee",
                "value": round(float((export_summary["royalty_sales"] * config.media_rate).round(2).sum()), 2),
            },
        ]
    )

    config.summary_csv_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(config.summary_csv_path, index=False)


def run(config: RoyaltyVerifierConfig) -> int:
    """Generate a POS-computed royalty export CSV and aggregate audit files."""
    target_dates = _date_list(config.start_date, config.end_date)
    scan_dates = _scan_dates(config)
    existing_scan_dates = [
        day for day in scan_dates if (config.pos_data_dir / day.isoformat()).is_dir()
    ]

    if config.include_cross_date_lookahead:
        print(
            "[royalty verifier] Scan window: "
            f"{scan_dates[0].isoformat()} -> {scan_dates[-1].isoformat()}"
        )
    else:
        print("[royalty verifier] Scan window: selected date range only")

    print("[royalty verifier] Pre-loading cross-date sales context...")
    cross_date_sales = common._build_cross_date_sales_context(  # type: ignore[attr-defined]
        config.pos_data_dir, existing_scan_dates
    )
    print("[royalty verifier] Pre-loading cross-date payments...")
    cross_date_payments = common._build_cross_date_payments(  # type: ignore[attr-defined]
        config.pos_data_dir, existing_scan_dates
    )

    rows: list[dict[str, object]] = []
    missing_dates: list[str] = []
    skipped_store_days: list[dict[str, str]] = []
    total_work = len(target_dates) * len(config.stores)

    with tqdm(total=total_work, unit="store-day", desc="[royalty verifier] Computing") as pbar:
        for target in target_dates:
            target_date_str = target.isoformat()
            day_dir = config.pos_data_dir / target_date_str
            if not day_dir.is_dir():
                missing_dates.append(target_date_str)
                pbar.update(len(config.stores))
                continue

            store_map = royalty_fee._load_store_map(day_dir)  # type: ignore[attr-defined]
            for store_number in config.stores:
                pbar.set_postfix_str(f"Store {store_number} | {target_date_str}")
                store_match = store_map[store_map["Store_Number"].eq(str(store_number))]
                if store_match.empty:
                    skipped_store_days.append(
                        {
                            "date": target_date_str,
                            "store_number": str(store_number),
                            "reason": f"Store {store_number} not found in Store.txt",
                        }
                    )
                    pbar.update(1)
                    continue

                store_state = str(store_match["State"].iloc[0]).strip().upper()
                store_id = str(store_match["Store_ID"].iloc[0]).strip()
                state_id = config.state_id_by_state.get(store_state, "")
                try:
                    rows.append(
                        royalty_fee._compute_store_day(  # type: ignore[attr-defined]
                            config.pos_data_dir,
                            target_date_str,
                            str(store_number),
                            cross_date_sales,
                            cross_date_payments,
                            store_state,
                            state_id,
                            config.royalty_rate,
                            config.advertising_rate,
                            config.media_rate,
                            store_id,
                        )
                    )
                except Exception as exc:
                    skipped_store_days.append(
                        {
                            "date": target_date_str,
                            "store_number": str(store_number),
                            "reason": str(exc),
                        }
                    )
                pbar.update(1)

    if not rows:
        raise ValueError("No POS-computed royalty rows were produced.")

    detail_df = pd.DataFrame(rows)
    export_df = _build_export_df(
        detail_df,
        start_date=config.start_date,
        end_date=config.end_date,
        royalty_rate=config.royalty_rate,
        advertising_rate=config.advertising_rate,
        media_rate=config.media_rate,
    )

    config.output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    export_df.to_csv(config.output_csv_path, index=False)

    if config.detail_csv_path is not None:
        config.detail_csv_path.parent.mkdir(parents=True, exist_ok=True)
        detail_df.to_csv(config.detail_csv_path, index=False)
    if config.skipped_csv_path is not None and skipped_store_days:
        config.skipped_csv_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(skipped_store_days).to_csv(config.skipped_csv_path, index=False)
    _write_summary(
        config,
        detail_df,
        missing_dates=missing_dates,
        skipped_count=len(skipped_store_days),
    )

    return len(export_df)
