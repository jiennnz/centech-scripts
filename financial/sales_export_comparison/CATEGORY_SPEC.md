# Sales Export Category Specification

## Purpose

This document defines **what each financial category means and how it is calculated**, independent of any one implementation. It is a handoff document for a backend developer.

The sibling file `CATEGORY_CALCULATIONS.md` describes how *this tool* — a Python verifier that reads daily POS export `.txt` folders — computes the categories. That description is tied to file scanning, pandas, and folder layout. The **backend that produces the real export almost certainly works differently** (live database, different schema, different query path).

This spec states the *business logic* so a backend developer can confirm their implementation matches without reading the verifier code. Where the verifier does something only because of its file-based input, it is called out under **Implementation notes** at the end and can be ignored when comparing against a database-backed backend.

If you need the operational read path rather than just the business rules, see
`CALCULATION_DATA_FLOW_DIAGRAM.md`.

## Output shape

Each (store, date) pair produces up to 24 category rows. Each row carries a **Debit** value or a **Credit** value, never both — except Cash Over/Short Adjustment, which is one or the other depending on sign. A category that nets to 0 is omitted.

## Data entities

The logic references five conceptual record types. Names in parentheses are the verifier's source files; your backend's tables/views will be named differently — map by meaning, not name.

| Entity | Meaning | Key fields |
|---|---|---|
| Ticket (`Sales_Ticket`) | one sale / order | `Store_ID`, `Tax_Exempt`, `Ticket_Type_ID`, `Status_ID`, `Refund` |
| Ticket Summary (`Sales_Ticket_Summary`) | per-ticket money breakdown, one row per `Category_ID` | `Ticket_Number`, `Category_ID`, `Taxable_Amount`, `Non_Taxable_Amount`, `Total` |
| Payment (`Payment`) | one tender applied to a ticket | `Payment_Type_ID`, `Payment_Name_ID`, `Transaction_ID`, `Tendered_Amount`, `Change`, `Tip_Amount`, `Tip_Paid`, `Processing_Status_ID`, `Payment_Date`, `Name` |
| Store Transaction (`Store_Transactions`) | register event — payout / payin / audit | `Transaction_Type_Name`, `Status`, `Amount`, `Transaction_Date` |
| Daily Journal (`DailyJournal`) | register-audit log entry | `Action`, `Amount`, `Comments` |

### Code values

**Ticket Summary `Category_ID`:**

| ID | Meaning |
|---|---|
| 1 | Sale amount |
| 2 | Discount / adjustment — always subtracted |
| 5 | Tax |
| 7 | Donation |

**Payment `Payment_Type_ID`:**

| ID | Tender |
|---|---|
| 3 | paired with 14 for online tips only |
| 5 | Gift card |
| 7 | House account |
| 13 | 3rd party delivery |
| 14 | Credit card |

**Payment `Transaction_ID` length** — distinguishes how a card was processed:

| Length | Meaning |
|---|---|
| 4 | In-store swipe, short ID |
| 6 | Swiped, tip settled |
| 32 | Token / chip card, or online |

**`Processing_Status_ID`:** 4 = Processed (settled), 9 = Discarded (voided), 2 = Open.
Status 2 rows are eligible for ISCC/ISCCT only when the ticket has exactly one type-14 row
across the full cross-date scan window (3-day lookback + configured range + 30-day lookahead).
Multiple type-14 rows for the same ticket mean the payment was reprocessed to status 4 in a
later export, or is a duplicate; in that case the status-4 row handles inclusion and the
status-2 row is excluded.

## Core scoping rules

These apply to every category.

1. **Store scope.** A store-day only counts tickets whose `Store_ID` belongs to that store.
2. **Payment-date attribution.** A ticket counts on the date its payment settles (`Payment_Date`), not the date the ticket was created. A ticket opened just before midnight and paid after midnight belongs to the *next* day.
3. `store_paid` = the set of tickets for the store whose payment is attributed to the current date. **Most categories operate on `store_paid`.**

## Ticket subsets

Computed once per store-day, reused across categories:

| Subset | Definition |
|---|---|
| `non_exempt_tix` | `Tax_Exempt = false` |
| `exempt_tix` | `Tax_Exempt = true` |
| `tt_8_tix` | `Ticket_Type_ID = 8` (3rd-party order) |
| `tt_1_7_tix` | `Ticket_Type_ID in (1, 7)` |
| `tt_5_tix` | `Ticket_Type_ID = 5` |
| `status_8_tix` | `Status_ID = 8` — a gift card was sold on this ticket |
| `cancelled_tix` | `Status_ID = 2` in Sales_Ticket — cancelled tickets |
| `refund_tix` | `Refund = true` |
| `online_refund_tix` | `refund_tix` that also have at least one payment row with `Transaction_ID` length 32 |

`STS(tickets, [category_ids], field)` = sum of `field` in Ticket Summary, restricted to those tickets and those `Category_ID` values.

---

## Sales categories

**Subject to Tax** — taxable sales revenue.
- Credit. Tickets: `(store_paid - cancelled_tix) ∩ non_exempt_tix`.
- `STS(tix,[1],Taxable_Amount) - STS(tix,[2],Taxable_Amount)`

**Non-Taxable Sales** — non-taxable sales revenue, excluding gift-card sales and donations.
- Tickets: `store_paid` minus `status_8_tix`.
- `non_tax = STS(tix,[1],Non_Taxable_Amount) - STS(tix,[2],Non_Taxable_Amount) - STS(tix,[7],Total)`
- If `non_tax >= 0`: Credit = `non_tax`. If `non_tax < 0`: Debit = `abs(non_tax)`. A day with net refunds can produce a negative value; the client export places the absolute value in Debit rather than a negative Credit.
- The donation term (category 7) is subtracted so it does not double-count against the Donation category.

**3rd Party Tax Exempt** — exempt sales on 3rd-party-type tickets.
- Credit. Tickets: `store_paid ∩ exempt_tix ∩ tt_8_tix`.
- `STS(tix,[1],Taxable_Amount) - STS(tix,[2],Taxable_Amount)`

**Tax Exempt** — exempt sales on normal ticket types.
- Credit. Tickets: `store_paid ∩ exempt_tix ∩ tt_1_7_tix`.
- `STS(tix,[1],Taxable_Amount) - STS(tix,[2],Taxable_Amount)`

**Sales Tax** — tax collected.
- Credit. Tickets: `(store_paid - cancelled_tix) ∩ non_exempt_tix`.
- `STS(tix,[5],Total)`

**Donation** — donations collected.
- Credit. `STS(store_paid,[7],Total)`

## Credit card categories

In-store vs online card payments are distinguished by `Transaction_ID` length and the `Tip_Paid` flag.

Important: `Transaction_ID` length 32 by itself does **not** mean online. The business rule
is a two-part discriminator plus a refund override:

- `tlen=32` and `Tip_Paid=false` can be a normal in-store register card payment. This is
  the tokenized/chip in-store shape produced by the POS.
- `tlen=32`, `Tip_Paid=true`, and `Ticket_Type_ID=5` is online card activity.
- `tlen=32` rows on in-store ticket types (`Ticket_Type_ID IN (1,2,3,4,6,7)`) are
  in-store card activity.
- If a refund ticket has `Ticket_Type_ID=5` and any 32-character card row, it is treated
  as an online refund and both sides of the refund event stay in `Online Credit Card` so
  the reversal nets in the same bucket as the original online charge.

**In-store CC shape** — a payment row qualifies when `Payment_Type_ID = 14` and any of:
- length 6 and `Tip_Paid = true`, or
- length 32 and `Ticket_Type_ID IN (1,2,3,4,6,7)`, or
- length 4.

Apply this test to each `Payment` row. Do not dedupe or collapse by `Ticket_Number` before summing; one ticket can have multiple qualifying in-store card rows from split tenders, adjustments, or negative correction rows, and all qualifying rows must net together.

**In-Store Credit Card (ISCC)** — card payments taken at the register.
- Debit.
- Rows: in-store CC shape, `Processing_Status_ID` eligible (4 always; 2 if sole type-14 row for ticket in scan window), ticket NOT in `status_8_tix`, ticket NOT in `online_refund_tix`, ticket NOT in `cancelled_tix`.
- `SUM(Tendered_Amount - Change + Tip_Amount)` plus `gc_sold_cc` (see Gift Card Sold).
- `status_8` tickets are excluded because card-paid gift-card purchases are reported separately, then re-added as `gc_sold_cc`. `online_refund_tix` are excluded because online refund rows would otherwise misclassify here — they belong in Online Credit Card.
- Multi-row tickets: if the same `Ticket_Number` has two or more qualifying ISCC payment rows, include every qualifying row. Example shape: one row can contribute a positive amount and another row on the same ticket can contribute a negative amount; the ISCC contribution is their net sum, not the first row or a deduped ticket total.
- Business intent: keep register card activity in ISCC even when the processor emits a
  tokenized 32-character ID, but keep online refund reversals entirely in Online CC so one
  online event does not split across two categories.

**ISCC edge cases:**

*Chip/token card (tlen=32, Tip_Paid=false) — looks online, is in-store.* A chip card processed at the register creates a 32-character token-based `Transaction_ID`. The POS flow always leaves `Tip_Paid=false`; only OLO/online payments set it to `true`. So `tlen=32, Tip_Paid=false` is the correct in-store discriminator even though the 32-char ID superficially resembles an online payment. A later tip-settlement row (new `Transaction_ID`, same day or next) arrives with the same `tlen=32, Tip_Paid=false` shape and must also be included.

> Ticket #1001 — chip card at register:
> - Row A (charge): tlen=32, Tip_Paid=false, Tendered=25.00, Tip=0 → ISCC +25.00
> - Row B (tip settled next day, new Transaction_ID): tlen=32, Tip_Paid=false, Tendered=0, Tip=3.00 → ISCC +3.00, ISCCT +3.00

*Online refund excluded; in-store refund kept.* A refund ticket (`Refund=true`) that has at least one tlen=32 payment row falls into `online_refund_tix` — all its rows go to Online CC, including the tlen=32/Tip_Paid=false row that would otherwise match the ISCC shape. A refund ticket whose payment rows are all tlen=4/6 is NOT in `online_refund_tix` and stays in ISCC with negative `Tendered_Amount`, netting against the day's total.

> Ticket #2001 — online refund (has tlen=32 row → in `online_refund_tix`):
> - Row A: tlen=32, Tip_Paid=false, Tendered=−20.00 → ISCC shape but excluded → Online CC
> - Row B: tlen=32, Tip_Paid=true,  Tendered=+20.00 → Online CC (Tip_Paid=true)
> - ISCC: 0 | Online CC rows net to 0
>
> Ticket #2002 — in-store refund (only tlen=6 rows → NOT in `online_refund_tix`):
> - Row A: tlen=6, Tip_Paid=true, Tendered=−20.00, Tip=−2.00 → ISCC −22.00

*CC-paid gift card (status_8 exclusion + gc_sold_cc).* A ticket where a gift card was sold (`Status_ID=8`) is excluded from ISCC qualifying rows regardless of tender. The CC-paid portion is captured separately as `gc_sold_cc` and added to the ISCC total afterward. A cash-paid gift card purchase has no CC payment row, so `gc_sold_cc` is 0 — cash does not inflate ISCC.

> Ticket #3001 — gift card purchased with CC (Status_ID=8):
> - Row: Payment_Type_ID=14, tlen=6, Tip_Paid=true, Tendered=50.00
> - Excluded from ISCC qualifying rows → gc_sold_cc=50.00 added to ISCC debit total
> - Gift Card Sold credit = 50.00 (all tender types combined)
>
> Same-day cash gift card purchase:
> - Payment_Type_ID≠14 → gc_sold_cc += 0; cash does not reach ISCC

**In-Store Credit Card Tips (ISCCT)** — tips on register card payments.
- Credit.
- Rows: `Payment_Type_ID = 14`, `Processing_Status_ID` eligible (same rule as ISCC), `Tip_Amount ≠ 0`, ticket NOT in `status_8_tix`/`online_refund_tix`, and either `Transaction_ID` length in (4, 6) OR length 32 with `Tip_Paid = false`.
- `SUM(Tip_Amount)`.
- The test is `≠ 0`, not `> 0`, so negative refund tips net correctly.

**Discarded CC** — card payments that were voided / discarded.
- Debit.
- Same row rule as ISCC but `Processing_Status_ID = 9`.
- `SUM(Tendered_Amount - Change + Tip_Amount)`.

**Online Credit Card** — card payments taken online.
- Debit.
- Rows: `Payment_Type_ID = 14`, length 32, `Ticket_Type_ID=5`, and either `Tip_Paid = true` OR ticket in `online_refund_tix`.
- `SUM(Tendered_Amount + Tip_Amount)`. No `Change` term — online payments have no change.
- Business intent: online charges and their refund reversals net together in the online
  bucket, even if one refund row has the same `tlen=32`/`Tip_Paid=false` shape that would
  normally look in-store when viewed in isolation.

**Online Credit Card Tips** — tips on online card payments.
- Credit.
- Rows: `Payment_Type_ID in (14, 3)`, length 32, `Ticket_Type_ID=5`, `Tip_Paid = true`.
- `SUM(Tip_Amount)`.

## Gift card categories

**Gift Card** — a gift card used as tender.
- Debit. Rows: `Payment_Type_ID = 5`, length 6. `SUM(Tendered_Amount)`.

**Gift Card Sold** — value of gift cards purchased.
- Credit.
- `gc_sold_pay = SUM(Tendered_Amount - Change)` over payments on `store_paid ∩ status_8_tix`, **any tender type** — a gift card can be bought with cash, card, or anything else.
- `credit = gc_sold_pay`.
- `gc_sold_cc = SUM(Tendered_Amount - Change)` over the same tickets but `Payment_Type_ID = 14` only. This is the figure added into the ISCC total — cash-bought gift cards must not inflate the card total.

**Online Gift Card** — gift card bought or used online.
- Debit. Rows: `Payment_Type_ID = 5`, length 32. `SUM(Tendered_Amount + Tip_Amount)`.

**Online Gift Card Tips** — tips on online gift-card transactions.
- Credit. Rows: `Payment_Type_ID = 5`, `Payment_Name_ID = 8`, ticket in `store_paid ∩ tt_5_tix`. `SUM(Tip_Amount)`.

## Store transaction categories

**Register Audit** — counted register cash total.
- Debit. From Store Transactions, `Transaction_Type_Name = "Register Audit"` — the last non-void row's `Amount` for the store-day, skipping trailing cancelled re-audits whose matching Daily Journal row has `Amount == Over/Short`.

**Payout** — cash paid out of the register.
- Debit. Store Transactions, `Transaction_Type_Name = "Store Payout"`, `Status = "Inserted"`, excluding any `Transaction_ID` that also has a `Status = "Void"` row. `SUM(ABS(Amount))`.

**Payin** — cash added to the register.
- Credit. `Transaction_Type_Name = "Payins"`, `Status = "Inserted"`. `SUM(Amount)`.

**Cash Over/Short Adjustment** — register overage / shortage.
- From Daily Journal, `Action = "Register Audit"`, value parsed from the `Comments` text `Over/Short: <value>`.
- Value negative → Debit = `abs(value)`. Value zero or positive → Credit = `value`.

**Register Audit / Cash Over/Short cancellation:** if the Daily Journal audit row's `Amount` equals the parsed Over/Short value, **both** Register Audit and Cash Over/Short Adjustment are zeroed.

## 3rd party delivery

All use `Payment_Type_ID = 13`, distinguished by the `Name` field. Debit = `SUM(Tendered_Amount)`.

| Category | `Name` value |
|---|---|
| 3rd Party - UberEats | 4001 |
| 3rd Party - DoorDash | 4004 |
| 3rd Party - GrubHub | 4003 |
| 3rd Party - EZ Cater | 74 or 4022 |

## House Account

**House Account** — charged to a house / customer account.
- Debit. Rows: `Payment_Type_ID = 7`. `SUM(Tendered_Amount)`.

## Debit vs credit summary

| Category | Side |
|---|---|
| Subject to Tax | Credit |
| Non-Taxable Sales | Debit if negative, Credit if positive |
| 3rd Party Tax Exempt | Credit |
| Tax Exempt | Credit |
| Sales Tax | Credit |
| Donation | Credit |
| Register Audit | Debit |
| In-Store Credit Card | Debit |
| In-Store Credit Card Tips | Credit |
| Discarded CC | Debit |
| Online Credit Card | Debit |
| Online Credit Card Tips | Credit |
| Gift Card | Debit |
| Gift Card Sold | Credit |
| Online Gift Card | Debit |
| Online Gift Card Tips | Credit |
| Payout | Debit |
| Payin | Credit |
| Cash Over/Short Adjustment | Debit if negative, Credit if positive |
| 3rd Party - UberEats | Debit |
| 3rd Party - DoorDash | Debit |
| 3rd Party - GrubHub | Debit |
| 3rd Party - EZ Cater | Debit |
| House Account | Debit |

---

## Implementation notes — verifier-specific, may not apply to your backend

1. **3-day lookback + 30-day lookahead.** The verifier reads one export folder per calendar day. To handle tickets created just before the range start (e.g. late-night on the day before) whose payment settles on start_date, the verifier scans 3 extra days of folders *before* start_date. To handle payments that settle in a later folder than the ticket, the verifier also scans 30 extra days *after* end_date. In both cases rows are re-attributed by their `Payment_Date` / `Transaction_Date`. A backend querying a live database does not need this workaround.

2. **Payment-date sales attribution.** For the same reason, ticket attributes and Ticket Summary rows are pulled from the folder where the ticket was created but attributed to the payment date. A database-backed backend gets this for free.

3. **Register Audit auto-fill.** When the POS has no `Register Audit` row for a store-day
   and credits exceed debits by more than $0.001, the verifier fills Register Audit with the
   whole-dollar portion of the imbalance. The fractional remainder (cents) is applied as a
   negative Cash Over/Short (shortage debit) to keep the ledger balanced. A backend with a
   live audit count does not need this fallback.

4. **Gift Card Sold Ticket-Summary fallback — known dead code.** The verifier carries a fallback path (`gc_sold_sts`) meant to recover gift-card-sold value from Ticket Summary when no `status_8` payment rows exist. As written it only runs when `store_paid ∩ status_8_tix` is empty, yet it also filters on that same empty set, so it always yields 0. If your backend needs a fallback, the *intended* logic is: `SUM(Non_Taxable_Amount)` from Ticket Summary where `Category_ID = 1`, `Taxable_Amount = 0`, `Non_Taxable_Amount > 0`, over the gift-card-sold tickets. Confirm whether a fallback is actually needed before implementing it.
