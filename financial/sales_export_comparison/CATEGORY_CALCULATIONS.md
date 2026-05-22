# Financial Category Calculation Reference

Source files per date: `Sales_Ticket.txt`, `Sales_Ticket_Summary.txt`, `Payment.txt`,
`Store_Transactions.txt`, `DailyJournal.txt`, `Store.txt`

All amounts are store-scoped: only tickets belonging to the store's `Store_ID` are used.

---

## Common Ticket Sets

| Variable | Definition |
|---|---|
| `store_tix` | All ticket numbers where `Store_ID` matches |
| `store_paid` | `store_tix` intersected with tickets whose `Payment_Date` matches the current date, including tickets created in another scanned POS folder |
| `non_exempt_tix` | Tickets where `Tax_Exempt == False` |
| `exempt_tix` | Tickets where `Tax_Exempt == True` |
| `tt_8_tix` | Tickets where `Ticket_Type_ID == 8` (3rd party) |
| `tt_1_7_tix` | Tickets where `Ticket_Type_ID IN (1, 7)` |
| `tt_5_tix` | Tickets where `Ticket_Type_ID == 5` |
| `status_8_tix` | Tickets where `Status_ID == 8` (gift card sold) |
| `refund_tix` | Tickets where `Refund == True` in Sales_Ticket |
| `online_refund_tix` | `refund_tix` filtered to tickets that have at least one payment row with `len(Transaction_ID) == 32` — used to exclude online refunds from ISCC/ISCCT only |

`sts_sum(tickets, category_ids, field)` = sum of `field` in `Sales_Ticket_Summary` filtered by ticket set and `Category_ID`.

**Payment_Date attribution**: `store_paid` includes tickets whose `Payment_Date == current date` across the scanned POS folders. Tickets can be created in one folder and paid on another business date; they are counted on the payment date, not the folder date.

**Cross-date scan window**: `Payment.txt`, `Store_Transactions.txt`, `Sales_Ticket.txt`, and `Sales_Ticket_Summary.txt` are scanned across all date folders within the configured range **plus 14 extra days** beyond end_date. This captures payments, transactions, and ticket detail rows recorded in later folders but attributed (via `Payment_Date` / `Transaction_Date`) to dates within the range.

Example: a ticket created in the Apr 22 POS folder but paid just after midnight on Apr 23 is posted to Apr 23 with its original ticket attributes and sales/tax summary rows.

---

## Sales Categories

### Subject to Tax
```
paid_non_exempt = store_paid ∩ non_exempt_tix
credit = sts_sum(paid_non_exempt, [1], Taxable_Amount)
       - sts_sum(paid_non_exempt, [2], Taxable_Amount)
```

### Non-Taxable Sales
```
paid_no_status8 = store_paid - status_8_tix
credit = sts_sum(paid_no_status8, [1], Non_Taxable_Amount)
       - sts_sum(paid_no_status8, [2], Non_Taxable_Amount)
       - sts_sum(paid_no_status8, [7], Total)
```

### 3rd Party Tax Exempt
```
paid_exempt_tt8 = store_paid ∩ exempt_tix ∩ tt_8_tix
credit = sts_sum(paid_exempt_tt8, [1], Taxable_Amount)
       - sts_sum(paid_exempt_tt8, [2], Taxable_Amount)
```

### Tax Exempt
```
paid_exempt_tt17 = store_paid ∩ exempt_tix ∩ tt_1_7_tix
credit = sts_sum(paid_exempt_tt17, [1], Taxable_Amount)
       - sts_sum(paid_exempt_tt17, [2], Taxable_Amount)
```

### Sales Tax
```
credit = sts_sum(store_paid ∩ non_exempt_tix, [5], Total)
```

### Donation
```
credit = sts_sum(store_paid, [7], Total)
```

---

## Credit Card Categories

### In-Store Credit Card (ISCC)
```
Qualifying rows: Payment_Type_ID == 14
  AND Processing_Status_ID == 4
  AND Ticket_Number NOT IN status_8_tix       (gift card sold — counted in Gift Card Sold)
  AND Ticket_Number NOT IN online_refund_tix  (online refunds — both rows belong in Online CC)
  AND (
       len(Transaction_ID) == 6  AND Tip_Paid == True
    OR len(Transaction_ID) == 32 AND Tip_Paid == False
    OR len(Transaction_ID) == 4
  )

debit = SUM(Tendered_Amount - Change + Tip_Amount) for qualifying rows
      + gc_sold_cc  (CC-paid portion of Gift Card Sold only — see below)
```
Note: ISCC uses cross-date payments attributed by `Payment_Date`, not folder date.

**status_8 exclusion**: CC payments for gift-card-sold tickets are excluded from the qualifying rows above, then re-added as `gc_sold_cc` (only the CC-paid portion). Cash-paid gift card purchases must not inflate the CC total.

**online_refund_tix exclusion**: Refunds of online payments (tlen=32) have one Tip_Paid=False row (refund) and one Tip_Paid=True row (original). The False row would misclassify into ISCC. Client counts both rows in Online CC. In-store refunds (tlen=4/6) are NOT excluded — they remain in ISCC as negative rows and net correctly.

### In-Store Credit Card Tips (ISCCT)
```
Qualifying rows: Payment_Type_ID == 14
  AND Processing_Status_ID == 4
  AND Tip_Amount != 0  (includes negative tip refunds)
  AND Ticket_Number NOT IN status_8_tix
  AND Ticket_Number NOT IN online_refund_tix
  AND (
       len(Transaction_ID) IN (4, 6)
    OR len(Transaction_ID) == 32 AND Tip_Paid == False
  )

credit = SUM(Tip_Amount) for qualifying rows
```
Note: mirrors ISCC shape exactly. tlen=32/Tip_Paid=False catches chip/token cards that
settle with a tip on a later date under a new Transaction_ID. tlen=32/Tip_Paid=True is
excluded — those are Online CC tips. `Tip_Amount != 0` (not `> 0`) ensures refund rows
with negative tips are included so the net matches the actual amount owed.

### Discarded CC
```
Qualifying rows: Payment_Type_ID == 14
  AND Processing_Status_ID == 9
  AND (
       len(Transaction_ID) == 6  AND Tip_Paid == True
    OR len(Transaction_ID) == 32 AND Tip_Paid == False
    OR len(Transaction_ID) == 4
  )

debit = SUM(Tendered_Amount - Change + Tip_Amount) for qualifying rows
```
Note: Same shape as ISCC but status 9 (discarded/voided). Gift Card Sold not included.

### Online Credit Card (Online CC)
```
Qualifying rows: Payment_Type_ID == 14
  AND len(Transaction_ID) == 32
  AND (
       Tip_Paid == True
    OR Ticket_Number IN online_refund_tix
  )

debit = SUM(Tendered_Amount + Tip_Amount) for qualifying rows
```
Note: Online refund tickets (`online_refund_tix`) are **included**, even when the refund
row has `Tip_Paid == False`. A refund ticket carries negative Tendered_Amount rows that
net against the original charge, matching client OLO deposit behaviour. The
`online_refund_tix` exclusion applies to ISCC/ISCCT only (to prevent the Tip_Paid=False
refund row from misclassifying into in-store CC).

### Online Credit Card Tips
```
Qualifying rows:
  Payment_Type_ID IN (14, 3)
  AND len(Transaction_ID) == 32
  AND Tip_Paid == True

credit = SUM(Tip_Amount) for qualifying rows
```

### Transaction ID Length Key

| Length | Tip_Paid | Meaning |
|---|---|---|
| 4 | any | Short ID — in-store swipe |
| 6 | True | Swiped, tip settled |
| 32 | False | Token/chip, tip pending |
| 32 | True | Online/token card — excluded from ISCC |

---

## Gift Card Categories

### Gift Card
```
Qualifying rows: Payment_Type_ID == 5 AND len(Transaction_ID) == 6

debit = SUM(Tendered_Amount)
```

### Gift Card Sold
```
gc_sold_pay = SUM(Tendered_Amount - Change) WHERE Ticket_Number IN status_8_tix
              (all payment types — gift cards can be purchased with any tender)

gc_sold_sts = SUM(Non_Taxable_Amount) in Sales_Ticket_Summary
              WHERE Ticket_Number IN status_8_tix
              AND Category_ID == 1
              AND Taxable_Amount == 0
              AND Non_Taxable_Amount > 0
              (only when status_8_tix set is empty — fallback path)

credit = gc_sold_pay + gc_sold_sts

gc_sold_cc = SUM(Tendered_Amount - Change) WHERE Ticket_Number IN status_8_tix
             AND Payment_Type_ID == 14  (CC-paid portion only)
```
Note: The `credit` line uses all payment types (the full Gift Card Sold category value).
`gc_sold_cc` is the separate CC-only figure added into the ISCC debit total — cash-paid
gift card purchases must not inflate the in-store credit card total.

### Online Gift Card
```
Qualifying rows: Payment_Type_ID == 5 AND len(Transaction_ID) == 32

debit = SUM(Tendered_Amount + Tip_Amount)
```

### Online Gift Card Tips
```
Qualifying rows: Payment_Type_ID == 5 AND Payment_Name_ID == 8
                 AND Ticket_Number IN (store_paid ∩ tt_5_tix)

credit = SUM(Tip_Amount)
```

---

## Store Transaction Categories

### Register Audit
```
Source: Store_Transactions.txt WHERE Transaction_Type_Name == "Register Audit"
debit = last row's Amount for the store+date
```

**Cancellation rule**: If the DailyJournal Register Audit row's `Amount` field equals the
Over/Short value parsed from its `Comments` field, both Register Audit and Cash Over/Short
Adjustment are zeroed out (they cancel each other).

### Payout
```
Source: Store_Transactions.txt (cross-date — all folders scanned by Transaction_Date)
  WHERE Transaction_Type_Name == "Store Payout"
  AND Status == "Inserted"
  AND Transaction_ID NOT IN voided_payout_ids

voided_payout_ids = Transaction_IDs WHERE Transaction_Type_Name == "Store Payout"
                    AND Status == "Void"  (scoped to same store_txn date slice)

debit = SUM(ABS(Amount))
```
Note: Cross-date scan used because payout rows are sometimes recorded in a later folder's
Store_Transactions.txt but carry a Transaction_Date matching the business day. `ABS` applied
because some systems store payout amounts as negative.

**Void exclusion**: when a payout is entered retroactively then voided, both the `Inserted`
and `Void` rows share the same `Transaction_Date` and land in the same date slice. Excluding
Transaction_IDs that have a matching `Void` row prevents the original entry from counting
before the void is applied. The void and re-entry are each attributed to their own dates.

### Payin
```
Source: Store_Transactions.txt
  WHERE Transaction_Type_Name == "Payins" AND Status == "Inserted"
credit = SUM(Amount)
```

### Cash Over/Short Adjustment
```
Source: DailyJournal.txt WHERE Action == "Register Audit"
        parsed from Comments field: "Over/Short: <value>"

If DailyJournal row Amount == Over/Short value → both Register Audit and COS zeroed (cancelled).
Otherwise:
  If value < 0:  debit  = abs(value),  credit = 0
  If value >= 0: debit  = 0,           credit = value
```

---

## 3rd Party Deliveries

All use `Payment_Type_ID == 13`. Differentiated by `Name` field:

| Category | Name value |
|---|---|
| 3rd Party - UberEats | 4001 |
| 3rd Party - DoorDash | 4004 |
| 3rd Party - GrubHub | 4003 |
| 3rd Party - EZ Cater | 74 or 4022 |

```
debit = SUM(Tendered_Amount) for matching rows
```
Note: EZ Cater appears as `Name = "4022"` in most stores and `Name = "74"` in others;
both are matched.

---

## House Account
```
Qualifying rows: Payment_Type_ID == 7

debit = SUM(Tendered_Amount)
```

---

## Debit vs Credit Summary

| Category | Debit | Credit |
|---|---|---|
| Subject to Tax | — | computed |
| Non-Taxable Sales | — | computed |
| 3rd Party Tax Exempt | — | computed |
| Tax Exempt | — | computed |
| Register Audit | computed | — |
| Sales Tax | — | computed |
| In-Store Credit Card | computed | — |
| Payout | computed | — |
| Online Credit card | computed | — |
| Online Gift Card | computed | — |
| Online Credit Card Tips | — | computed |
| In-Store Credit Card Tips | — | computed |
| Online Gift Card Tips | — | computed |
| Gift Card | computed | — |
| Gift Card Sold | — | computed |
| 3rd Party - UberEats | computed | — |
| 3rd Party - DoorDash | computed | — |
| 3rd Party - GrubHub | computed | — |
| 3rd Party - EZ Cater | computed | — |
| House Account | computed | — |
| Donation | — | computed |
| Payin | — | computed |
| Cash Over/Short Adjustment | if negative | if positive |
| Discarded CC | computed | — |
