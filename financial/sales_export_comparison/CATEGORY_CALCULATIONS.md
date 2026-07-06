# Financial Category Calculation Reference

Source files per date: `Sales_Ticket.txt`, `Sales_Ticket_Summary.txt`, `Payment.txt`,
`Store_Transactions.txt`, `DailyJournal.txt`, `Store.txt`

All amounts are store-scoped: only tickets belonging to the store's `Store_ID` are used.

This document describes the verifier's operational rules: how it reads exported POS text
files, how it builds reusable ticket subsets, and how it turns those inputs into category
debit/credit values.

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
| `cancelled_tix` | Tickets where `Status_ID == 2` in `Sales_Ticket.txt` (canceled) |
| `refund_tix` | Tickets where `Refund == True` in Sales_Ticket |
| `online_refund_tix` | `refund_tix` filtered to tickets that have at least one payment row with `len(Transaction_ID) == 32` — used to exclude online refunds from ISCC/ISCCT only |

`sts_sum(tickets, category_ids, field)` = sum of `field` in `Sales_Ticket_Summary` filtered by ticket set and `Category_ID`.

**Payment_Date attribution**: `store_paid` includes tickets whose `Payment_Date == current date` across the scanned POS folders. Tickets can be created in one folder and paid on another business date; they are counted on the payment date, not the folder date.

**Duplicate refund copy handling**: If a ticket is found in an earlier POS folder with
`Payment_Date == current date`, but the same `Ticket_Number` also exists in the current
business-date POS folder with `Refund == True`, the earlier folder's sales summary copy is
excluded from sales/tax calculations. The current-date refund copy remains eligible under
the normal category rules. This prevents double-counting a stale source-folder copy while
preserving legitimate cross-midnight paid tickets.

**Cross-date scan window**: `Payment.txt`, `Store_Transactions.txt`, `Sales_Ticket.txt`, and `Sales_Ticket_Summary.txt` are scanned across **3 days before start_date**, the full configured range, and **30 extra days beyond end_date**. The lookback captures tickets created just before the range (e.g. late-night on the day before start) whose payment settles on start_date. The lookahead captures payments/transactions recorded in later folders but attributed (via `Payment_Date` / `Transaction_Date`) to dates within the range.

Example: a ticket created Mar 31 night but paid Apr 1 is attributed to Apr 1, even when the run starts Apr 1 — because Mar 31's folder is in the 3-day lookback window.

---

## Sales Categories

### Subject to Tax
```
paid_non_exempt = (store_paid - cancelled_tix) ∩ non_exempt_tix
credit = sts_sum(paid_non_exempt, [1], Taxable_Amount)
       - sts_sum(paid_non_exempt, [2], Taxable_Amount)
```

### Non-Taxable Sales
```
paid_no_status8 = store_paid - status_8_tix
non_tax = sts_sum(paid_no_status8, [1], Non_Taxable_Amount)
        - sts_sum(paid_no_status8, [2], Non_Taxable_Amount)
        - sts_sum(paid_no_status8, [7], Total)

If non_tax >= 0: credit = non_tax, debit = 0
If non_tax <  0: debit  = abs(non_tax), credit = 0
```
Note: A day with net refunds can produce a negative value. Client export places the absolute
value in Debit in that case rather than a negative Credit.

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
credit = sts_sum((store_paid - cancelled_tix) ∩ non_exempt_tix, [5], Total)
```

### Donation
```
credit = sts_sum(store_paid, [7], Total)
```

---

## Credit Card Categories

### Business classification rule

For card rows, `len(Transaction_ID) == 32` is not enough to call a payment "online".
The business split is:

- `tlen=32` and `Tip_Paid=False` can still be an in-store register card payment. This is
  the chip/tokenized in-store shape used by the POS, and the POS chip flow does not flip
  `Tip_Paid` to `True`.
- `tlen=32`, `Tip_Paid=True`, and `Ticket_Type_ID=5` is treated as online card activity.
- `tlen=32` rows on in-store ticket types (`Ticket_Type_ID IN (1,2,3,4,6,7)`) stay in
  in-store card activity even when `Tip_Paid=True`.
- Refunds are handled by ticket-level override, not by row shape alone. If a refund ticket
  has `Ticket_Type_ID=5` and at least one `tlen=32` payment row, the ticket enters
  `online_refund_tix` and both the negative refund row and the matching original online row
  stay in `Online Credit Card`.

Business intent: keep one economic event in one bucket. A raw refund row with
`tlen=32`/`Tip_Paid=False` superficially resembles in-store chip activity, but if that row
belongs to an online refund it must net against the original online charge in `Online CC`,
not leak into `ISCC`.

### In-Store Credit Card (ISCC)
```
Qualifying rows: Payment_Type_ID == 14
  AND Processing_Status_ID is eligible:
        status 4 (Processed)  — always eligible
        status 2 (Open)       — eligible only if this ticket has exactly one
                                type-14 row across the full cross-date scan window
                                (3-day lookback + range + 30-day lookahead).
                                Multiple rows mean the payment was reprocessed to
                                status 4 in a later export, or is a genuine
                                duplicate; the status-4 row handles it.
  AND Ticket_Number NOT IN status_8_tix       (gift card sold — counted in Gift Card Sold)
  AND Ticket_Number NOT IN online_refund_tix  (online refunds — both rows belong in Online CC)
  AND Ticket_Number NOT IN cancelled_tix      (Status_ID=2 in Sales_Ticket.txt)
  AND (
       len(Transaction_ID) == 6  AND Tip_Paid == True
    OR len(Transaction_ID) == 32 AND Ticket_Type_ID IN (1,2,3,4,6,7)
    OR len(Transaction_ID) == 4
  )

debit = SUM(Tendered_Amount - Change + Tip_Amount) for qualifying rows
      + gc_sold_cc  (CC-paid portion of Gift Card Sold only — see below)
```
Note: ISCC uses cross-date payments attributed by `Payment_Date`, not folder date.

**row-level summing**: ISCC is a payment-row calculation. Do not dedupe by `Ticket_Number` or assume one card payment row per ticket. Split tenders, adjustments, and correction/refund rows can create multiple qualifying rows for the same ticket; include all qualifying rows and let positive and negative rows net.

**status_8 exclusion**: CC payments for gift-card-sold tickets are excluded from the qualifying rows above, then re-added as `gc_sold_cc` (only the CC-paid portion). Cash-paid gift card purchases must not inflate the CC total.

**online_refund_tix exclusion**: Refunds of online payments (tlen=32) have one Tip_Paid=False row (refund) and one Tip_Paid=True row (original). The False row would misclassify into ISCC. Client counts both rows in Online CC. In-store refunds (tlen=4/6) are NOT excluded — they remain in ISCC as negative rows and net correctly.

**why ticket type matters for `tlen=32`**: The 32-character ID is a token shape shared by
online and chip/tokenized in-store payments. The verifier treats `Ticket_Type_ID=5` as the
online card shape, while `Ticket_Type_ID IN (1,2,3,4,6,7)` stays in in-store card activity
even when `Tip_Paid=True`. Online refund tickets are the exception that forces both refund
and original token rows into Online CC.

#### Edge case quick reference

| tlen | Tip_Paid | Processing_Status_ID | Ticket in | Result |
|---|---|---|---|---|
| 4 | any | 4 | — | Qualifies (short-ID swipe) |
| any | any | 8 | — | Excluded — provisional payment status |
| 6 | True | 4 | — | Qualifies (swiped, tip settled) |
| 32 | any | 4 | in-store ticket type | Qualifies — chip/token in-store; ticket type controls the split |
| 32 | True | 4 | Ticket_Type_ID=5 | Not ISCC → Online CC |
| any | any | 9 | — | Not ISCC → Discarded CC |
| 6 | True | 4 | `status_8_tix` | Excluded from qualifying rows; CC amount re-added via `gc_sold_cc` |
| 32 | False | 4 | `online_refund_tix` | Excluded — both refund rows go to Online CC |
| 6 | True | 4 | `refund_tix` (in-store only) | Qualifies — negative Tendered_Amount nets correctly |
| any | any | 2 (sole) | — | Qualifies — Open payment never reprocessed; treated same as status 4 |
| any | any | 2 (not sole) | — | Excluded — ticket has other type-14 rows; status-4 sibling handles inclusion |

**Example A — chip/token card (tlen=32, Tip_Paid=False):**
```
Ticket #1001 (chip card at register):
  Row A (charge):  tlen=32, Tip_Paid=False, Tendered=25.00, Change=0, Tip=0.00
    → ISCC: +25.00
  Row B (tip, settled next day under new Transaction_ID):
           tlen=32, Tip_Paid=False, Tendered=0.00,  Change=0, Tip=3.00
    → ISCC: +3.00  |  ISCCT: +3.00
  Total ISCC for ticket: 28.00
```
The POS chip flow never sets `Tip_Paid=True` — both the original charge and the later tip-settlement row arrive as tlen=32/False.

**Example B — online refund excluded; in-store refund kept:**
```
Ticket #2001 (Refund=True, has tlen=32 row → in online_refund_tix):
  Row A: tlen=32, Tip_Paid=False, Tendered=-20.00
    → shape matches ISCC (tlen=32/False) but ticket excluded → Online CC
  Row B: tlen=32, Tip_Paid=True,  Tendered=+20.00
    → Online CC (Tip_Paid=True)
  ISCC contribution: 0.00  |  Online CC: nets to 0.00

Ticket #2002 (Refund=True, only tlen=6 rows → NOT in online_refund_tix):
  Row A: tlen=6, Tip_Paid=True, Tendered=-20.00, Change=0, Tip=-2.00
    → ISCC: -22.00  (negative — nets against other ISCC rows for the day)
```

**Example C — multi-row ticket (split tender + adjustment):**
```
Ticket #1005:
  Row A: tlen=4, Tip_Paid=False, Tendered=10.00, Change=0, Tip=0.00 → +10.00
  Row B: tlen=6, Tip_Paid=True,  Tendered=20.00, Change=0, Tip=4.00 → +24.00
  ISCC for ticket #1005: 34.00
```

**Example D — CC-paid gift card (status_8 exclusion + gc_sold_cc re-add):**
```
Ticket #3001 (Status_ID=8, gift card purchased by CC):
  Row: Payment_Type_ID=14, tlen=6, Tip_Paid=True, Tendered=50.00, Change=0
    → EXCLUDED from qualifying rows (ticket in status_8_tix)
    → gc_sold_cc = 50.00 → added to ISCC debit after the qualifying-row sum
  Gift Card Sold credit = 50.00 (all tender types)

Same-day cash gift card purchase:
  → Payment_Type_ID != 14 → gc_sold_cc += 0 — cash does not inflate ISCC
```

### In-Store Credit Card Tips (ISCCT)
```
Qualifying rows: Payment_Type_ID == 14
  AND Processing_Status_ID is eligible (same rule as ISCC: status 4 always,
        status 2 only if sole type-14 row across the full cross-date scan window)
  AND Tip_Amount != 0  (includes negative tip refunds)
  AND Ticket_Number NOT IN status_8_tix
  AND Ticket_Number NOT IN online_refund_tix
  AND (
       len(Transaction_ID) IN (4, 6)
    OR len(Transaction_ID) == 32 AND Ticket_Type_ID IN (1,2,3,4,6,7)
  )

credit = SUM(Tip_Amount) for qualifying rows
```
Note: mirrors ISCC shape exactly. For `len(Transaction_ID) == 32`, ticket type controls the
split: in-store ticket types stay in ISCCT and `Ticket_Type_ID=5` goes to Online CC tips.
`Tip_Amount != 0` (not `> 0`) ensures refund rows with negative tips are included so the
net matches the actual amount owed.

**Late-arriving tlen=4 rows**: A tlen=4 payment row (manual/keyed entry) can appear in a
POS folder several days after its `Payment_Date` — e.g. a row with `Payment_Date = Apr 2`
first appearing in the Apr 6 folder. This pipeline attributes it to `Payment_Date` (Apr 2)
per standard cross-date logic. Accounting exports sourced from real-time settlement data may
not include these retroactively entered rows at all, producing a small ISCCT gap on the
original date that does not offset on the later date.

### Discarded CC
```
Qualifying rows: Payment_Type_ID == 14
  AND Processing_Status_ID == 9
  AND Ticket_Number NOT IN status_8_tix
  AND Ticket_Number NOT IN online_refund_tix
  AND (
       len(Transaction_ID) == 6  AND Tip_Paid == True
    OR len(Transaction_ID) == 32 AND Ticket_Type_ID IN (1,2,3,4,6,7)
    OR len(Transaction_ID) == 4
  )

debit = SUM(Tendered_Amount - Change + Tip_Amount) for qualifying rows
```
Note: Same ticket exclusions and transaction-ID shape as ISCC, but `Processing_Status_ID == 9`
(discarded/voided). Gift Card Sold tickets and online refund tickets are excluded from
Discarded CC for the same reason they are excluded from ISCC.

### Online Credit Card (Online CC)
```
Qualifying rows: Payment_Type_ID == 14
  AND len(Transaction_ID) == 32
  AND Ticket_Type_ID == 5
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

**business reason for refund override**: refund rows are not classified independently if
that would split a single online charge/refund pair across two categories. The override
forces both sides of the reversal to remain in `Online CC`, which matches how the client
deposit/export nets online activity.

### Online Credit Card Tips
```
Qualifying rows:
  Payment_Type_ID IN (14, 3)
  AND len(Transaction_ID) == 32
  AND Ticket_Type_ID == 5
  AND Tip_Paid == True

credit = SUM(Tip_Amount) for qualifying rows
```

### Transaction ID Length Key

| Length | Tip_Paid | Meaning |
|---|---|---|
| 4 | any | Short ID — in-store swipe |
| 6 | True | Swiped, tip settled |
| 32 | False | Token/chip or online token; ticket type and refund rules decide category |
| 32 | True | Online/token or in-store token; Ticket_Type_ID=5 goes online, in-store ticket types stay ISCC |

---

## Gift Card Categories

### Gift Card
```
Qualifying rows: Payment_Type_ID == 5 AND len(Transaction_ID) == 6

debit = SUM(Tendered_Amount)
```

### Gift Card Sold
```
gc_sold_pay = SUM(Tendered_Amount - Change) WHERE Ticket_Number IN (store_paid ∩ status_8_tix)
              (all payment types — gift cards can be purchased with any tender)

gc_sold_sts = SUM(Non_Taxable_Amount) in Sales_Ticket_Summary
              WHERE Ticket_Number IN (store_paid ∩ status_8_tix)
              AND Category_ID == 1
              AND Taxable_Amount == 0
              AND Non_Taxable_Amount > 0
              (only when store_paid ∩ status_8_tix is empty — fallback path)

credit = gc_sold_pay + gc_sold_sts

gc_sold_cc = SUM(Tendered_Amount - Change) WHERE Ticket_Number IN (store_paid ∩ status_8_tix)
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
debit = last non-void row's Amount for the store+date
```

`DailyJournal.txt` is not used to select Register Audit. When present, it is used
only for Cash Over/Short Adjustment.

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
Source: Store_Transactions.txt (cross-date — all folders scanned by Transaction_Date)
  WHERE Transaction_Type_Name == "Payins"

inserted_payins = rows where Status == "Inserted"
matching_void_payins = rows where Status == "Void"
                      AND Transaction_ID is in inserted_payins.Transaction_ID

credit = SUM(inserted_payins.Amount) - SUM(matching_void_payins.Amount)
```
Note: Payin uses the same cross-date Store_Transactions slice as Payout. A `Void` Payin
row only reduces Payin when it shares a `Transaction_ID` with an inserted Payin in the same
store/date transaction slice. Void rows with different transaction IDs are separate
transactions and are ignored.


### Cash Over/Short Adjustment
```
Optional source: DailyJournal.txt WHERE Action == "Register Audit"
        parsed from Comments field: "Over/Short: <value>"

The verifier walks DailyJournal Register Audit rows from latest to earliest:
  - rows where Amount == parsed Over/Short are skipped as cancelled re-audits
  - the first earlier parseable non-cancelled Over/Short value is used
  - if all parseable rows are cancelled, Cash Over/Short remains 0

For the selected value:
  If value < 0:  debit  = abs(value), credit = 0
  If value >= 0: debit  = 0,          credit = value

If DailyJournal.txt is absent, Cash Over/Short remains 0 and all other QA
categories are still calculated.
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
| Non-Taxable Sales | if negative | if positive |
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
