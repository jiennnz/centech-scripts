# Sales Export Calculation Data Flow

This diagram explains how the current implementation reads data, computes QA/POS category
rows, and feeds the workbook comparison pipeline.

It is based on the current code path in:

- `financial/sales_export_comparison/run.py`
- `financial/sales_export_comparison/stages/verifier.py`
- `financial/sales_export_comparison/stages/generator.py`

## 1. End-to-end pipeline flow

```mermaid
flowchart TD
    A[CLI / interactive run.py] --> B[Resolve run mode]
    B --> B1[CenTech vs Client]
    B --> B2[CenTech vs QA]
    B --> B3[QA vs Client]
    B --> B4[CenTech only]

    B --> C[Build workbook skeleton<br/>template_builder]
    C --> D{QA/POS side enabled?}
    D -- No --> G[generator fills workbook from exports]
    D -- Yes --> E[verifier builds pos_computed.csv]
    E --> G

    G --> H{Comparison mode?}
    H -- Yes --> I[heatmap marks mismatches]
    H -- No --> J[skip heatmap]

    I --> K[diagnostics tab]
    J --> K
    K --> L[archive inputs into run/input]
```

## 2. Verifier scan and attribution flow

```mermaid
flowchart TD
    A[Verifier date range] --> B{include_cross_date_lookahead?}
    B -- Yes --> B1[Scan window<br/>start-3 days to end+30 days]
    B -- No --> B2[Scan only selected date range]
    B1 --> C[Read POS text exports by folder date]
    B2 --> C
    C --> C1[Sales_Ticket.txt]
    C --> C2[Sales_Ticket_Summary.txt]
    C --> C3[Payment.txt]
    C --> C4[Store_Transactions.txt]
    C --> C5[DailyJournal.txt]
    C --> C6[Store.txt]

    C1 --> D[Build ticket-level attributes<br/>Store_ID Tax_Exempt Ticket_Type_ID Status_ID Refund]
    C2 --> E[Build summary rows by Ticket_Number and Category_ID]
    C3 --> F[Build payment rows<br/>Payment_Date Transaction_ID Tip_Paid Tendered Change Tip]
    C4 --> G[Build store transaction rows<br/>Transaction_Date Type Status Amount]
    C5 --> H[Build register audit / over-short rows]

    D --> I[Pre-build cross-date sales slices by Payment_Date]
    E --> I
    F --> J[Pre-build cross-date payment slices by Payment_Date]
    G --> K[Pre-build cross-date store transaction slices by Transaction_Date]
    H --> L[Keep DailyJournal in folder-date slice]

    I --> M[Create store x date tasks for selected date range]
    J --> M
    K --> M
    L --> M
    M --> N[Process store-day tasks in parallel]
```

## 3. Store-day calculation context

```mermaid
flowchart TD
    A[One store x one date] --> B[Read same-day folder files<br/>Sales Ticket Summary Payment Store Txn DailyJournal Store]
    B --> C{Cross-date sales slice exists?}
    C -- Yes --> D[Replace ticket and summary context<br/>with Payment_Date-attributed sales slice]
    C -- No --> E[Use same-folder sales context]

    D --> F[Resolve store_id from Store.txt]
    E --> F
    F --> G[store_tix<br/>tickets whose Store_ID matches]
    G --> H{Cross-date payment slice exists?}
    H -- Yes --> I[all_paid from cross-date Payment_Date slice]
    H -- No --> J[all_paid from same-folder Payment.txt filtered by Payment_Date]
    I --> K[store_paid = store_tix intersect all_paid]
    J --> K

    K --> L[non_exempt_tix]
    K --> M[exempt_tix]
    K --> N[tt_8_tix]
    K --> O[tt_1_7_tix]
    K --> P[tt_5_tix]
    K --> Q[status_8_tix]
    K --> R[refund_tix]

    R --> S[online_refund_tix<br/>refund tickets having any payment row with tlen=32]
```

## 4. Card payment decision flow

```mermaid
flowchart TD
    A[Payment row] --> B{Payment_Type_ID == 14?}
    B -- No --> Z[Not a credit card category]
    B -- Yes --> C{Processing_Status_ID}

    C -- 9 --> D[Discarded CC candidate]
    C -- 4 --> E[Settled CC candidate]

    E --> F{Ticket in status_8_tix?}
    F -- Yes --> G[Exclude from ISCC/ISCCT row sum<br/>re-add CC amount later as gc_sold_cc]
    F -- No --> H{Ticket in online_refund_tix?}

    H -- Yes --> I[Force ticket rows to Online CC path]
    H -- No --> J{Transaction_ID length and Tip_Paid}

    J -- 4 any tip --> K[ISCC shape]
    J -- 6 and Tip_Paid=True --> K
    J -- 32 and Tip_Paid=False --> K
    J -- 32 and Tip_Paid=True --> L[Online CC shape]
    J -- anything else --> Z

    K --> M[ISCC = Tendered - Change + Tip<br/>plus gc_sold_cc after row sum]
    K --> N{Tip_Amount != 0?}
    N -- Yes --> O[ISCCT = Tip_Amount]
    N -- No --> P[No ISCCT contribution]

    I --> Q[Online CC = Tendered + Tip]
    L --> Q
```

## 5. Why `tlen=32` splits two ways

```mermaid
flowchart LR
    A[tlen=32 row] --> B{Tip_Paid}
    B -- False --> C[Usually in-store chip/token register payment]
    B -- True --> D[Online card payment]

    C --> E{Refund ticket has any tlen=32 row?}
    E -- No --> F[ISCC / ISCCT path]
    E -- Yes --> G[Online refund override]

    G --> H[Keep both refund and original rows in Online CC]
    D --> H
```

Interpretation:

- `tlen=32` alone does not mean online.
- `tlen=32` with `Tip_Paid=False` is the in-store chip/token shape used by the POS.
- `tlen=32` with `Tip_Paid=True` is online card activity.
- Online refunds are forced into `Online CC` as a ticket-level override so the reversal nets
  in the same bucket as the original online charge.

## 6. Category family calculation map

```mermaid
flowchart TD
    A[Per store-date slice] --> B[Sales categories<br/>Ticket Summary + ticket subsets]
    A --> C[Credit card categories<br/>Payment rows + row-shape rules]
    A --> D[Gift card categories<br/>Payment rows + status_8 logic]
    A --> E[Store transaction categories<br/>Store_Transactions + DailyJournal]
    A --> F[3rd party / house account<br/>Payment type and Name filters]

    B --> G[Debit/Credit output rows]
    C --> G
    D --> G
    E --> G
    F --> G
```

## 7. Register audit balancing branch

```mermaid
flowchart TD
    A[Computed category totals] --> B{Register Audit from POS == 0?}
    B -- No --> C[Keep POS Register Audit]
    B -- Yes --> D[Compute credits minus debits imbalance]
    D --> E{Imbalance > 0.001?}
    E -- No --> F[Leave Register Audit at 0]
    E -- Yes --> G[Register Audit = whole-dollar part of imbalance]
    G --> H[Decimal remainder becomes negative Cash Over/Short debit]
```

This branch exists in `verifier.py` and is implementation-specific. It is not just a
presentation rule; it changes the emitted QA/POS output rows when no POS Register Audit row
exists and credits exceed debits.

## 8. Read order in practice

1. Read all relevant folders in the expanded scan window.
2. Optionally expand that scan window by 3 days before start and 30 days after end.
3. Pre-build cross-date payment slices keyed by `Payment_Date`.
4. Pre-build cross-date store transaction slices keyed by `Transaction_Date`.
5. Pre-build cross-date ticket/summary slices keyed by `Payment_Date`.
6. For each selected store-date, compute one store-day task in parallel.
7. Emit non-zero QA/POS category rows into `pos_computed.csv`.
8. Feed that CSV into the workbook generator when the run mode uses QA.
9. Apply heatmap and diagnostics in workbook-comparison modes.
