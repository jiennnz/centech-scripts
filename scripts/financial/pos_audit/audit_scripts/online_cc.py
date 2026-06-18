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

ONLINE_CC_CATEGORY = "Online Credit card"
ONLINE_CC_TIPS_CATEGORY = "Online Credit Card Tips"


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
) -> tuple[pd.DataFrame, set[str]]:
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
        return pd.DataFrame(), set()

    target_sales = sales[
        (sales["_pay_date"] == target_date)
        & (sales["Store_ID"].astype(str).str.strip() == str(store_id))
    ]
    store_tickets = set(target_sales["Ticket_Number"].astype(str))

    refund_tix: set[str] = set()
    online_refund_candidate_tix: set[str] = set()
    online_card_tix = set(
        target_sales[target_sales["Ticket_Type_ID"].astype(str).str.strip() == "5"][
            "Ticket_Number"
        ].astype(str)
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
    df["Tip_Paid_s"] = df["Tip_Paid"].map(common.normalize_bool)
    df["Transaction_ID_s"] = df["Transaction_ID"].astype(str).str.strip()
    df["Transaction_ID_len"] = df["Transaction_ID_s"].str.len()
    df["Ticket_Number_s"] = df["Ticket_Number"].astype(str).str.strip()

    df["is_type_14"] = df["Payment_Type_ID_s"] == "14"
    df["is_type_3"] = df["Payment_Type_ID_s"] == "3"
    df["is_tlen_32"] = df["Transaction_ID_len"] == 32
    df["is_tip_true"] = df["Tip_Paid_s"] == "True"
    df["is_refund_ticket"] = df["Ticket_Number_s"].isin(refund_tix)
    df["is_online_ticket_type"] = df["Ticket_Number_s"].isin(online_card_tix)
    df["is_online_refund_candidate"] = df["Ticket_Number_s"].isin(online_refund_candidate_tix)

    online_refund_tix = set(
        df[df["is_online_refund_candidate"] & df["is_tlen_32"]]["Ticket_Number_s"].unique()
    )
    df["is_online_refund"] = df["Ticket_Number_s"].isin(online_refund_tix)

    df["online_cc_included"] = (
        df["is_type_14"]
        & df["is_tlen_32"]
        & df["is_online_ticket_type"]
        & (df["is_tip_true"] | df["is_online_refund"])
    )
    df["online_cc_tips_included"] = (
        (df["is_type_14"] | df["is_type_3"])
        & df["is_tlen_32"]
        & df["is_online_ticket_type"]
        & df["is_tip_true"]
        & (df["Tip_Amount"] != 0)
    )

    df["online_cc_component"] = df["Tendered_Amount"] + df["Tip_Amount"]
    df["online_cc_component_used"] = df["online_cc_component"].where(df["online_cc_included"], 0.0)
    df["online_cc_tips_component_used"] = df["Tip_Amount"].where(df["online_cc_tips_included"], 0.0)

    def classify(row: pd.Series) -> str:
        if not bool(row["is_type_14"]) and not bool(row["is_type_3"]):
            return "EXCLUDED_NOT_TYPE_14_OR_3"
        if not bool(row["is_tlen_32"]):
            return "EXCLUDED_TLEN_NOT_32"
        if not bool(row["is_online_ticket_type"]):
            return "EXCLUDED_NON_ONLINE_TICKET_TYPE"
        if bool(row["is_online_refund"]):
            return "INCLUDED_ONLINE_CC_REFUND"
        if bool(row["is_tip_true"]):
            return "INCLUDED_ONLINE_CC"
        return "EXCLUDED_TIP_FALSE_NOT_REFUND"

    df["rule_bucket"] = df.apply(classify, axis=1)
    df["audit_exclusion_reason_online_cc"] = ""
    df.loc[~df["is_type_14"], "audit_exclusion_reason_online_cc"] = "not_type_14"
    df.loc[df["is_type_14"] & ~df["is_tlen_32"], "audit_exclusion_reason_online_cc"] = "transaction_id_len_not_32"
    df.loc[
        df["is_type_14"] & df["is_tlen_32"] & ~df["is_online_ticket_type"],
        "audit_exclusion_reason_online_cc",
    ] = "ticket_type_not_online"
    df.loc[
        df["is_type_14"] & df["is_tlen_32"] & df["is_online_ticket_type"] & ~df["is_tip_true"] & ~df["is_online_refund"],
        "audit_exclusion_reason_online_cc",
    ] = "tip_paid_false_not_online_refund"
    df["audit_exclusion_reason_online_cc_tips"] = ""
    df.loc[~(df["is_type_14"] | df["is_type_3"]), "audit_exclusion_reason_online_cc_tips"] = "not_type_14_or_3"
    df.loc[
        (df["is_type_14"] | df["is_type_3"]) & ~df["is_tlen_32"],
        "audit_exclusion_reason_online_cc_tips",
    ] = "transaction_id_len_not_32"
    df.loc[
        (df["is_type_14"] | df["is_type_3"]) & df["is_tlen_32"] & ~df["is_online_ticket_type"],
        "audit_exclusion_reason_online_cc_tips",
    ] = "ticket_type_not_online"
    df.loc[
        (df["is_type_14"] | df["is_type_3"]) & df["is_tlen_32"] & df["is_online_ticket_type"] & ~df["is_tip_true"],
        "audit_exclusion_reason_online_cc_tips",
    ] = "tip_paid_false"
    df.loc[
        (df["is_type_14"] | df["is_type_3"]) & df["is_tlen_32"] & df["is_online_ticket_type"] & df["is_tip_true"] & (df["Tip_Amount"] == 0),
        "audit_exclusion_reason_online_cc_tips",
    ] = "tip_amount_zero"
    return df, online_refund_tix


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
    for cat in [ONLINE_CC_CATEGORY, ONLINE_CC_TIPS_CATEGORY]:
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
    payment_df, online_refund_tix = _load_payment_frame(day_dirs, store_id, config.target_date_str)

    type14_3_df = payment_df[payment_df["is_type_14"] | payment_df["is_type_3"]].copy() if not payment_df.empty else payment_df.copy()
    online_cc_df = payment_df[payment_df["online_cc_included"]].copy() if not payment_df.empty else payment_df.copy()
    online_cc_tips_df = payment_df[payment_df["online_cc_tips_included"]].copy() if not payment_df.empty else payment_df.copy()

    online_cc_total = float(online_cc_df["online_cc_component_used"].sum()) if not online_cc_df.empty else 0.0
    online_cc_tips_total = float(online_cc_tips_df["online_cc_tips_component_used"].sum()) if not online_cc_tips_df.empty else 0.0

    summary_rows: list[dict[str, object]] = [
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "scan_start_date", "value": config.scan_start_str},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "scan_end_date", "value": config.scan_end_str},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "all_payment_rows", "value": int(len(payment_df))},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "online_cc_total", "value": round(online_cc_total, 2)},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "online_cc_tips_total", "value": round(online_cc_tips_total, 2)},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "online_refund_tickets", "value": len(online_refund_tix)},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "type14_or_3_rows", "value": int(len(type14_3_df))},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "online_cc_rows", "value": int(len(online_cc_df))},
        {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "online_cc_tips_rows", "value": int(len(online_cc_tips_df))},
    ]

    if config.client_export is not None:
        client = _aggregate_export_side(config.client_export, config.target_date_str, config.store_number, side="client")
        summary_rows.extend(
            [
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "client_online_cc_debit", "value": round(client[f"{ONLINE_CC_CATEGORY}_debit"], 2)},
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "client_online_cc_tips_credit", "value": round(client[f"{ONLINE_CC_TIPS_CATEGORY}_credit"], 2)},
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "delta_online_cc_vs_client", "value": round(online_cc_total - client[f"{ONLINE_CC_CATEGORY}_debit"], 2)},
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "delta_online_cc_tips_vs_client", "value": round(online_cc_tips_total - client[f"{ONLINE_CC_TIPS_CATEGORY}_credit"], 2)},
            ]
        )

    if config.centech_export is not None:
        ct = _aggregate_export_side(config.centech_export, config.target_date_str, config.store_number, side="centech")
        summary_rows.extend(
            [
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "centech_online_cc_debit", "value": round(ct[f"{ONLINE_CC_CATEGORY}_debit"], 2)},
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "centech_online_cc_tips_credit", "value": round(ct[f"{ONLINE_CC_TIPS_CATEGORY}_credit"], 2)},
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "delta_online_cc_vs_centech", "value": round(online_cc_total - ct[f"{ONLINE_CC_CATEGORY}_debit"], 2)},
                {"date": config.target_date_str, "store_number": config.store_number, "store_id": store_id, "metric": "delta_online_cc_tips_vs_centech", "value": round(online_cc_tips_total - ct[f"{ONLINE_CC_TIPS_CATEGORY}_credit"], 2)},
            ]
        )

    out_dir = config.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_df = pd.DataFrame(summary_rows)
    payment_out = out_dir / "audit_payment_rows.csv"
    online_cc_out = out_dir / "audit_online_cc_rows.csv"
    tips_out = out_dir / "audit_online_cc_tips_rows.csv"
    summary_out = out_dir / "audit_summary.csv"

    payment_df.to_csv(payment_out, index=False)
    online_cc_df.to_csv(online_cc_out, index=False)
    online_cc_tips_df.to_csv(tips_out, index=False)
    summary_df.to_csv(summary_out, index=False)

    if config.write_excel:
        xlsx_out = out_dir / "audit_online_cc.xlsx"
        with pd.ExcelWriter(xlsx_out, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="summary", index=False)
            online_cc_df.to_excel(writer, sheet_name="online_cc_rows", index=False)
            online_cc_tips_df.to_excel(writer, sheet_name="online_cc_tips_rows", index=False)
            type14_3_df.to_excel(writer, sheet_name="all_type14_3_rows", index=False)

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
    window, store_number = common.prompt_audit_inputs("Online Credit Card Audit", pos_data_dir)
    cfg = AuditConfig(
        pos_data_dir=pos_data_dir,
        target_date_str=window.target_date_str,
        scan_start_str=window.start_date_str,
        scan_end_str=window.end_date_str,
        store_number=store_number,
        output_dir=common.output_dir_for("online_cc", window.target_date_str, store_number),
    )
    run(cfg)


if __name__ == "__main__":
    main()
