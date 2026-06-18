# Royalty Calculation Reference

This document explains how the royalty audit calculates `Royalty Sales`, `Royalty`,
`Advertising`, and `Media` from raw POS export files.

The scripts are aggregate audits. They do not print customer names, payment identifiers,
employee identifiers, or raw ticket-level records in chat output.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/financial/pos_audit/audit_royalty_fee.py` | Per-store royalty audit for a prompted date range and store number |
| `scripts/financial/pos_audit/audit_royalty_fee_century.py` | Century-wide royalty audit for all stores in `century.yaml` |
| `scripts/financial/pos_audit/audit_scripts/royalty_fee.py` | Shared calculation implementation |
| `scripts/financial/pos_audit/audit_scripts/royalty_fee_century.py` | Century store-list wrapper and progress bar |

## Output Shape

The main export is `royalties_export_audit.csv` and the first workbook tab
`royalties_export`.

Columns:

| Column | Meaning |
|---|---|
| `Store` | POS store number |
| `Royalty Sales` | Total royalty base after surcharge adjustment |
| `Royalty` | `Royalty Sales * Royalty %` |
| `Royalty %` | Default `6.5` |
| `Advertising` | `Royalty Sales * Advertising %` |
| `Advertising %` | Default `1.0` |
| `Media` | `Royalty Sales * Media %` |
| `Media %` | Default `4.0` |
| `Days` | Number of POS dates with calculated data over selected date count |
| `State ID` | State mapping value. Current default map is `OH=2`; other states require a prompt override/map entry. |

## POS Files Used

All files are read from `pos_data/<YYYY-MM-DD>/`.

### `Store.txt`

Used to map prompted or configured store numbers to POS store IDs.

Required columns:

| Column | Use |
|---|---|
| `Store_Number` | User-facing store number and Century YAML store value |
| `Store_ID` | Internal POS store key used by `Sales_Ticket.txt` |
| `State` | Used for optional `State ID` mapping |

### `Payment.txt`

Used to attribute tickets to business dates by `Payment_Date`.

Required columns:

| Column | Use |
|---|---|
| `Ticket_Number` | Join key to `Sales_Ticket.txt` and `Sales_Ticket_Summary.txt` |
| `Payment_Date` | Business date attribution. Tickets count on payment date, not folder date. |

The royalty scripts use payment date only for the royalty calculation. They do not use tender
amounts for the royalty base.

### `Sales_Ticket.txt`

Used to scope tickets to the store and build ticket subsets.

Required columns:

| Column | Use |
|---|---|
| `Store_ID` | Filters tickets to the target store |
| `Ticket_Number` | Join key |
| `Tax_Exempt` | Builds taxable and tax-exempt ticket sets |
| `Ticket_Type_ID` | Identifies third-party tickets and normal ticket types |
| `Status_ID` | Identifies cancelled tickets and gift-card-sold tickets |
| `Refund` | Loaded into context for consistency with other audits, not currently part of royalty formula |

### `Sales_Ticket_Summary.txt`

Used for all sales and surcharge amounts.

Required columns:

| Column | Use |
|---|---|
| `Ticket_Number` | Join key |
| `Category_ID` | Identifies sale, discount, donation, tax, surcharge rows |
| `Taxable_Amount` | Used for Subject to Tax, Tax Exempt, and 3rd Party Tax Exempt components |
| `Non_Taxable_Amount` | Used for non-taxable sales component |
| `Total` | Used for donation subtraction and surcharge sales |

Category IDs used:

| `Category_ID` | Meaning | Royalty use |
|---|---|---|
| `1` | Sale amount | Included in Subject to Tax, Non-Taxable Sales, Tax Exempt, and 3rd Party Tax Exempt components |
| `2` | Discount or adjustment | Subtracted from sale components |
| `7` | Donation | Subtracted from non-taxable sales to avoid double counting |
| `11` | Surcharge | Subtracted from total royalty sales when tied to third-party tickets |

`Category_ID == 11` is confirmed from `Reference.txt` where reference type `47`, ID `11`
is labeled `Surcharge`.

### `Reference.txt`

Used as a schema/reference aid, not as a required calculation input.

Relevant rows:

| Reference type | Reference ID | Label |
|---|---|---|
| `47` | `1` | Sale |
| `47` | `2` | Discount |
| `47` | `4` | Net Sales |
| `47` | `5` | Tax |
| `47` | `7` | Donation |
| `47` | `11` | Surcharge |

## Date Attribution

The royalty scripts do cross-date attribution because tickets can be created in one POS
folder and paid on another business date.

For a selected range:

```text
scan_start = start_date - 10 days
scan_end   = end_date + 30 days
```

The scripts scan `Sales_Ticket.txt`, `Sales_Ticket_Summary.txt`, and `Payment.txt` from
all existing folders in that scan window.

Low-level flow:

1. Read each scan-window `Payment.txt`.
2. Extract distinct `(Ticket_Number, Payment_Date)` pairs.
3. Read matching `Sales_Ticket.txt` and `Sales_Ticket_Summary.txt`.
4. Join ticket and summary rows to payment dates by `Ticket_Number`.
5. Partition the joined data by normalized `Payment_Date` (`YYYY-MM-DD`).
6. For each target date, calculate store results from the payment-date partition.

This means a ticket created on May 31 but paid on June 1 contributes to June 1.

## Ticket Sets

For each store and target date:

```text
store_tix = tickets where Sales_Ticket.Store_ID == target Store_ID

store_paid = store_tix intersect tickets with Payment_Date == target date

non_exempt_tix = tickets where Tax_Exempt == False
exempt_tix     = tickets where Tax_Exempt == True

tt_8_tix   = tickets where Ticket_Type_ID == 8
tt_1_7_tix = tickets where Ticket_Type_ID in (1, 7)

status_8_tix  = tickets where Status_ID == 8
cancelled_tix = tickets where Status_ID == 2
```

Derived sets:

```text
paid_non_exempt = (store_paid - cancelled_tix) intersect non_exempt_tix

paid_no_status8 = store_paid - status_8_tix

paid_exempt_tt8 = store_paid intersect exempt_tix intersect tt_8_tix

paid_exempt_tt17 = store_paid intersect exempt_tix intersect tt_1_7_tix

paid_third_party = store_paid intersect tt_8_tix
```

## Helper Function

The formulas below use:

```text
sts_sum(ticket_set, category_ids, field)
```

Definition:

```text
SUM(Sales_Ticket_Summary[field])
WHERE Ticket_Number IN ticket_set
AND Category_ID IN category_ids
```

## Sales Components

### Subject to Tax

This is the Sales Comparison category name. For royalty purposes, this is the taxable-sales
component of Total Sales.

```text
Subject to Tax =
  sts_sum(paid_non_exempt, [1], Taxable_Amount)
- sts_sum(paid_non_exempt, [2], Taxable_Amount)
```

Cancelled tickets are excluded from this component through `paid_non_exempt`.

### Non-Taxable Sales

```text
Non-Taxable Sales =
  sts_sum(paid_no_status8, [1], Non_Taxable_Amount)
- sts_sum(paid_no_status8, [2], Non_Taxable_Amount)
- sts_sum(paid_no_status8, [7], Total)
```

Gift-card-sold tickets (`Status_ID == 8`) are excluded. Donations are subtracted so they
do not inflate royalty sales.

### Tax Exempt

Normal tax-exempt tickets:

```text
Tax Exempt =
  sts_sum(paid_exempt_tt17, [1], Taxable_Amount)
- sts_sum(paid_exempt_tt17, [2], Taxable_Amount)
```

### 3rd Party Tax Exempt

Third-party tax-exempt tickets:

```text
3rd Party Tax Exempt =
  sts_sum(paid_exempt_tt8, [1], Taxable_Amount)
- sts_sum(paid_exempt_tt8, [2], Taxable_Amount)
```

## Total Sales

```text
Total Sales =
  Subject to Tax
+ Non-Taxable Sales
+ Tax Exempt
+ 3rd Party Tax Exempt
```

This `Total Sales` is the sales base before the surcharge adjustment.

## Surcharge Sales

Surcharge comes from POS ticket summary category `11`, scoped to paid third-party tickets.

```text
Surcharge Sales =
  sts_sum(paid_third_party, [11], Total)
```

Current third-party scope:

```text
paid_third_party = store_paid intersect tickets where Ticket_Type_ID == 8
```

Only third-party-ticket surcharge is subtracted from royalty sales.

The audit also computes this diagnostic:

```text
Non-Third-Party Surcharge Sales =
  sts_sum(store_paid, [11], Total)
- sts_sum(paid_third_party, [11], Total)
```

This should usually be zero. A nonzero value means surcharge rows exist outside
`Ticket_Type_ID == 8` and should be reviewed.

## Royalty Sales

```text
Royalty Sales =
  Total Sales
- Surcharge Sales
```

## Fee Calculations

Default rates:

```text
Royalty %     = 6.5
Advertising % = 1.0
Media %       = 4.0
```

Formulas:

```text
Royalty =
  Royalty Sales * 0.065

Advertising =
  Royalty Sales * 0.010

Media =
  Royalty Sales * 0.040
```

The scripts allow prompt overrides for these percentages.

## Century Store List

The Century-wide script reads stores from:

```text
financial/sales_export_comparison/rules/century.yaml
```

Field used:

```yaml
stores:
  - "2006"
  - "2016"
  ...
```

The script does not infer stores from `pos_data/`; it uses the configured Century list so
the output aligns with the financial pipeline's organization rule.

## Output Files

Per-store script output:

```text
scripts/financial/pos_audit/audits/royalty_fee/<start>_<end>/<store>/
```

Century-wide script output:

```text
scripts/financial/pos_audit/audits/royalty_fee_century/<start>_<end>/
```

Files:

| File | Contents |
|---|---|
| `royalties_export_audit.csv` | Store-level export layout: Royalty Sales, Royalty, Advertising, Media |
| `audit_royalty_fee.xlsx` | Excel workbook with export, summary, by-date, and by-store-day tabs |
| `audit_royalty_fee_by_store_day.csv` | Store/date aggregate components and diagnostics |
| `audit_royalty_fee_by_date.csv` | Date-level aggregate totals |
| `audit_summary.csv` | Period, scan window, rates, skipped counts, and grand totals |
| `audit_royalty_fee_century_skipped_store_days.csv` | Created only when the Century script skips a store/date |

## Worked Formula Shape

For each store over the selected period:

```text
1. Build payment-date store_paid tickets.
2. Calculate:
   Subject to Tax
   Non-Taxable Sales
   Tax Exempt
   3rd Party Tax Exempt
3. Total Sales = sum of those four values.
4. Surcharge Sales = Category_ID 11 Total on paid third-party tickets.
5. Royalty Sales = Total Sales - Surcharge Sales.
6. Royalty = Royalty Sales * 6.5%.
7. Advertising = Royalty Sales * 1.0%.
8. Media = Royalty Sales * 4.0%.
```

## Related Surcharge Audit

The third-party surcharge report is separate:

```powershell
python scripts\financial\pos_audit\audit_third_party_surcharge.py
```

It breaks out third-party providers by payment tender and uses:

```text
Net Sales        = Sales_Ticket_Summary Category_ID 4 Total
Surcharge Sales  = Sales_Ticket_Summary Category_ID 11 Total
Sales Tax        = Sales_Ticket_Summary Category_ID 5 Total
Total Sales      = Net Sales + Surcharge Sales + Sales Tax
```

That report is a supporting audit for surcharge review, not the royalty base formula.
