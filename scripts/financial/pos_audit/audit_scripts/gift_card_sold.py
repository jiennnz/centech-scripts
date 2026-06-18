from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import common  # type: ignore
else:
    from . import common

CATEGORY_NAME = "Gift Card Sold"


@dataclass(frozen=True)
class AuditConfig:
    pos_data_dir: Path
    target_date_str: str
    scan_start_str: str
    scan_end_str: str
    store_number: str
    output_dir: Path
    write_excel: bool = True


def _load_payment_rows(
    pos_data_dir: Path,
    scan_dates: list,
    target_date_str: str,
    store_tickets: set[str],
    status8_tickets: set[str],
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for day in scan_dates:
        pay_path = pos_data_dir / day.isoformat() / "Payment.txt"
        if not pay_path.exists():
            continue
        try:
            pay = pd.read_csv(pay_path, sep="|", dtype=str)
        except Exception:
            continue

        pay["source_folder"] = day.isoformat()
        pay["_pay_date"] = pd.to_datetime(pay["Payment_Date"], errors="coerce").dt.strftime("%Y-%m-%d")
        target_pay = pay[pay["_pay_date"] == target_date_str].copy()
        if not target_pay.empty:
            frames.append(target_pay)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df["Ticket_Number_s"] = df["Ticket_Number"].astype(str).str.strip()
    df = df[df["Ticket_Number_s"].isin(store_tickets)].copy()

    for col in ["Tendered_Amount", "Change", "Tip_Amount"]:
        df[col] = common.to_num(df[col])

    df["Payment_Type_ID_s"] = df["Payment_Type_ID"].astype(str).str.strip()
    df["Payment_Name_ID_s"] = df["Payment_Name_ID"].astype(str).str.strip()
    df["Processing_Status_ID_s"] = df["Processing_Status_ID"].astype(str).str.strip()
    df["Tip_Paid_s"] = df["Tip_Paid"].map(common.normalize_bool)
    df["Transaction_ID_s"] = df["Transaction_ID"].astype(str).str.strip()
    df["Transaction_ID_len"] = df["Transaction_ID_s"].str.len()
    df["is_status8_ticket"] = df["Ticket_Number_s"].isin(status8_tickets)
    df["gift_card_sold_included"] = df["is_status8_ticket"]
    df["net_tender"] = df["Tendered_Amount"] - df["Change"]
    df["gift_card_sold_component_used"] = df["net_tender"].where(
        df["gift_card_sold_included"], 0.0
    )
    df["audit_exclusion_reason"] = ""
    df.loc[~df["is_status8_ticket"], "audit_exclusion_reason"] = "ticket_status_not_8"
    return df.reset_index(drop=True)


def _build_summary_rows(ctx: common.SalesContext) -> pd.DataFrame:
    rows = ctx.sts.copy()
    rows["Ticket_Number_s"] = rows["Ticket_Number"].astype(str).str.strip()
    rows["Category_ID_s"] = rows["Category_ID"].astype(str).str.strip()
    rows["audit_ticket_in_store_paid"] = rows["Ticket_Number_s"].isin(ctx.store_paid)
    rows["audit_ticket_status8"] = rows["Ticket_Number_s"].isin(ctx.status_8_tix)
    rows["audit_category_1"] = rows["Category_ID_s"] == "1"
    rows["gift_card_sold_summary_included"] = (
        rows["audit_ticket_in_store_paid"]
        & rows["audit_ticket_status8"]
        & rows["audit_category_1"]
    )
    rows["summary_component_used"] = common.to_num(rows["Non_Taxable_Amount"]).where(
        rows["gift_card_sold_summary_included"], 0.0
    )
    rows["audit_exclusion_reason"] = ""
    rows.loc[~rows["audit_ticket_in_store_paid"], "audit_exclusion_reason"] = "ticket_not_paid"
    rows.loc[
        rows["audit_ticket_in_store_paid"] & ~rows["audit_ticket_status8"],
        "audit_exclusion_reason",
    ] = "ticket_status_not_8"
    rows.loc[
        rows["audit_ticket_in_store_paid"]
        & rows["audit_ticket_status8"]
        & ~rows["audit_category_1"],
        "audit_exclusion_reason",
    ] = "category_not_1"
    return rows.reset_index(drop=True)


def _build_per_ticket_join_evidence(
    payment_rows: pd.DataFrame, summary_rows: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if payment_rows.empty:
        empty = pd.DataFrame()
        return empty, empty

    gc_pay = payment_rows[payment_rows["gift_card_sold_included"]].copy()
    gc_summary = summary_rows[summary_rows["gift_card_sold_summary_included"]].copy()

    pay_per_ticket = gc_pay.groupby("Ticket_Number_s", dropna=False).agg(
        payment_rows=("Ticket_Number_s", "size"),
        payment_net_tender=("net_tender", "sum"),
        payment_component_used=("gift_card_sold_component_used", "sum"),
        payment_type_ids=("Payment_Type_ID_s", lambda s: "|".join(sorted(set(s)))),
        processing_status_ids=("Processing_Status_ID_s", lambda s: "|".join(sorted(set(s)))),
        source_folders=("source_folder", lambda s: "|".join(sorted(set(s)))),
    )
    summary_per_ticket = gc_summary.groupby("Ticket_Number_s", dropna=False).agg(
        summary_rows=("Ticket_Number_s", "size"),
        summary_non_taxable=("Non_Taxable_Amount", "sum"),
        summary_total=("Total", "sum"),
    )

    per_ticket = summary_per_ticket.merge(
        pay_per_ticket, left_index=True, right_index=True, how="outer"
    ).reset_index()
    per_ticket["payment_rows"] = per_ticket["payment_rows"].fillna(0).astype(int)
    for col in [
        "summary_rows",
        "summary_non_taxable",
        "summary_total",
        "payment_net_tender",
        "payment_component_used",
    ]:
        per_ticket[col] = common.to_num(per_ticket[col])

    per_ticket["joined_summary_contribution"] = (
        per_ticket["summary_non_taxable"] * per_ticket["payment_rows"]
    )
    per_ticket["join_overstatement"] = (
        per_ticket["joined_summary_contribution"] - per_ticket["summary_non_taxable"]
    )

    pattern = per_ticket.groupby(["payment_rows", "payment_type_ids"], dropna=False).agg(
        ticket_count=("Ticket_Number_s", "size"),
        summary_non_taxable=("summary_non_taxable", "sum"),
        payment_net_tender=("payment_net_tender", "sum"),
        joined_summary_contribution=("joined_summary_contribution", "sum"),
        join_overstatement=("join_overstatement", "sum"),
    ).reset_index()
    return per_ticket, pattern


def run(config: AuditConfig) -> None:
    window = common.build_scan_window(config.target_date_str)
    ctx = common.load_sales_context(
        config.pos_data_dir,
        config.target_date_str,
        config.store_number,
        window.scan_dates,
    )

    payment_rows = _load_payment_rows(
        config.pos_data_dir,
        window.scan_dates,
        config.target_date_str,
        ctx.store_tix,
        ctx.status_8_tix,
    )
    summary_rows = _build_summary_rows(ctx)
    per_ticket, join_pattern = _build_per_ticket_join_evidence(payment_rows, summary_rows)

    gc_payment_rows = (
        payment_rows[payment_rows["gift_card_sold_included"]].copy()
        if not payment_rows.empty
        else payment_rows.copy()
    )
    gc_summary_rows = summary_rows[summary_rows["gift_card_sold_summary_included"]].copy()

    payment_total = (
        float(gc_payment_rows["gift_card_sold_component_used"].sum())
        if not gc_payment_rows.empty
        else 0.0
    )
    summary_total = (
        float(gc_summary_rows["summary_component_used"].sum())
        if not gc_summary_rows.empty
        else 0.0
    )
    joined_summary_total = (
        float(per_ticket["joined_summary_contribution"].sum())
        if not per_ticket.empty
        else 0.0
    )
    duplicate_overstatement = joined_summary_total - summary_total
    gc_sold_cc = (
        float(
            gc_payment_rows.loc[
                gc_payment_rows["Payment_Type_ID_s"] == "14", "net_tender"
            ].sum()
        )
        if not gc_payment_rows.empty
        else 0.0
    )

    summary_df = pd.DataFrame(
        [
            {"date": config.target_date_str, "store_number": config.store_number, "store_id": ctx.store_id, "metric": "scan_start_date", "value": config.scan_start_str},
            {"date": config.target_date_str, "store_number": config.store_number, "store_id": ctx.store_id, "metric": "scan_end_date", "value": config.scan_end_str},
            {"date": config.target_date_str, "store_number": config.store_number, "store_id": ctx.store_id, "metric": "formula", "value": "SUM(Tendered_Amount - Change) for paid Sales_Ticket.Status_ID = 8"},
            {"date": config.target_date_str, "store_number": config.store_number, "store_id": ctx.store_id, "metric": "status8_paid_tickets", "value": len(ctx.store_paid & ctx.status_8_tix)},
            {"date": config.target_date_str, "store_number": config.store_number, "store_id": ctx.store_id, "metric": "gift_card_sold_payment_rows", "value": int(len(gc_payment_rows))},
            {"date": config.target_date_str, "store_number": config.store_number, "store_id": ctx.store_id, "metric": "gift_card_sold_credit", "value": round(payment_total, 2)},
            {"date": config.target_date_str, "store_number": config.store_number, "store_id": ctx.store_id, "metric": "gift_card_sold_summary_non_taxable", "value": round(summary_total, 2)},
            {"date": config.target_date_str, "store_number": config.store_number, "store_id": ctx.store_id, "metric": "joined_summary_total_if_summed_after_payment_join", "value": round(joined_summary_total, 2)},
            {"date": config.target_date_str, "store_number": config.store_number, "store_id": ctx.store_id, "metric": "duplicate_overstatement_if_summed_after_payment_join", "value": round(duplicate_overstatement, 2)},
            {"date": config.target_date_str, "store_number": config.store_number, "store_id": ctx.store_id, "metric": "gc_sold_cc_for_iscc_readd", "value": round(gc_sold_cc, 2)},
        ]
    )

    out_dir = config.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(out_dir / "audit_summary.csv", index=False)
    payment_rows.to_csv(out_dir / "audit_payment_rows.csv", index=False)
    gc_payment_rows.to_csv(out_dir / "audit_gift_card_sold_payment_rows.csv", index=False)
    summary_rows.to_csv(out_dir / "audit_ticket_summary_rows.csv", index=False)
    gc_summary_rows.to_csv(out_dir / "audit_gift_card_sold_summary_rows.csv", index=False)
    per_ticket.to_csv(out_dir / "audit_per_ticket_join_evidence.csv", index=False)
    join_pattern.to_csv(out_dir / "audit_join_duplication_pattern.csv", index=False)

    if config.write_excel:
        with pd.ExcelWriter(out_dir / "audit_gift_card_sold.xlsx", engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="summary", index=False)
            join_pattern.to_excel(writer, sheet_name="join_pattern", index=False)
            per_ticket.to_excel(writer, sheet_name="per_ticket", index=False)
            gc_payment_rows.to_excel(writer, sheet_name="payment_rows", index=False)
            gc_summary_rows.to_excel(writer, sheet_name="summary_rows", index=False)

    print(f"Audit written to: {out_dir}")


def main() -> None:
    root = common.repo_root()
    pos_data_dir = root / "pos_data"
    window, store_number = common.prompt_audit_inputs("Gift Card Sold Audit", pos_data_dir)
    cfg = AuditConfig(
        pos_data_dir=pos_data_dir,
        target_date_str=window.target_date_str,
        scan_start_str=window.start_date_str,
        scan_end_str=window.end_date_str,
        store_number=store_number,
        output_dir=common.output_dir_for("gift_card_sold", window.target_date_str, store_number),
    )
    run(cfg)


if __name__ == "__main__":
    main()
