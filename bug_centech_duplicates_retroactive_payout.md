Title

CenTech Duplicates a Retroactive Payout in the Sales Export



Brief Description

CenTech includes the same `$19.98` store payout twice for store `2016` on
June 15, 2026. The POS source contains only one corresponding transaction.

The payout has a June 15 transaction date but was created on June 23. This
retroactive timing may be related to the duplicate CenTech records.



URL

N/A - CenTech Sales Export



Bug Type

Sales data duplication / reporting



User Type

Finance / Accounting



Severity

High



Steps To Reproduce

1. Generate the CenTech Sales Export for June 1-27, 2026.
2. Open the June 15 data.
3. Filter the data to store `2016` and category `Payout`.
4. Compare the aggregate against the local payout audit.



Actual Results

The POS source contains one corresponding payout, while the CenTech export
contains it twice.

Payout totals:

- Client: `$19.32`
- QA: `$39.30`
- CenTech: `$59.28`

CenTech is overstated by `$19.98` compared with the valid POS/QA total.



Attachment

- Payout audit:
  `scripts/financial/pos_audit/audits/payout/2026-06-15/2016/payout_rows.csv`
- CenTech vs Client comparison:
  `financial/sales_export_comparison/runs/2026-06-01_2026-06-27/century/centech_vs_client/output/Sales_CenTech_vs_Client_2026-06-01_2026-06-27.xlsx`



Expected Results

CenTech should include the payout exactly once and report a June 15 payout
total of `$39.30` for store `2016`, matching the valid POS/QA total.



Device & Software Used

Windows / CenTech Sales Export



Resolution [FOR DEVS]



Closure Notes

Pending investigation.
