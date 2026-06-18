from __future__ import annotations

from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import common  # type: ignore
else:
    from . import common

CATEGORY_NAME = "Payout"


def run() -> None:
    root = common.repo_root()
    pos_data_dir = root / "pos_data"
    window, store_number = common.prompt_audit_inputs("Payout Audit", pos_data_dir)
    store_id, txn = common.load_store_transactions(
        pos_data_dir, window.target_date_str, store_number, window.scan_dates
    )

    payout_all_rows = txn[
        txn["Transaction_Type_Name"].astype(str).str.strip() == "Store Payout"
    ].copy()

    voided_ids = set(
        payout_all_rows[
            payout_all_rows["Status"].astype(str).str.strip() == "Void"
        ]["Transaction_ID"].astype(str)
    ) if not payout_all_rows.empty else set()

    payout_rows = payout_all_rows.copy()
    if not payout_rows.empty:
        payout_rows["audit_status"] = payout_rows["Status"].astype(str).str.strip()
        payout_rows["audit_transaction_id"] = payout_rows["Transaction_ID"].astype(str)
        payout_rows["audit_is_void_transaction_id"] = payout_rows[
            "audit_transaction_id"
        ].isin(voided_ids)
        payout_rows["audit_included"] = (
            payout_rows["audit_status"].eq("Inserted")
            & ~payout_rows["audit_is_void_transaction_id"]
        )
        payout_rows["audit_exclusion_reason"] = ""
        payout_rows.loc[
            payout_rows["audit_status"] != "Inserted", "audit_exclusion_reason"
        ] = "status_not_inserted"
        payout_rows.loc[
            payout_rows["audit_is_void_transaction_id"], "audit_exclusion_reason"
        ] = "void_transaction_id"
        payout_rows["audit_abs_amount"] = 0.0
        payout_rows.loc[payout_rows["audit_included"], "audit_abs_amount"] = (
            common.to_num(payout_rows.loc[payout_rows["audit_included"], "Amount"]).abs()
        )
    else:
        payout_rows["audit_status"] = []
        payout_rows["audit_transaction_id"] = []
        payout_rows["audit_is_void_transaction_id"] = []
        payout_rows["audit_included"] = []
        payout_rows["audit_exclusion_reason"] = []
        payout_rows["audit_abs_amount"] = []

    payout_debit = float(payout_rows["audit_abs_amount"].sum()) if not payout_rows.empty else 0.0

    out_dir = common.output_dir_for("payout", window.target_date_str, store_number)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_df = pd.DataFrame(
        [
            {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "scan_start_date", "value": window.start_date_str},
            {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "scan_end_date", "value": window.end_date_str},
            {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "voided_transaction_ids", "value": len(voided_ids)},
            {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "all_store_payout_rows", "value": int(len(payout_rows))},
            {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "included_rows", "value": int(payout_rows["audit_included"].sum()) if not payout_rows.empty else 0},
            {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "payout_debit", "value": round(payout_debit, 2)},
        ]
    )

    payout_rows.to_csv(out_dir / "audit_payout_rows.csv", index=False)
    summary_df.to_csv(out_dir / "audit_summary.csv", index=False)

    with pd.ExcelWriter(out_dir / "audit_payout.xlsx", engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="summary", index=False)
        payout_rows.to_excel(writer, sheet_name="txn_rows", index=False)

    print(f"Audit written to: {out_dir}")


if __name__ == "__main__":
    run()
