Title

Exclude Standalone Processing_Status_ID 8 Rows from ISCC and ISCCT



Brief Description

CenTech and QA currently include standalone payment rows with
`Processing_Status_ID = 8` in `In-Store Credit Card` and, when applicable,
`In-Store Credit Card Tips`.

Flexe excludes these provisional rows. This creates repeatable CenTech vs Flexe
and QA vs Flexe discrepancies even though all systems are using the same
business date.

Update the CenTech and QA sales calculations to exclude standalone
`Processing_Status_ID = 8` payment rows from ISCC and ISCCT.



Business Value

- Align CenTech and QA sales exports with Flexe.
- Remove false ISCC and ISCCT discrepancies from financial comparisons.
- Keep provisional payment records from affecting finalized sales totals.



Scope

- `In-Store Credit Card`
- `In-Store Credit Card Tips`
- CenTech and QA sales export calculations
- Payment rows where `Processing_Status_ID = 8` and no corresponding finalized
  payment row exists

This change applies to payment processing status only. It must not change the
existing handling of ticket `Status_ID = 8`, which represents gift-card-sold
tickets.



Current Behavior

Standalone `Processing_Status_ID = 8` rows are treated as qualifying in-store
card payments. During July 2-4, 2026, this caused CenTech and QA to report
higher ISCC/ISCCT totals than Flexe.

Confirmed examples include:

- July 2: store `7049`
- July 3: stores `4004`, `6021`, `6076`, `7049`, and `13062`
- July 4: stores `6072`, `37016`, and `49002`

The supporting rows are in the correct business-date folders. These are not
cross-date discrepancies.



Expected Behavior

Standalone payment rows with `Processing_Status_ID = 8` do not contribute to
ISCC or ISCCT totals in either CenTech or QA.

Finalized qualifying payment rows continue to be included under the existing
ISCC/ISCCT rules.



Acceptance Criteria

1. A standalone type-14 payment row with `Processing_Status_ID = 8` contributes
   `$0.00` to `In-Store Credit Card`.
2. Its tip contributes `$0.00` to `In-Store Credit Card Tips`.
3. Existing handling for finalized payment rows remains unchanged.
4. Existing online/token refund classification remains unchanged.
5. Ticket `Status_ID = 8` gift-card-sold logic remains unchanged.
6. CenTech and QA match Flexe for the identified July 2-4 ISCC/ISCCT cases
   after regeneration.
7. Automated tests cover status-8 rows with and without tips and verify that
   the similarly named ticket `Status_ID = 8` behavior is unaffected.



Attachment

- Audit workbook:
  `scripts/financial/pos_audit/audits/sales_comparison/2026-07-01_to_2026-07-04/sales_comparison_row_level_audit.xlsx`
- Calculation documentation:
  `financial/sales_export_comparison/CATEGORY_CALCULATIONS.md`



Resolution [FOR DEVS]



Closure Notes

Pending implementation.
