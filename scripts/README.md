# Scripts

This folder is organized by purpose:

- `financial/pos_audit/` - one-off and interactive POS audit helpers.
- `financial/sales_export_comparison/` - sales export comparison workflow and audit outputs.
- `payroll/` - payroll-related scripts.
- `utilities/` - general conversion tools.
- `data/excel_conversions/` - generated Excel exports from POS folders.
- `data/samples/` - small sample or ticket-specific CSV/XLSX files used while auditing.

Most POS audit scripts resolve `pos_data/` from the repository root, so they can be run from the repo root or directly from their subfolder.

## Compare POS Folders

Use the standalone folder comparator to check whether two POS snapshots are
identical and identify changed files, rows, and fields:

```powershell
python scripts/utilities/compare_pos_folders.py `
  pos_data/2026-06-27 `
  pos_data/2026-06-28
```

By default, audit CSVs are written under:

```text
scripts/financial/pos_audit/audits/pos_folder_comparison/<left>_vs_<right>/
```

Outputs:

- `file_summary.csv`: file hashes/statuses and row-change counts
- `row_differences.csv`: added and removed rows
- `field_differences.csv`: changed columns for rows with an inferred stable key

Use `--output-dir <path>` to override the audit destination.
