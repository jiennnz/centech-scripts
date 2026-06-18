from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import common  # type: ignore
else:
    from . import common

CATEGORY_NAME = "Register Audit"


def run() -> None:
    root = common.repo_root()
    pos_data_dir = root / "pos_data"
    window, store_number = common.prompt_audit_inputs("Register Audit", pos_data_dir)
    store_id, txn = common.load_store_transactions(
        pos_data_dir, window.target_date_str, store_number, window.scan_dates
    )

    # DailyJournal is same-day only — no cross-date needed.
    dj_path = pos_data_dir / window.target_date_str / "DailyJournal.txt"
    try:
        dj = pd.read_csv(dj_path, sep="|", dtype=str)
        dj["Action"]       = dj["Action"].str.strip()
        dj["Store_Number"] = dj["Store_Number"].str.strip()
    except FileNotFoundError:
        dj = pd.DataFrame(columns=["Action", "Store_Number", "Comments", "Amount"])

    dj_store = dj[dj["Store_Number"] == str(store_number)] if not dj.empty else pd.DataFrame()
    ra_dj = (
        dj_store[dj_store["Action"] == "Register Audit"].reset_index(drop=True)
        if not dj_store.empty
        else pd.DataFrame()
    )

    # ── Phase 1: DailyJournal — find real Over/Short and cancelled re-audit rows ──
    # Cancelled row: Amount == parsed Over/Short value (cashier voided and re-did audit).
    # Walk backwards; first non-cancelled parseable row = real over/short.
    cash_over_short = 0.0
    _ra_dj_cancelled = False
    _cancelled_ra_counts: Counter = Counter()

    ra_dj_annotated = ra_dj.copy() if not ra_dj.empty else pd.DataFrame()

    if not ra_dj.empty:
        # Forward pass: count all cancelled rows (used later to skip matching txn rows).
        for _, row in ra_dj.iterrows():
            m = re.search(r"Over/Short:\s*([-\d.]+)", str(row.get("Comments", "")))
            if m:
                cos_val = float(m.group(1))
                dj_amount = pd.to_numeric(row.get("Amount", None), errors="coerce")
                if pd.notna(dj_amount) and dj_amount == cos_val:
                    _cancelled_ra_counts[cos_val] += 1

        # Backward pass: find real over/short + annotate each row.
        parsed_ovsh_by_idx: dict = {}
        is_cancelled_by_idx: dict = {}
        _any_cancelled = False
        _found_real = False

        for idx, row in ra_dj.iloc[::-1].iterrows():
            m = re.search(r"Over/Short:\s*([-\d.]+)", str(row.get("Comments", "")))
            cos_val = float(m.group(1)) if m else None
            dj_amount = pd.to_numeric(row.get("Amount", None), errors="coerce")
            is_cancelled = m is not None and pd.notna(dj_amount) and dj_amount == cos_val
            parsed_ovsh_by_idx[idx] = cos_val
            is_cancelled_by_idx[idx] = is_cancelled
            if is_cancelled:
                _any_cancelled = True
            elif m is not None and not _found_real:
                cash_over_short = cos_val
                _found_real = True

        if _any_cancelled and not _found_real:
            _ra_dj_cancelled = True

        ra_dj_annotated["audit_parsed_ovsh"]  = ra_dj.index.map(parsed_ovsh_by_idx)
        ra_dj_annotated["audit_is_cancelled"] = ra_dj.index.map(is_cancelled_by_idx)

    # ── Phase 2: Store_Transactions — pick surviving Register Audit row ────────
    ra_txn = txn[
        txn["Transaction_Type_Name"].astype(str).str.strip() == "Register Audit"
    ].copy()

    register_audit = 0.0

    if not ra_txn.empty:
        ra_txn["audit_amount"]            = common.to_num(ra_txn["Amount"])
        ra_txn["audit_status"]            = (
            ra_txn["Status"].astype(str).str.strip() if "Status" in ra_txn.columns else ""
        )
        ra_txn["audit_is_cancelled_by_dj"] = False
        ra_txn["audit_included"]           = False
        ra_txn["audit_exclusion_reason"]   = ""

        ra_txn.loc[ra_txn["audit_status"] == "Void", "audit_exclusion_reason"] = "status_void"

        candidate = ra_txn[ra_txn["audit_status"] != "Void"]
        _working_counts = Counter(_cancelled_ra_counts)

        for idx, row in candidate.iloc[::-1].iterrows():
            ra_amount = float(row["audit_amount"])
            if _working_counts[ra_amount] > 0:
                _working_counts[ra_amount] -= 1
                ra_txn.at[idx, "audit_is_cancelled_by_dj"] = True
                ra_txn.at[idx, "audit_exclusion_reason"]   = "cancelled_by_dj"
                continue
            register_audit = ra_amount
            ra_txn.at[idx, "audit_included"] = True
            break

    if _ra_dj_cancelled:
        register_audit = 0.0
        if not ra_txn.empty:
            was_included = ra_txn["audit_included"].copy()
            ra_txn.loc[was_included, "audit_included"]         = False
            ra_txn.loc[was_included, "audit_exclusion_reason"] = "dj_all_cancelled"

    # ── Output ────────────────────────────────────────────────────────────────
    cos_dr = abs(cash_over_short) if cash_over_short < 0 else 0.0
    cos_cr = cash_over_short      if cash_over_short >= 0 else 0.0

    out_dir = common.output_dir_for("register_audit", window.target_date_str, store_number)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_df = pd.DataFrame([
        {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "scan_start_date",      "value": window.start_date_str},
        {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "scan_end_date",        "value": window.end_date_str},
        {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "dj_ra_rows",           "value": int(len(ra_dj)) if not ra_dj.empty else 0},
        {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "dj_ra_cancelled_flag", "value": _ra_dj_cancelled},
        {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "txn_ra_rows",          "value": int(len(ra_txn)) if not ra_txn.empty else 0},
        {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "register_audit_debit", "value": round(register_audit, 2)},
        {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "cash_over_short",      "value": round(cash_over_short, 2)},
        {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "cos_debit",            "value": round(cos_dr, 2)},
        {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "cos_credit",           "value": round(cos_cr, 2)},
    ])

    ra_txn.to_csv(out_dir / "audit_ra_txn_rows.csv", index=False)
    ra_dj_annotated.to_csv(out_dir / "audit_ra_dj_rows.csv", index=False)
    summary_df.to_csv(out_dir / "audit_summary.csv", index=False)

    with pd.ExcelWriter(out_dir / "audit_register_audit.xlsx", engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="summary", index=False)
        ra_txn.to_excel(writer, sheet_name="txn_rows", index=False)
        ra_dj_annotated.to_excel(writer, sheet_name="dj_rows", index=False)

    print(f"Audit written to: {out_dir}")


if __name__ == "__main__":
    run()
