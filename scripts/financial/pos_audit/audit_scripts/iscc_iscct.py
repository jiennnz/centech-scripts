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

ISCC_CATEGORY = "In-Store Credit Card"
ISCCT_CATEGORY = "In-Store Credit Card Tips"


@dataclass(frozen=True)
class AuditConfig:
    pos_data_dir: Path
    target_date_str: str
    scan_start_str: str
    scan_end_str: str
    store_number: str
    output_dir: Path
    client_export: Path | None = None
    centech_export: Path | None = None
    write_excel: bool = True


def _load_payment_frame(
    day_dirs: list[Path], store_id: str, target_date: str
) -> tuple[pd.DataFrame, set[str], set[str], set[str]]:
    payment_frames: list[pd.DataFrame] = []
    sales_frames: list[pd.DataFrame] = []

    for day_dir in day_dirs:
        if not (day_dir / "Sales_Ticket.txt").exists() or not (day_dir / "Payment.txt").exists():
            continue

        st = pd.read_csv(day_dir / "Sales_Ticket.txt", sep="|", dtype=str)
        pay = pd.read_csv(day_dir / "Payment.txt", sep="|", dtype=str)
        pay["_pay_date"] = pd.to_datetime(pay["Payment_Date"], errors="coerce").dt.strftime("%Y-%m-%d")

        target_pay = pay[pay["_pay_date"] == target_date].copy()
        if not target_pay.empty:
            target_pay["source_folder"] = day_dir.name
            payment_frames.append(target_pay)

        ticket_dates = pay[["Ticket_Number", "_pay_date"]].dropna().drop_duplicates()
        if not ticket_dates.empty:
            sales_frames.append(st.merge(ticket_dates, on="Ticket_Number", how="inner"))

    payments = pd.concat(payment_frames, ignore_index=True) if payment_frames else pd.DataFrame()
    sales = pd.concat(sales_frames, ignore_index=True) if sales_frames else pd.DataFrame()

    if payments.empty or sales.empty:
        return pd.DataFrame(), set(), set(), set()

    target_sales = sales[
        (sales["_pay_date"] == target_date)
        & (sales["Store_ID"].astype(str).str.strip() == str(store_id))
    ]
    store_tickets = set(target_sales["Ticket_Number"].astype(str))
    status8_tix = set(
        target_sales[target_sales["Status_ID"].astype(str).str.strip() == "8"][
            "Ticket_Number"
        ].astype(str)
    )
    cancelled_tix = set(
        target_sales[target_sales["Status_ID"].astype(str).str.strip() == "2"][
            "Ticket_Number"
        ].astype(str)
    )
    refund_tix: set[str] = set()
    online_refund_candidate_tix: set[str] = set()
    instore_card_tix = set(
        target_sales[
            target_sales["Ticket_Type_ID"].astype(str).str.strip().isin(["1", "2", "3", "4", "6", "7"])
        ]["Ticket_Number"].astype(str)
    )
    if "Refund" in target_sales.columns:
        refund_tix = set(
            target_sales[
                target_sales["Refund"].astype(str).str.strip().str.lower() == "true"
            ]["Ticket_Number"].astype(str)
        )
        online_refund_candidate_tix = set(
            target_sales[
                (target_sales["Refund"].astype(str).str.strip().str.lower() == "true")
                & (target_sales["Ticket_Type_ID"].astype(str).str.strip() == "5")
            ]["Ticket_Number"].astype(str)
        )
    df = payments[payments["Ticket_Number"].astype(str).isin(store_tickets)].copy()

    for col in ["Tendered_Amount", "Change", "Tip_Amount"]:
        df[col] = common.to_num(df[col])

    df["Payment_Type_ID_s"] = df["Payment_Type_ID"].astype(str).str.strip()
    df["Processing_Status_ID_s"] = df["Processing_Status_ID"].astype(str).str.strip()
    df["Tip_Paid_s"] = df["Tip_Paid"].map(common.normalize_bool)
    df["Transaction_ID_s"] = df["Transaction_ID"].astype(str).str.strip()
    df["Transaction_ID_len"] = df["Transaction_ID_s"].str.len()

    df["is_type_14"] = df["Payment_Type_ID_s"] == "14"
    df["is_status_4"] = df["Processing_Status_ID_s"] == "4"
    df["is_status_8"] = df["Processing_Status_ID_s"] == "8"
    df["is_status_2"] = df["Processing_Status_ID_s"] == "2"

    # Status-2 (Open) included only if ticket has exactly one type-14 row in the scan window.
    # Multiple rows mean it was reprocessed (later folder has status-4) or is a duplicate.
    _type14_counts = df[df["is_type_14"]].groupby("Ticket_Number").size()
    df["_type14_count"] = df["Ticket_Number"].map(_type14_counts).fillna(0).astype(int)
    df["is_status_2_sole"] = df["is_status_2"] & df["is_type_14"] & (df["_type14_count"] == 1)
    df["is_status_eligible"] = df["is_status_4"] | df["is_status_8"] | df["is_status_2_sole"]

    df["is_6_true"] = (df["Transaction_ID_len"] == 6) & (df["Tip_Paid_s"] == "True")
    df["is_32_false"] = (df["Transaction_ID_len"] == 32) & (df["Tip_Paid_s"] == "False")
    df["is_4_any"] = df["Transaction_ID_len"] == 4
    df["is_32_true"] = (df["Transaction_ID_len"] == 32) & (df["Tip_Paid_s"] == "True")

    df["is_refund_ticket"] = df["Ticket_Number"].astype(str).isin(refund_tix)
    df["is_cancelled_ticket"] = df["Ticket_Number"].astype(str).isin(cancelled_tix)
    df["is_online_refund_candidate"] = df["Ticket_Number"].astype(str).isin(online_refund_candidate_tix)
    df["is_instore_ticket_type"] = df["Ticket_Number"].astype(str).isin(instore_card_tix)
    online_refund_tix = set(
        df[df["is_online_refund_candidate"] & (df["Transaction_ID_len"] == 32)]["Ticket_Number"].astype(str).unique()
    )
    df["is_online_refund"] = df["Ticket_Number"].astype(str).isin(online_refund_tix)

    df["iscc_included"] = df["is_type_14"] & df["is_status_eligible"] & ~df["is_online_refund"] & ~df["is_cancelled_ticket"] & (
        df["is_6_true"] | ((df["Transaction_ID_len"] == 32) & df["is_instore_ticket_type"]) | df["is_4_any"]
    )
    df["iscct_included"] = (
        df["is_type_14"]
        & df["is_status_eligible"]
        & ~df["is_online_refund"]
        & (df["Transaction_ID_len"].isin([4, 6]) | ((df["Transaction_ID_len"] == 32) & df["is_instore_ticket_type"]))
        & (df["Tip_Amount"] != 0)
    )

    df["iscc_component"] = df["Tendered_Amount"] - df["Change"] + df["Tip_Amount"]
    df["iscc_component_used"] = df["iscc_component"].where(df["iscc_included"], 0.0)
    df["iscct_component_used"] = df["Tip_Amount"].where(df["iscct_included"], 0.0)

    def classify(row: pd.Series) -> str:
        if not bool(row["is_type_14"]):
            return "EXCLUDED_NOT_TYPE_14"
        if bool(row["is_online_refund"]):
            return "EXCLUDED_ONLINE_REFUND"
        if bool(row["is_cancelled_ticket"]):
            return "EXCLUDED_CANCELLED_TICKET"
        if bool(row["iscc_included"]) and bool(row["iscct_included"]):
            return "INCLUDED_ISCC_AND_ISCCT"
        if bool(row["iscc_included"]) and not bool(row["iscct_included"]):
            return "INCLUDED_ISCC_ONLY"
        if bool(row["is_32_true"]):
            return "EXCLUDED_ONLINE_CC_32_TRUE"
        return "EXCLUDED_TYPE14_OTHER"

    df["rule_bucket"] = df.apply(classify, axis=1)
    df["audit_exclusion_reason_iscc"] = ""
    df.loc[~df["is_type_14"], "audit_exclusion_reason_iscc"] = "not_type_14"
    df.loc[df["is_type_14"] & ~df["is_status_eligible"], "audit_exclusion_reason_iscc"] = "processing_status_not_4_8_or_2"
    df.loc[df["is_type_14"] & df["is_status_2"] & ~df["is_status_2_sole"], "audit_exclusion_reason_iscc"] = "processing_status_2_duplicate_ticket"
    df.loc[df["is_online_refund"], "audit_exclusion_reason_iscc"] = "online_refund"
    df.loc[df["is_cancelled_ticket"], "audit_exclusion_reason_iscc"] = "cancelled_ticket"
    df.loc[
        df["is_type_14"]
        & df["is_status_eligible"]
        & ~df["is_online_refund"]
        & ~df["is_cancelled_ticket"]
        & ~(df["is_6_true"] | ((df["Transaction_ID_len"] == 32) & df["is_instore_ticket_type"]) | df["is_4_any"]),
        "audit_exclusion_reason_iscc",
    ] = "transaction_shape_not_matched"
    df["audit_exclusion_reason_iscct"] = ""
    df.loc[~df["is_type_14"], "audit_exclusion_reason_iscct"] = "not_type_14"
    df.loc[df["is_type_14"] & ~df["is_status_eligible"], "audit_exclusion_reason_iscct"] = "processing_status_not_4_8_or_2"
    df.loc[df["is_type_14"] & df["is_status_2"] & ~df["is_status_2_sole"], "audit_exclusion_reason_iscct"] = "processing_status_2_duplicate_ticket"
    df.loc[df["is_online_refund"], "audit_exclusion_reason_iscct"] = "online_refund"
    df.loc[
        df["is_type_14"] & df["is_status_eligible"] & ~df["is_online_refund"] & ~(df["Transaction_ID_len"].isin([4, 6]) | ((df["Transaction_ID_len"] == 32) & df["is_instore_ticket_type"])),
        "audit_exclusion_reason_iscct",
    ] = "transaction_shape_not_matched"
    df.loc[
        df["is_type_14"]
        & df["is_status_eligible"]
        & ~df["is_online_refund"]
        & (df["Transaction_ID_len"].isin([4, 6]) | ((df["Transaction_ID_len"] == 32) & df["is_instore_ticket_type"]))
        & (df["Tip_Amount"] == 0),
        "audit_exclusion_reason_iscct",
    ] = "tip_amount_zero"
    return df, status8_tix, online_refund_tix, cancelled_tix


def _aggregate_export_side(
    path: Path, date_iso: str, store_number: str, side: str
) -> dict[str, float]:
    if side == "client":
        df = pd.read_csv(path, dtype=str)
        required = ["JournalDate", "Class", "Description", "Debits", "Credits"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"{path} missing required column: {col}")
        work = df.copy()
        work["_date"] = pd.to_datetime(work["JournalDate"], errors="coerce")
        work["_store"] = work["Class"].astype(str).str.extract(r"^\s*(\d+)", expand=False)
        work["_category"] = work["Description"].astype(str).str.strip()
        work["_debit"] = common.to_num(work["Debits"])
        work["_credit"] = common.to_num(work["Credits"])
    elif side == "centech":
        if path.suffix.lower() in {".xlsx", ".xls"}:
            df = pd.read_excel(path, engine="openpyxl", dtype=str)
        else:
            df = pd.read_csv(path, dtype=str)
        required = ["Date", "Class", "Transaction Category", "Debit", "Credit"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"{path} missing required column: {col}")
        work = df.copy()
        work["_date"] = pd.to_datetime(work["Date"], errors="coerce")
        work["_store"] = work["Class"].astype(str).str.strip()
        work["_category"] = work["Transaction Category"].astype(str).str.strip()
        work["_debit"] = common.to_num(work["Debit"])
        work["_credit"] = common.to_num(work["Credit"])
    else:
        raise ValueError(f"Unknown side: {side}")

    target_date = pd.to_datetime(date_iso).date()
    work = work[(work["_date"].dt.date == target_date) & (work["_store"] == str(store_number))]

    out: dict[str, float] = {}
    for cat in [ISCC_CATEGORY, ISCCT_CATEGORY]:
        sub = work[work["_category"] == cat]
        out[f"{cat}_debit"] = float(sub["_debit"].sum())
        out[f"{cat}_credit"] = float(sub["_credit"].sum())
    return out


def run(config: AuditConfig) -> None:
    base_dir = config.pos_data_dir / config.target_date_str
    if not base_dir.is_dir():
        raise ValueError(f"Date directory not found: {base_dir}")

    scan_dates = common.build_scan_window(config.target_date_str).scan_dates
    day_dirs = common.existing_scan_dirs(config.pos_data_dir, scan_dates)
    store_id = common.load_store_id(base_dir, config.store_number)
    payment_df, status8_tix, online_refund_tix, cancelled_tix = _load_payment_frame(day_dirs, store_id, config.target_date_str)

    if not payment_df.empty:
        payment_df["audit_excluded_status8_ticket"] = payment_df["Ticket_Number"].astype(str).isin(status8_tix)
        payment_df["iscc_included"] = payment_df["iscc_included"] & ~payment_df["audit_excluded_status8_ticket"]
        payment_df.loc[
            payment_df["audit_excluded_status8_ticket"], "audit_exclusion_reason_iscc"
        ] = "status8_ticket"

    type14_df = payment_df[payment_df["is_type_14"]].copy() if not payment_df.empty else payment_df.copy()
    iscc_df = payment_df[payment_df["iscc_included"]].copy() if not payment_df.empty else payment_df.copy()
    iscct_df = payment_df[payment_df["iscct_included"]].copy() if not payment_df.empty else payment_df.copy()

    iscc_total = float(iscc_df["iscc_component_used"].sum()) if not iscc_df.empty else 0.0
    iscct_total = float(iscct_df["iscct_component_used"].sum()) if not iscct_df.empty else 0.0
    iscc_base = float((iscc_df["Tendered_Amount"] - iscc_df["Change"]).sum()) if not iscc_df.empty else 0.0

    # CC-paid portion of gift card sold — excluded from qualifying rows but re-added to ISCC
    # to match verifier logic (verifier.py: instore_cc = qualifying_sum + gc_sold_cc).
    gc_sold_cc = 0.0
    gc_df = pd.DataFrame()
    if not payment_df.empty and status8_tix:
        gc_df = payment_df[
            payment_df["Ticket_Number"].astype(str).isin(status8_tix)
            & payment_df["is_type_14"]
        ].copy()
        gc_sold_cc = float((gc_df["Tendered_Amount"] - gc_df["Change"]).sum())
    iscc_total += gc_sold_cc

    summary_rows: list[dict[str, object]] = [
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "scan_start_date", "value": config.scan_start_str},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "scan_end_date", "value": config.scan_end_str},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "all_payment_rows", "value": int(len(payment_df))},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "iscc_total", "value": round(iscc_total, 2)},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "gc_sold_cc", "value": round(gc_sold_cc, 2)},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "iscct_total", "value": round(iscct_total, 2)},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "iscc_base_without_tips", "value": round(iscc_base, 2)},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "type14_rows", "value": int(len(type14_df))},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "iscc_rows", "value": int(len(iscc_df))},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "iscct_rows", "value": int(len(iscct_df))},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "online_refund_tickets_excluded", "value": len(online_refund_tix)},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "cancelled_tickets_excluded_from_iscc", "value": len(cancelled_tix)},
    ]

    if config.client_export is not None:
        client = _aggregate_export_side(config.client_export, config.target_date_str, config.store_number, side="client")
        summary_rows.extend(
            [
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "client_iscc_debit", "value": round(client[f"{ISCC_CATEGORY}_debit"], 2)},
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "client_iscct_credit", "value": round(client[f"{ISCCT_CATEGORY}_credit"], 2)},
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "delta_iscc_vs_client", "value": round(iscc_total - client[f"{ISCC_CATEGORY}_debit"], 2)},
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "delta_iscct_vs_client", "value": round(iscct_total - client[f"{ISCCT_CATEGORY}_credit"], 2)},
            ]
        )

    if config.centech_export is not None:
        ct = _aggregate_export_side(config.centech_export, config.target_date_str, config.store_number, side="centech")
        summary_rows.extend(
            [
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "centech_iscc_debit", "value": round(ct[f"{ISCC_CATEGORY}_debit"], 2)},
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "centech_iscct_credit", "value": round(ct[f"{ISCCT_CATEGORY}_credit"], 2)},
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "delta_iscc_vs_centech", "value": round(iscc_total - ct[f"{ISCC_CATEGORY}_debit"], 2)},
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "delta_iscct_vs_centech", "value": round(iscct_total - ct[f"{ISCCT_CATEGORY}_credit"], 2)},
            ]
        )

    out_dir = config.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_df = pd.DataFrame(summary_rows)
    payment_out = out_dir / "audit_payment_rows.csv"
    iscc_out = out_dir / "audit_iscc_rows.csv"
    iscct_out = out_dir / "audit_iscct_rows.csv"
    gc_out = out_dir / "audit_gc_sold_cc_rows.csv"
    summary_out = out_dir / "audit_summary.csv"

    payment_df.to_csv(payment_out, index=False)
    iscc_df.to_csv(iscc_out, index=False)
    iscct_df.to_csv(iscct_out, index=False)
    gc_df.to_csv(gc_out, index=False)
    summary_df.to_csv(summary_out, index=False)

    if config.write_excel:
        xlsx_out = out_dir / "audit_iscc_iscct.xlsx"
        with pd.ExcelWriter(xlsx_out, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="summary", index=False)
            iscc_df.to_excel(writer, sheet_name="iscc_rows", index=False)
            iscct_df.to_excel(writer, sheet_name="iscct_rows", index=False)
            gc_df.to_excel(writer, sheet_name="gc_sold_cc_rows", index=False)
            type14_df.to_excel(writer, sheet_name="all_type14_rows", index=False)

        tickets_out = out_dir / "all_ticket_payments.xlsx"
        with pd.ExcelWriter(tickets_out, engine="openpyxl") as writer:
            payment_df.to_excel(writer, sheet_name="all", index=False)
            if not payment_df.empty and "source_folder" in payment_df.columns:
                for folder_name, group in payment_df.groupby("source_folder"):
                    group.to_excel(writer, sheet_name=str(folder_name), index=False)

    print(f"Audit written to: {out_dir}")


def main() -> None:
    root = common.repo_root()
    pos_data_dir = root / "pos_data"
    window, store_number = common.prompt_audit_inputs("ISCC/ISCCT Audit", pos_data_dir)
    cfg = AuditConfig(
        pos_data_dir=pos_data_dir,
        target_date_str=window.target_date_str,
        scan_start_str=window.start_date_str,
        scan_end_str=window.end_date_str,
        store_number=store_number,
        output_dir=common.output_dir_for("iscc", window.target_date_str, store_number),
    )
    run(cfg)


if __name__ == "__main__":
    main()
