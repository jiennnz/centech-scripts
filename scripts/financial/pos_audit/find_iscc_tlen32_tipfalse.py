from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / "audit_scripts"))

import common  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find ISCC-included rows where Transaction_ID length is 32 and "
            "Tip_Paid is False."
        )
    )
    parser.add_argument(
        "--date",
        help="Optional single target date in YYYY-MM-DD format. Defaults to all dates.",
    )
    parser.add_argument(
        "--store",
        help="Optional single store number filter.",
    )
    return parser.parse_args()


def available_dates(pos_data_dir: Path, target_date: str | None) -> list[str]:
    if target_date:
        return [target_date]
    return common.list_available_dates(pos_data_dir)


def render_progress(current: int, total: int, label: str) -> None:
    width = 32
    filled = width if total == 0 else int(width * current / total)
    bar = "#" * filled + "-" * (width - filled)
    print(f"\r[{bar}] {current}/{total} {label}", end="", flush=True)


def load_target_frames(day_dirs: list[Path], target_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    payment_frames: list[pd.DataFrame] = []
    sales_frames: list[pd.DataFrame] = []

    for day_dir in day_dirs:
        st_path = day_dir / "Sales_Ticket.txt"
        pay_path = day_dir / "Payment.txt"
        if not st_path.exists() or not pay_path.exists():
            continue

        try:
            st = pd.read_csv(st_path, sep="|", dtype=str)
            pay = pd.read_csv(pay_path, sep="|", dtype=str)
        except Exception:
            continue

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
    return payments, sales


def find_matches_for_date(pos_data_dir: Path, target_date: str, store_filter: str | None) -> pd.DataFrame:
    window = common.build_scan_window(target_date)
    day_dirs = common.existing_scan_dirs(pos_data_dir, window.scan_dates)
    payments, sales = load_target_frames(day_dirs, target_date)
    if payments.empty or sales.empty:
        return pd.DataFrame()

    base_dir = pos_data_dir / target_date
    store_path = base_dir / "Store.txt"
    if not store_path.exists():
        return pd.DataFrame()

    store_map = pd.read_csv(store_path, sep="|", dtype=str)[["Store_ID", "Store_Number"]].drop_duplicates()
    store_map["Store_ID"] = store_map["Store_ID"].astype(str).str.strip()
    store_map["Store_Number"] = store_map["Store_Number"].astype(str).str.strip()
    store_lookup = dict(store_map.itertuples(index=False, name=None))

    target_sales = sales[sales["_pay_date"] == target_date].copy()
    if target_sales.empty:
        return pd.DataFrame()

    target_sales["Store_ID_s"] = target_sales["Store_ID"].astype(str).str.strip()
    if store_filter:
        wanted_store_ids = {sid for sid, snum in store_lookup.items() if snum == str(store_filter).strip()}
        target_sales = target_sales[target_sales["Store_ID_s"].isin(wanted_store_ids)]
        if target_sales.empty:
            return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for store_id, sales_group in target_sales.groupby("Store_ID_s"):
        store_number = store_lookup.get(store_id)
        if not store_number:
            continue

        store_tickets = set(sales_group["Ticket_Number"].astype(str))
        status8_tix = set(
            sales_group[sales_group["Status_ID"].astype(str).str.strip() == "8"]["Ticket_Number"].astype(str)
        )
        refund_tix: set[str] = set()
        if "Refund" in sales_group.columns:
            refund_tix = set(
                sales_group[sales_group["Refund"].astype(str).str.strip().str.lower() == "true"]["Ticket_Number"].astype(str)
            )

        payment_df = payments[payments["Ticket_Number"].astype(str).isin(store_tickets)].copy()
        if payment_df.empty:
            continue

        for col in ["Tendered_Amount", "Change", "Tip_Amount"]:
            payment_df[col] = common.to_num(payment_df[col])

        payment_df["Payment_Type_ID_s"] = payment_df["Payment_Type_ID"].astype(str).str.strip()
        payment_df["Processing_Status_ID_s"] = payment_df["Processing_Status_ID"].astype(str).str.strip()
        payment_df["Tip_Paid_s"] = payment_df["Tip_Paid"].map(common.normalize_bool)
        payment_df["Transaction_ID_s"] = payment_df["Transaction_ID"].astype(str).str.strip()
        payment_df["Transaction_ID_len"] = payment_df["Transaction_ID_s"].str.len()

        payment_df["is_type_14"] = payment_df["Payment_Type_ID_s"] == "14"
        payment_df["is_status_4"] = payment_df["Processing_Status_ID_s"] == "4"
        payment_df["is_6_true"] = (payment_df["Transaction_ID_len"] == 6) & (payment_df["Tip_Paid_s"] == "True")
        payment_df["is_32_false"] = (payment_df["Transaction_ID_len"] == 32) & (payment_df["Tip_Paid_s"] == "False")
        payment_df["is_4_any"] = payment_df["Transaction_ID_len"] == 4
        payment_df["is_refund_ticket"] = payment_df["Ticket_Number"].astype(str).isin(refund_tix)

        online_refund_tix = set(
            payment_df[
                payment_df["is_refund_ticket"] & (payment_df["Transaction_ID_len"] == 32)
            ]["Ticket_Number"].astype(str).unique()
        )
        payment_df["is_online_refund"] = payment_df["Ticket_Number"].astype(str).isin(online_refund_tix)
        payment_df["audit_excluded_status8_ticket"] = payment_df["Ticket_Number"].astype(str).isin(status8_tix)
        payment_df["iscc_included"] = (
            payment_df["is_type_14"]
            & payment_df["is_status_4"]
            & ~payment_df["is_online_refund"]
            & (payment_df["is_6_true"] | payment_df["is_32_false"] | payment_df["is_4_any"])
            & ~payment_df["audit_excluded_status8_ticket"]
        )

        match_df = payment_df[payment_df["iscc_included"] & payment_df["is_32_false"]].copy()
        if match_df.empty:
            continue

        match_df.insert(0, "target_date", target_date)
        match_df.insert(1, "store_number", store_number)
        frames.append(match_df)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    args = parse_args()
    root = common.repo_root()
    pos_data_dir = root / "pos_data"
    out_dir = SCRIPT_DIR / "audits" / "iscc" / "_ad_hoc"
    out_dir.mkdir(parents=True, exist_ok=True)

    dates = available_dates(pos_data_dir, args.date)
    all_matches: list[pd.DataFrame] = []

    for idx, target_date in enumerate(dates, start=1):
        render_progress(idx - 1, len(dates), target_date)
        match_df = find_matches_for_date(pos_data_dir, target_date, args.store)
        if not match_df.empty:
            all_matches.append(match_df)
    render_progress(len(dates), len(dates), "done")
    print()

    if not all_matches:
        print("No ISCC matches found for Transaction_ID length 32 and Tip_Paid False.")
        return

    out_df = pd.concat(all_matches, ignore_index=True)
    audit_path = out_dir / "iscc_tlen32_tipfalse_all_matches.csv"
    out_df.to_csv(audit_path, index=False)

    summary = (
        out_df.groupby(["target_date", "store_number"], as_index=False)
        .size()
        .rename(columns={"size": "match_count"})
        .sort_values(["target_date", "store_number"])
    )

    print(f"Ticket-level audit written to: {audit_path}")
    for row in summary.itertuples(index=False):
        print(f"{row.target_date} | store {row.store_number} | matches {row.match_count}")


if __name__ == "__main__":
    main()
