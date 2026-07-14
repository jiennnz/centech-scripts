Title

CenTech Misses Retroactive Payouts in the Sales Export



Brief Description

CenTech does not include two valid store payout transactions in the July 1-12,
2026 Sales Export.

Both payouts were created on July 12, 2026, but their business transaction
dates are earlier. Flexe and QA both include the payouts on the correct
business dates, while CenTech has no `Payout` row for those store/date/category
combinations.

`Payin` should be reviewed under the same fix because it is sourced from the
same `Store_Transactions.txt` file and may have the same retroactive-entry
behavior.



URL

N/A - CenTech Sales Export



Bug Type

Sales data omission / retroactive store transaction handling



User Type

Finance / Accounting



Severity

High



Steps To Reproduce

1. Open the comparison workbook:
   `https://tidewrk-my.sharepoint.com/:x:/p/pcorrea/IQDv--hzu8gbQ5UkIZVdjPW6ARzA1TXXhrDZYHrEUUSd7HA?e=qzn2QS`
2. Filter the comparison to category `Payout`.
3. Check the following store/date combinations:
   - July 9, 2026, store `6067`
   - July 11, 2026, store `7049`



Actual Results

CenTech has no `Payout` row for these valid payout transactions:

- Store `6067`, transaction `2673`, POS folder `2026-07-12`
  - Transaction date: `2026-07-09`
  - Create date: `2026-07-12 09:54`
  - Flexe / QA payout debit: `$35.00`
  - CenTech payout debit: `$0.00`

- Store `7049`, transaction `6919`, POS folder `2026-07-12`
  - Transaction date: `2026-07-11`
  - Create date: `2026-07-12 17:02`
  - Flexe / QA payout debit: `$100.49`
  - CenTech payout debit: `$0.00`

CenTech did export other categories for those same stores and dates, so this is
not a missing store/day export. The omission is specific to `Payout`.



Attachment

- CenTech vs Flexe comparison:
  `financial/sales_export_comparison/runs/2026-07-01_2026-07-12/century/centech_vs_flexe/output/Sales_CenTech_vs_Flexe_2026-07-01_2026-07-12.xlsx`
- QA vs Flexe comparison:
  `financial/sales_export_comparison/runs/2026-07-01_2026-07-12/century/qa_vs_flexe/output/Sales_QA_vs_Flexe_2026-07-01_2026-07-12.xlsx`
- QA computed output:
  `financial/sales_export_comparison/runs/2026-07-01_2026-07-12/century/qa_vs_flexe/output/pos_computed.csv`



Expected Results

CenTech should include retroactive store payouts based on their business
`Transaction_Date`, even when the payout row is created in a later POS folder.

Expected payout rows:

- July 9, 2026, store `6067`, `Payout` debit `$35.00`
- July 11, 2026, store `7049`, `Payout` debit `$100.49`

The same cross-date logic should be applied to `Payin` rows because Payin is
also sourced from `Store_Transactions.txt`.



Device & Software Used

Windows / CenTech Sales Export



Resolution [FOR DEVS]



Closure Notes

Pending investigation.
