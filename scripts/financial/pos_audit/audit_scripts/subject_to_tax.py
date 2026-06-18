from __future__ import annotations

from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import common  # type: ignore
else:
    from . import common

CATEGORY_NAME = "Subject to Tax"


def run() -> None:
    root = common.repo_root()
    pos_data_dir = root / "pos_data"
    window, store_number = common.prompt_audit_inputs("Subject to Tax Audit", pos_data_dir)
    ctx = common.load_sales_context(pos_data_dir, window.target_date_str, store_number, window.scan_dates)

    paid_non_exempt = (ctx.store_paid - ctx.cancelled_tix) & ctx.non_exempt_tix
    sales_rows = ctx.sts.copy()
    sales_rows["audit_ticket_in_store_paid"] = sales_rows["Ticket_Number"].astype(str).isin(ctx.store_paid)
    sales_rows["audit_ticket_non_exempt"] = sales_rows["Ticket_Number"].astype(str).isin(ctx.non_exempt_tix)
    sales_rows["audit_ticket_not_cancelled"] = ~sales_rows["Ticket_Number"].astype(str).isin(ctx.cancelled_tix)
    sales_rows["audit_category_id_s"] = sales_rows["Category_ID"].astype(str).str.strip()
    sales_rows["audit_category_matches"] = sales_rows["audit_category_id_s"].isin(["1", "2"])
    sales_rows["audit_included"] = (
        sales_rows["audit_ticket_in_store_paid"]
        & sales_rows["audit_ticket_non_exempt"]
        & sales_rows["audit_ticket_not_cancelled"]
        & sales_rows["audit_category_matches"]
    )
    sales_rows["row_role"] = sales_rows["audit_category_id_s"].map(
        {"1": "sale_taxable_amount", "2": "discount_taxable_amount"}
    ).fillna("other")
    sales_rows.loc[~sales_rows["audit_included"], "row_role"] = "excluded"
    sales_rows["audit_exclusion_reason"] = ""
    sales_rows.loc[
        ~sales_rows["audit_ticket_in_store_paid"], "audit_exclusion_reason"
    ] = "ticket_not_paid"
    sales_rows.loc[
        sales_rows["audit_ticket_in_store_paid"] & ~sales_rows["audit_ticket_non_exempt"],
        "audit_exclusion_reason",
    ] = "ticket_tax_exempt"
    sales_rows.loc[
        sales_rows["audit_ticket_in_store_paid"]
        & sales_rows["audit_ticket_non_exempt"]
        & ~sales_rows["audit_ticket_not_cancelled"],
        "audit_exclusion_reason",
    ] = "cancelled_ticket"
    sales_rows.loc[
        sales_rows["audit_ticket_in_store_paid"]
        & sales_rows["audit_ticket_non_exempt"]
        & sales_rows["audit_ticket_not_cancelled"]
        & ~sales_rows["audit_category_matches"],
        "audit_exclusion_reason",
    ] = "category_not_1_or_2"
    sales_rows["audit_component_used"] = 0.0
    sales_rows.loc[
        sales_rows["audit_included"] & sales_rows["audit_category_id_s"].eq("1"),
        "audit_component_used",
    ] = common.to_num(
        sales_rows.loc[
            sales_rows["audit_included"] & sales_rows["audit_category_id_s"].eq("1"),
            "Taxable_Amount",
        ]
    )
    sales_rows.loc[
        sales_rows["audit_included"] & sales_rows["audit_category_id_s"].eq("2"),
        "audit_component_used",
    ] = -common.to_num(
        sales_rows.loc[
            sales_rows["audit_included"] & sales_rows["audit_category_id_s"].eq("2"),
            "Taxable_Amount",
        ]
    )

    sale_amount = common.sts_sum(ctx.sts, paid_non_exempt, [1], "Taxable_Amount")
    discount_amount = common.sts_sum(ctx.sts, paid_non_exempt, [2], "Taxable_Amount")
    net_credit = sale_amount - discount_amount
    audit_rows = sales_rows[sales_rows["audit_included"]].copy().sort_values(
        ["Ticket_Number", "pos_date_found", "sales_ticket_pos_date_found"]
    )

    out_dir = common.output_dir_for("subject_to_tax", window.target_date_str, store_number)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_df = pd.DataFrame(
        [
            {"date": window.target_date_str, "store_number": store_number, "store_id": ctx.store_id, "metric": "scan_start_date", "value": window.start_date_str},
            {"date": window.target_date_str, "store_number": store_number, "store_id": ctx.store_id, "metric": "scan_end_date", "value": window.end_date_str},
            {"date": window.target_date_str, "store_number": store_number, "store_id": ctx.store_id, "metric": "all_sts_rows", "value": int(len(sales_rows))},
            {"date": window.target_date_str, "store_number": store_number, "store_id": ctx.store_id, "metric": "included_rows", "value": int(len(audit_rows))},
            {"date": window.target_date_str, "store_number": store_number, "store_id": ctx.store_id, "metric": "store_paid_tickets", "value": len(ctx.store_paid)},
            {"date": window.target_date_str, "store_number": store_number, "store_id": ctx.store_id, "metric": "paid_non_exempt_tickets", "value": len(paid_non_exempt)},
            {"date": window.target_date_str, "store_number": store_number, "store_id": ctx.store_id, "metric": "sale_taxable_amount", "value": round(sale_amount, 2)},
            {"date": window.target_date_str, "store_number": store_number, "store_id": ctx.store_id, "metric": "discount_taxable_amount", "value": round(discount_amount, 2)},
            {"date": window.target_date_str, "store_number": store_number, "store_id": ctx.store_id, "metric": "subject_to_tax_credit", "value": round(net_credit, 2)},
        ]
    )

    ticket_df = audit_rows[
        ["Ticket_Number", "pos_date_found", "sales_ticket_pos_date_found"]
    ].drop_duplicates().sort_values(["Ticket_Number", "pos_date_found"])
    audit_rows.to_csv(out_dir / "audit_subject_to_tax_rows.csv", index=False)
    ticket_df.to_csv(out_dir / "audit_subject_to_tax_tickets.csv", index=False)
    summary_df.to_csv(out_dir / "audit_summary.csv", index=False)

    with pd.ExcelWriter(out_dir / "audit_subject_to_tax.xlsx", engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="summary", index=False)
        ticket_df.to_excel(writer, sheet_name="ticket_set", index=False)
        audit_rows.to_excel(writer, sheet_name="sts_rows", index=False)

    print(f"Audit written to: {out_dir}")


if __name__ == "__main__":
    run()
