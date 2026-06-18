from __future__ import annotations

from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import common  # type: ignore
    import royalty_fee  # type: ignore
else:
    from . import common
    from . import royalty_fee

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - fallback for minimal envs
    def tqdm(iterable, **_: object):  # type: ignore
        return iterable


OUTPUT_SLUG = "royalty_fee_century"
DEFAULT_STATE_ID_BY_STATE = {"OH": "2"}


def _load_century_stores(root: Path) -> list[str]:
    import sys

    sys.path.insert(0, str(root))
    from financial.sales_export_comparison.rules import load_org_rule

    rules_dir = root / "financial" / "sales_export_comparison" / "rules"
    return load_org_rule("century", rules_dir).stores


def _prompt_percent(label: str, default_value: float) -> float:
    return royalty_fee._prompt_percent(label, default_value)  # type: ignore[attr-defined]


def _prompt_state_id_map() -> dict[str, str]:
    default_text = ",".join(
        f"{state}={state_id}" for state, state_id in sorted(DEFAULT_STATE_ID_BY_STATE.items())
    )
    raw = input(f"State ID map (STATE=ID comma list, blank allowed) [{default_text}]: ").strip()
    if not raw:
        return dict(DEFAULT_STATE_ID_BY_STATE)

    out: dict[str, str] = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        state, state_id = part.split("=", 1)
        state = state.strip().upper()
        state_id = state_id.strip()
        if state and state_id:
            out[state] = state_id
    if not out:
        print(f"Invalid state map; using default {default_text}.")
        return dict(DEFAULT_STATE_ID_BY_STATE)
    return out


def _prompt_inputs(pos_data_dir: Path) -> tuple[royalty_fee.DateRange, float, float, float, dict[str, str]]:
    print("=== Century Royaltie Fee Audit ===")
    available_dates = common.list_available_dates(pos_data_dir)
    if available_dates:
        print(
            f"Available dates: {available_dates[0]} -> {available_dates[-1]} "
            f"({len(available_dates)} days)"
        )
    start_date = royalty_fee._prompt_date("Start date (YYYY-MM-DD): ")  # type: ignore[attr-defined]
    end_date = royalty_fee._prompt_date("End date (YYYY-MM-DD): ")  # type: ignore[attr-defined]
    if start_date > end_date:
        raise SystemExit("Start date must be <= end date.")

    date_range = royalty_fee.DateRange(start_date=start_date, end_date=end_date)
    print(
        "Scan window: "
        f"{date_range.scan_dates[0].isoformat()} -> {date_range.scan_dates[-1].isoformat()} "
        f"({royalty_fee.LOOKBACK_DAYS}-day backcheck, {royalty_fee.LOOKAHEAD_DAYS}-day forward check)"
    )
    royalty_rate = _prompt_percent("Royalty percent", royalty_fee.DEFAULT_ROYALTY_PCT)
    advertising_rate = _prompt_percent("Advertising percent", royalty_fee.DEFAULT_ADVERTISING_PCT)
    media_rate = _prompt_percent("Media percent", royalty_fee.DEFAULT_MEDIA_PCT)
    state_id_by_state = _prompt_state_id_map()
    return date_range, royalty_rate, advertising_rate, media_rate, state_id_by_state


def _build_royalties_export_df(
    detail_df: pd.DataFrame,
    *,
    total_days: int,
    royalty_rate: float,
    advertising_rate: float,
    media_rate: float,
) -> pd.DataFrame:
    store_summary = (
        detail_df.groupby("store_number", as_index=False)
        .agg(
            state=("state", "first"),
            state_id=("state_id", "first"),
            days_with_data=("date", "nunique"),
            royalty_sales=("royalty_sales", "sum"),
            royalty_fee=("royalty_fee", "sum"),
            advertising_fee=("advertising_fee", "sum"),
            media_fee=("media_fee", "sum"),
        )
        .round(2)
        .sort_values("store_number", key=lambda s: s.astype(str).str.zfill(8))
    )
    return pd.DataFrame(
        {
            "Store": store_summary["store_number"],
            "Royalty Sales": store_summary["royalty_sales"].round(2),
            "Royalty": store_summary["royalty_fee"].round(2),
            "Royalty %": round(royalty_rate * 100, 6),
            "Advertising": store_summary["advertising_fee"].round(2),
            "Advertising %": round(advertising_rate * 100, 6),
            "Media": store_summary["media_fee"].round(2),
            "Media %": round(media_rate * 100, 6),
            "Days": store_summary["days_with_data"].astype(str) + f" of {total_days}",
            "State ID": store_summary["state_id"],
        }
    )


def run() -> None:
    root = common.repo_root()
    pos_data_dir = root / "pos_data"
    stores = _load_century_stores(root)
    date_range, royalty_rate, advertising_rate, media_rate, state_id_by_state = _prompt_inputs(pos_data_dir)

    existing_scan_dates = [
        d for d in date_range.scan_dates if (pos_data_dir / d.isoformat()).is_dir()
    ]
    print("Preloading cross-date sales context...")
    cross_date_sales = common._build_cross_date_sales_context(  # type: ignore[attr-defined]
        pos_data_dir, existing_scan_dates
    )
    print("Preloading cross-date payments...")
    cross_date_payments = common._build_cross_date_payments(  # type: ignore[attr-defined]
        pos_data_dir, existing_scan_dates
    )

    rows: list[dict[str, object]] = []
    missing_dates: list[str] = []
    skipped_store_days: list[dict[str, str]] = []
    target_dates = date_range.target_dates
    total_work = len(target_dates) * len(stores)

    with tqdm(total=total_work, unit="store-day", desc="Royalty audit") as pbar:
        for target in target_dates:
            target_date_str = target.isoformat()
            day_dir = pos_data_dir / target_date_str
            if not day_dir.is_dir():
                missing_dates.append(target_date_str)
                pbar.update(len(stores))
                continue

            store_map = royalty_fee._load_store_map(day_dir)  # type: ignore[attr-defined]
            for store_number in stores:
                pbar.set_postfix_str(f"{target_date_str} store {store_number}")
                store_match = store_map[store_map["Store_Number"].eq(str(store_number))]
                if store_match.empty:
                    skipped_store_days.append(
                        {
                            "date": target_date_str,
                            "store_number": store_number,
                            "reason": f"Store {store_number} not found in Store.txt",
                        }
                    )
                    pbar.update(1)
                    continue

                store_state = str(store_match["State"].iloc[0]).strip().upper()
                store_id = str(store_match["Store_ID"].iloc[0]).strip()
                state_id = state_id_by_state.get(store_state, "")
                try:
                    rows.append(
                        royalty_fee._compute_store_day(  # type: ignore[attr-defined]
                            pos_data_dir,
                            target_date_str,
                            store_number,
                            cross_date_sales,
                            cross_date_payments,
                            store_state,
                            state_id,
                            royalty_rate,
                            advertising_rate,
                            media_rate,
                            store_id,
                        )
                    )
                except Exception as exc:
                    skipped_store_days.append(
                        {
                            "date": target_date_str,
                            "store_number": store_number,
                            "reason": str(exc),
                        }
                    )
                pbar.update(1)

    if not rows:
        raise SystemExit("No Century royalty fee audit rows were produced.")

    detail_df = pd.DataFrame(rows)
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
    date_summary_df = (
        detail_df.groupby("date", as_index=False)
        .agg(
            store_count=("store_number", "nunique"),
            store_paid_tickets=("store_paid_tickets", "sum"),
            paid_third_party_tickets=("paid_third_party_tickets", "sum"),
            **{col: (col, "sum") for col in amount_cols},
        )
        .round(2)
    )
    royalties_export_df = _build_royalties_export_df(
        detail_df,
        total_days=len(target_dates),
        royalty_rate=royalty_rate,
        advertising_rate=advertising_rate,
        media_rate=media_rate,
    )

    summary_rows: list[dict[str, object]] = [
        {"metric": "org", "value": "century"},
        {"metric": "start_date", "value": date_range.start_date_str},
        {"metric": "end_date", "value": date_range.end_date_str},
        {"metric": "scan_start_date", "value": date_range.scan_dates[0].isoformat()},
        {"metric": "scan_end_date", "value": date_range.scan_dates[-1].isoformat()},
        {"metric": "configured_stores", "value": len(stores)},
        {"metric": "stores_with_rows", "value": detail_df["store_number"].nunique()},
        {"metric": "store_day_rows", "value": int(len(detail_df))},
        {"metric": "missing_date_folders", "value": len(missing_dates)},
        {"metric": "skipped_store_days", "value": len(skipped_store_days)},
        {"metric": "royalty_rate", "value": round(royalty_rate, 6)},
        {"metric": "advertising_rate", "value": round(advertising_rate, 6)},
        {"metric": "media_rate", "value": round(media_rate, 6)},
        {
            "metric": "state_id_map",
            "value": ",".join(
                f"{state}={state_id}" for state, state_id in sorted(state_id_by_state.items())
            ),
        },
    ]
    if missing_dates:
        summary_rows.append({"metric": "missing_dates", "value": ",".join(missing_dates)})
    for col in amount_cols:
        summary_rows.append({"metric": col, "value": round(float(detail_df[col].sum()), 2)})
    grand_summary_df = pd.DataFrame(summary_rows)

    out_dir = common.script_root() / "audits" / OUTPUT_SLUG / date_range.period_key
    royalty_fee._write_outputs(  # type: ignore[attr-defined]
        out_dir, detail_df, royalties_export_df, date_summary_df, grand_summary_df
    )

    if skipped_store_days:
        pd.DataFrame(skipped_store_days).to_csv(
            out_dir / "audit_royalty_fee_century_skipped_store_days.csv", index=False
        )

    print(f"Audit written to: {out_dir}")


if __name__ == "__main__":
    run()
