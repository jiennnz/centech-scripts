# AGENTS.md

Guidance for Codex and other AI agents working in this repository.

## Data Privacy

- Treat `pos_data/` as sensitive operational data.
- Do not read or print raw row-level `pos_data/` records unless the user explicitly asks for that specific inspection.
- Agents may inspect file names, table names, column headers, schemas, row counts, null counts, data types, and aggregate totals.
- When diagnosing discrepancies, prefer pattern-level checks:
  - grouped totals by date, store, category, payment type, status, or transaction shape
  - counts by flags such as `Refund`, `Status_ID`, `Processing_Status_ID`, `Tip_Paid`, and `Transaction_ID` length
  - min/max dates and cross-date attribution checks
  - inclusion/exclusion bucket totals
- Avoid exposing customer names, ticket-level detail, payment identifiers, employee identifiers, or transaction identifiers in chat output unless the user has asked for that exact evidence.
- If ticket-level evidence is needed, write it to a local audit file and summarize only the relevant pattern in chat.

## Financial Diagnostics

- Prefer existing scripts under `scripts/financial/pos_audit/` and `financial/sales_export_comparison/` before writing new one-off logic.
- For sales comparison discrepancies, use verifier output and generated audit files as the source of truth before inferring from raw exports.
- For `In-Store Credit Card` and `In-Store Credit Card Tips`, use `scripts/financial/pos_audit/audit_iscc_iscct.py`.
- For category rules, check `financial/sales_export_comparison/CATEGORY_CALCULATIONS.md`.

## Refund Handling

- Do not exclude all tickets where `Refund == True`.
- For ISCC/ISCCT, only online/token refund tickets are excluded from in-store card totals:
  - `Refund == True`
  - and at least one payment row has `len(Transaction_ID) == 32`
- In-store refund rows with `Transaction_ID` length `4` or `6` remain in ISCC/ISCCT so positive and negative payment rows net correctly.
- Online/token refund rows belong in `Online Credit card`, where the negative rows net against online card activity.

## Working Style

- Keep edits small and scoped to the user request.
- Do not revert unrelated user changes.
- Prefer documented repo patterns over new abstractions.
- When adding diagnostics, write checkable CSV/XLSX outputs under the existing audit/output folders.
- In final responses, report the output paths and the high-level finding without dumping sensitive raw data.
