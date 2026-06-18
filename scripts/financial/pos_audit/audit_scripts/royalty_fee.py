from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import common  # type: ignore
else:
    from . import common

CATEGORY_NAME = "Royaltie Fee"
OUTPUT_SLUG = "royalty_fee"
LOOKBACK_DAYS = 10
LOOKAHEAD_DAYS = 30
DEFAULT_ROYALTY_PCT = 6.5
DEFAULT_ADVERTISING_PCT = 1.0
DEFAULT_MEDIA_PCT = 4.0
DEFAULT_STATE_ID_BY_STATE = {"OH": "2"}


@dataclass(frozen=True)
class DateRange:
    start_date: date
    end_date: date

    @property
    def start_date_str(self) -> str:
        return self.start_date.isoformat()

    @property
    def end_date_str(self) -> str:
        return self.end_date.isoformat()

    @property
    def period_key(self) -> str:
        return f"{self.start_date_str}_{self.end_date_str}"

    @property
    def target_dates(self) -> list[date]:
        return _date_list(self.start_date, self.end_date)

    @property
    def scan_dates(self) -> list[date]:
        return _date_list(
            self.start_date - timedelta(days=LOOKBACK_DAYS),
            self.end_date + timedelta(days=LOOKAHEAD_DAYS),
        )


def _date_list(start: date, end: date) -> list[date]:
    out: list[date] = []
    current = start
    while current <= end:
        out.append(current)
        current += timedelta(days=1)
    return out


def _parse_date(raw: str) -> date:
    raw = raw.strip()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Use YYYY-MM-DD format, got: {raw!r}") from exc


def _prompt_date(label: str) -> date:
    while True:
        raw = input(label).strip()
        if not raw:
            print("Input required.")
            continue
        try:
            return _parse_date(raw)
        except ValueError as exc:
            print(exc)


def _prompt_store_number() -> str:
    while True:
        raw = input("Store number: ").strip()
        if raw:
            return raw
        print("Input required.")


def _prompt_percent(label: str, default_value: float) -> float:
    raw = input(f"{label} [{default_value:g}]: ").strip()
    if not raw:
        return default_value / 100.0
    raw = raw.rstrip("%").strip()
    try:
        return float(raw) / 100.0
    except ValueError:
        print(f"Invalid percent; using default {default_value:g}%.")
        return default_value / 100.0


def _prompt_state_id_override() -> str | None:
    raw = input("State ID override (blank to auto from store state): ").strip()
    return raw or None


def _prompt_inputs(
    pos_data_dir: Path,
) -> tuple[DateRange, str, float, float, float, str | None]:
    print("=== Royaltie Fee Audit ===")
    available_dates = common.list_available_dates(pos_data_dir)
    if available_dates:
        print(
            f"Available dates: {available_dates[0]} -> {available_dates[-1]} "
            f"({len(available_dates)} days)"
        )
    start_date = _prompt_date("Start date (YYYY-MM-DD): ")
    end_date = _prompt_date("End date (YYYY-MM-DD): ")
    if start_date > end_date:
        raise SystemExit("Start date must be <= end date.")

    date_range = DateRange(start_date=start_date, end_date=end_date)
    print(
        "Scan window: "
        f"{date_range.scan_dates[0].isoformat()} -> {date_range.scan_dates[-1].isoformat()} "
        f"({LOOKBACK_DAYS}-day backcheck, {LOOKAHEAD_DAYS}-day forward check)"
    )
    store_number = _prompt_store_number()
    royalty_rate = _prompt_percent("Royalty percent", DEFAULT_ROYALTY_PCT)
    advertising_rate = _prompt_percent("Advertising percent", DEFAULT_ADVERTISING_PCT)
    media_rate = _prompt_percent("Media percent", DEFAULT_MEDIA_PCT)
    state_id_override = _prompt_state_id_override()
    return (
        date_range,
        store_number,
        royalty_rate,
        advertising_rate,
        media_rate,
        state_id_override,
    )


def _load_store_map(day_dir: Path) -> pd.DataFrame:
    store = pd.read_csv(day_dir / "Store.txt", sep="|", dtype=str, encoding="latin1")
    store["Store_Number"] = store["Store_Number"].astype(str).str.strip()
    store["Store_ID"] = store["Store_ID"].astype(str).str.strip()
    if "State" in store.columns:
        store["State"] = store["State"].astype(str).str.strip().str.upper()
    else:
        store["State"] = ""
    return store[["Store_Number", "Store_ID", "State"]].drop_duplicates()


def _ticket_attr(store_st: pd.DataFrame, col: str, values: list[str]) -> set[str]:
    if col not in store_st.columns:
        return set()
    return set(
        store_st[store_st[col].astype(str).str.strip().isin(values)]["Ticket_Number"].astype(str)
    )


def _build_context_from_cache(
    *,
    pos_data_dir: Path,
    target_date_str: str,
    store_number: str,
    cross_date_sales: dict[str, tuple[pd.DataFrame, pd.DataFrame]],
    cross_date_payments: dict[str, pd.DataFrame],
    store_id: str | None = None,
) -> common.SalesContext:
    base_dir = pos_data_dir / target_date_str
    if store_id is None:
        store_id = common.load_store_id(base_dir, store_number)
    if target_date_str not in cross_date_sales:
        raise ValueError(f"No cross-date sales context found for {target_date_str}")

    store_st, sts = cross_date_sales[target_date_str]
    pay = cross_date_payments.get(target_date_str, pd.DataFrame())

    store_st = store_st[
        store_st["Store_ID"].astype(str).str.strip() == str(store_id)
    ].reset_index(drop=True)
    store_tix = set(store_st["Ticket_Number"].astype(str))
    all_paid = set(pay["Ticket_Number"].astype(str)) if not pay.empty else set()
    store_paid = store_tix & all_paid

    sts = sts.reset_index(drop=True).copy()
    for col in ["Taxable_Amount", "Non_Taxable_Amount", "Total"]:
        if col in sts.columns:
            sts[col] = common.to_num(sts[col])

    return common.SalesContext(
        target_date_str=target_date_str,
        store_number=str(store_number),
        store_id=str(store_id),
        store_st=store_st,
        sts=sts,
        store_tix=store_tix,
        store_paid=store_paid,
        non_exempt_tix=_ticket_attr(store_st, "Tax_Exempt", ["False"]),
        exempt_tix=_ticket_attr(store_st, "Tax_Exempt", ["True"]),
        tt_8_tix=_ticket_attr(store_st, "Ticket_Type_ID", ["8"]),
        tt_1_7_tix=_ticket_attr(store_st, "Ticket_Type_ID", ["1", "7"]),
        tt_5_tix=_ticket_attr(store_st, "Ticket_Type_ID", ["5"]),
        status_8_tix=_ticket_attr(store_st, "Status_ID", ["8"]),
        cancelled_tix=_ticket_attr(store_st, "Status_ID", ["2"]),
        refund_tix=_ticket_attr(store_st, "Refund", ["True"]),
    )


def _component_sum(
    ctx: common.SalesContext,
    ticket_set: set[str],
    *,
    category_ids: list[int],
    field: str,
    sign: int = 1,
) -> float:
    return sign * common.sts_sum(ctx.sts, ticket_set, category_ids, field)


def _compute_store_day(
    pos_data_dir: Path,
    target_date_str: str,
    store_number: str,
    cross_date_sales: dict[str, tuple[pd.DataFrame, pd.DataFrame]],
    cross_date_payments: dict[str, pd.DataFrame],
    store_state: str,
    state_id: str,
    royalty_rate: float,
    advertising_rate: float,
    media_rate: float,
    store_id: str | None = None,
) -> dict[str, object]:
    ctx = _build_context_from_cache(
        pos_data_dir=pos_data_dir,
        target_date_str=target_date_str,
        store_number=store_number,
        cross_date_sales=cross_date_sales,
        cross_date_payments=cross_date_payments,
        store_id=store_id,
    )

    paid_non_exempt = (ctx.store_paid - ctx.cancelled_tix) & ctx.non_exempt_tix
    paid_no_status8 = ctx.store_paid - (ctx.store_paid & ctx.status_8_tix)
    paid_exempt_tt8 = ctx.store_paid & ctx.exempt_tix & ctx.tt_8_tix
    paid_exempt_tt17 = ctx.store_paid & ctx.exempt_tix & ctx.tt_1_7_tix
    paid_third_party = ctx.store_paid & ctx.tt_8_tix

    taxable_sales = (
        _component_sum(ctx, paid_non_exempt, category_ids=[1], field="Taxable_Amount")
        - _component_sum(ctx, paid_non_exempt, category_ids=[2], field="Taxable_Amount")
    )
    non_taxable_sales = (
        _component_sum(ctx, paid_no_status8, category_ids=[1], field="Non_Taxable_Amount")
        - _component_sum(ctx, paid_no_status8, category_ids=[2], field="Non_Taxable_Amount")
        - _component_sum(ctx, paid_no_status8, category_ids=[7], field="Total")
    )
    third_party_tax_exempt_sales = (
        _component_sum(ctx, paid_exempt_tt8, category_ids=[1], field="Taxable_Amount")
        - _component_sum(ctx, paid_exempt_tt8, category_ids=[2], field="Taxable_Amount")
    )
    tax_exempt_sales = (
        _component_sum(ctx, paid_exempt_tt17, category_ids=[1], field="Taxable_Amount")
        - _component_sum(ctx, paid_exempt_tt17, category_ids=[2], field="Taxable_Amount")
    )
    total_sales = (
        taxable_sales
        + non_taxable_sales
        + tax_exempt_sales
        + third_party_tax_exempt_sales
    )

    surcharge_sales = common.sts_sum(ctx.sts, paid_third_party, [11], "Total")
    all_surcharge_sales = common.sts_sum(ctx.sts, ctx.store_paid, [11], "Total")
    non_third_party_surcharge_sales = all_surcharge_sales - surcharge_sales
    royalty_sales = total_sales - surcharge_sales
    royalty_fee = royalty_sales * royalty_rate
    advertising_fee = royalty_sales * advertising_rate
    media_fee = royalty_sales * media_rate

    return {
        "date": target_date_str,
        "store_number": store_number,
        "store_id": ctx.store_id,
        "state": store_state,
        "state_id": state_id,
        "store_paid_tickets": len(ctx.store_paid),
        "paid_non_exempt_tickets": len(paid_non_exempt),
        "paid_tax_exempt_tickets": len(paid_exempt_tt17),
        "paid_third_party_tax_exempt_tickets": len(paid_exempt_tt8),
        "paid_third_party_tickets": len(paid_third_party),
        "taxable_sales": round(taxable_sales, 2),
        "non_taxable_sales": round(non_taxable_sales, 2),
        "tax_exempt_sales": round(tax_exempt_sales, 2),
        "third_party_tax_exempt_sales": round(third_party_tax_exempt_sales, 2),
        "total_sales": round(total_sales, 2),
        "surcharge_sales": round(surcharge_sales, 2),
        "non_third_party_surcharge_sales": round(non_third_party_surcharge_sales, 2),
        "royalty_sales_raw": float(royalty_sales),
        "royalty_sales": round(royalty_sales, 2),
        "royalty_rate": round(royalty_rate, 6),
        "royalty_fee": round(royalty_fee, 2),
        "advertising_rate": round(advertising_rate, 6),
        "advertising_fee": round(advertising_fee, 2),
        "media_rate": round(media_rate, 6),
        "media_fee": round(media_fee, 2),
    }


def _write_outputs(
    out_dir: Path,
    detail_df: pd.DataFrame,
    royalties_export_df: pd.DataFrame,
    date_summary_df: pd.DataFrame,
    grand_summary_df: pd.DataFrame,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    royalties_export_df.to_csv(out_dir / "royalties_export_audit.csv", index=False)
    detail_df.to_csv(out_dir / "audit_royalty_fee_by_store_day.csv", index=False)
    date_summary_df.to_csv(out_dir / "audit_royalty_fee_by_date.csv", index=False)
    grand_summary_df.to_csv(out_dir / "audit_summary.csv", index=False)

    with pd.ExcelWriter(out_dir / "audit_royalty_fee.xlsx", engine="openpyxl") as writer:
        royalties_export_df.to_excel(writer, sheet_name="royalties_export", index=False)
        grand_summary_df.to_excel(writer, sheet_name="summary", index=False)
        date_summary_df.to_excel(writer, sheet_name="by_date", index=False)
        detail_df.to_excel(writer, sheet_name="by_store_day", index=False)


def run() -> None:
    root = common.repo_root()
    pos_data_dir = root / "pos_data"
    (
        date_range,
        store_number,
        royalty_rate,
        advertising_rate,
        media_rate,
        state_id_override,
    ) = _prompt_inputs(pos_data_dir)

    rows: list[dict[str, object]] = []
    missing_dates: list[str] = []
    skipped_store_days: list[dict[str, str]] = []
    existing_scan_dates = [
        d for d in date_range.scan_dates if (pos_data_dir / d.isoformat()).is_dir()
    ]
    cross_date_sales = common._build_cross_date_sales_context(  # type: ignore[attr-defined]
        pos_data_dir, existing_scan_dates
    )
    cross_date_payments = common._build_cross_date_payments(  # type: ignore[attr-defined]
        pos_data_dir, existing_scan_dates
    )

    for target in date_range.target_dates:
        target_date_str = target.isoformat()
        day_dir = pos_data_dir / target_date_str
        if not day_dir.is_dir():
            missing_dates.append(target_date_str)
            continue

        store_map = _load_store_map(day_dir)
        store_match = store_map[store_map["Store_Number"].eq(str(store_number))]
        if store_match.empty:
            skipped_store_days.append(
                {
                    "date": target_date_str,
                    "store_number": store_number,
                    "reason": f"Store {store_number} not found in Store.txt",
                }
            )
            continue

        store_state = str(store_match["State"].iloc[0]).strip().upper()
        state_id = state_id_override or DEFAULT_STATE_ID_BY_STATE.get(store_state, "")
        try:
            rows.append(
                _compute_store_day(
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

    if not rows:
        raise SystemExit("No royalty fee audit rows were produced.")

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
    total_days = len(date_range.target_dates)
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
        .sort_values("store_number")
    )
    royalties_export_df = pd.DataFrame(
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

    summary_rows: list[dict[str, object]] = [
        {"metric": "start_date", "value": date_range.start_date_str},
        {"metric": "end_date", "value": date_range.end_date_str},
        {"metric": "scan_start_date", "value": date_range.scan_dates[0].isoformat()},
        {"metric": "scan_end_date", "value": date_range.scan_dates[-1].isoformat()},
        {"metric": "store_number", "value": store_number},
        {"metric": "store_day_rows", "value": int(len(detail_df))},
        {"metric": "missing_date_folders", "value": len(missing_dates)},
        {"metric": "skipped_store_days", "value": len(skipped_store_days)},
    ]
    if missing_dates:
        summary_rows.append({"metric": "missing_dates", "value": ",".join(missing_dates)})
    if royalty_rate is not None:
        summary_rows.append({"metric": "royalty_rate", "value": round(royalty_rate, 6)})
    summary_rows.append({"metric": "advertising_rate", "value": round(advertising_rate, 6)})
    summary_rows.append({"metric": "media_rate", "value": round(media_rate, 6)})
    summary_rows.append({"metric": "state_id_override", "value": state_id_override or ""})
    for col in amount_cols:
        summary_rows.append({"metric": col, "value": round(float(detail_df[col].sum()), 2)})

    grand_summary_df = pd.DataFrame(summary_rows)

    out_dir = (
        common.script_root()
        / "audits"
        / OUTPUT_SLUG
        / date_range.period_key
        / str(store_number)
    )
    _write_outputs(out_dir, detail_df, royalties_export_df, date_summary_df, grand_summary_df)

    if skipped_store_days:
        pd.DataFrame(skipped_store_days).to_csv(
            out_dir / "audit_royalty_fee_skipped_store_days.csv", index=False
        )

    print(f"Audit written to: {out_dir}")


if __name__ == "__main__":
    run()
