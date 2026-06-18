from __future__ import annotations

from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import common  # type: ignore
else:
    from . import common

CATEGORY_NAME = "Payin"


def run() -> None:
    root = common.repo_root()
    pos_data_dir = root / "pos_data"
    window, store_number = common.prompt_audit_inputs("Payin Audit", pos_data_dir)
    store_id, txn = common.load_store_transactions(
        pos_data_dir, window.target_date_str, store_number, window.scan_dates
    )

    payin_rows = txn[
        txn["Transaction_Type_Name"].astype(str).str.strip() == "Payins"
    ].copy()
    if not payin_rows.empty:
        payin_rows["audit_status"] = payin_rows["Status"].astype(str).str.strip()
        payin_rows["audit_included"] = payin_rows["audit_status"] == "Inserted"
        payin_rows["audit_exclusion_reason"] = ""
        payin_rows.loc[
            ~payin_rows["audit_included"], "audit_exclusion_reason"
        ] = "status_not_inserted"
        payin_rows["audit_component_used"] = 0.0
        payin_rows.loc[payin_rows["audit_included"], "audit_component_used"] = common.to_num(
            payin_rows.loc[payin_rows["audit_included"], "Amount"]
        )
    else:
        payin_rows["audit_status"] = []
        payin_rows["audit_included"] = []
        payin_rows["audit_exclusion_reason"] = []
        payin_rows["audit_component_used"] = []
    payin_credit = float(payin_rows["audit_component_used"].sum()) if not payin_rows.empty else 0.0

    out_dir = common.output_dir_for("payin", window.target_date_str, store_number)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_df = pd.DataFrame(
        [
            {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "scan_start_date", "value": window.start_date_str},
            {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "scan_end_date", "value": window.end_date_str},
            {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "all_payin_rows", "value": int(len(payin_rows))},
            {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "included_rows", "value": int(payin_rows["audit_included"].sum()) if not payin_rows.empty else 0},
            {"date": window.target_date_str, "store_number": store_number, "store_id": store_id, "metric": "payin_credit", "value": round(payin_credit, 2)},
        ]
    )

    payin_rows.to_csv(out_dir / "audit_payin_rows.csv", index=False)
    summary_df.to_csv(out_dir / "audit_summary.csv", index=False)

    with pd.ExcelWriter(out_dir / "audit_payin.xlsx", engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="summary", index=False)
        payin_rows.to_excel(writer, sheet_name="txn_rows", index=False)

    print(f"Audit written to: {out_dir}")


if __name__ == "__main__":
    run()
