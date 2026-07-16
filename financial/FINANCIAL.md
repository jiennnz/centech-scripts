# Financial Operations Guide

This document covers the financial tooling in this repo:

- Sales export comparison: `financial/sales_export_comparison/run.py`
- Royalties comparison: `financial/royalties/run.py`

Both pipelines use local files only. No AWS or S3 access is required.

---

## Prerequisites

### Python

- Python 3.10 or higher
- Virtual environment activated (see `README.md` for setup)

### Dependencies

Install from the repo root:

```powershell
pip install -r requirements.txt
```

The financial scripts use **pandas**, **openpyxl**, **PyYAML**, **python-dateutil**, and **tqdm**.

### Templates

Default template paths:

```text
financial/sales_export_comparison/templates/Sales_Template.xlsx
financial/royalties/templates/Royalties_Template.xlsx
```

Pass `--template` to either runner if you need to use a different copy.

---

## Folder Structure

```text
centech-scripts/
  financial/
    FINANCIAL.md
    sales_export_comparison/
      run.py
      CATEGORY_SPEC.md
      CATEGORY_CALCULATIONS.md
      CALCULATION_DATA_FLOW_DIAGRAM.md
      add_audit_check_tabs.py
      rules/
        century.yaml
        century_austin.yaml
      templates/
        Sales_Template.xlsx
      stages/
        template_builder.py
        generator.py
        heatmap.py
        diagnostics.py
        verifier.py
      runs/
        <start>_<end>/<org>/<mode>/
          input/
          output/
            Sales_<ModeLabel>_<start>_<end>.xlsx
            pos_computed.csv
    royalties/
      run.py
      README.md
      ROYALTY_CALCULATIONS.md
      templates/
        Royalties_Template.xlsx
      stages/
        comparison.py
        verifier.py
      runs/
        <start>_<end>/<org>/<mode>/
          input/
          output/
            Royalties_<Left>_vs_<Right>_<start>_<end>.xlsx
            pos_computed.csv
            pos_computed_detail.csv
            pos_computed_summary.csv
  pos_data/
    YYYY-MM-DD/
      Sales_Ticket.txt
      Sales_Ticket_Summary.txt
      Payment.txt
      Store_Transactions.txt
      DailyJournal.txt
      Store.txt
```

Treat `pos_data/` as sensitive operational data. Prefer aggregate diagnostics and generated audit files over raw ticket-level inspection.

---

## Sales Export Comparison

### Manual inputs

Before running, place exports in the repo root unless passing explicit paths.

CenTech side:

```text
centech_export.csv
centech_export.xlsx
centech_export.xls
```

Client / GL side:

```text
client_export.csv
client_export.xlsx
client_export.xls
```

On reruns, the sales runner first checks the matching run folder:

```text
financial/sales_export_comparison/runs/<period>/<org>/<mode>/input/
```

If an expected input is missing, the script prompts you to drop it into the repo root or run input folder and press Enter.

### Standard run

From the repo root:

```powershell
.\.venv\Scripts\Activate.ps1
python financial/sales_export_comparison/run.py
```

You will be prompted for:

- Start and end dates
- Organization key from `financial/sales_export_comparison/rules/`
- Comparison mode, including CenTech vs Client, CenTech vs Flexe, CenTech vs QA, QA vs Client, and QA vs Flexe
- Client/source label for workbook columns D/E

Non-interactive example:

```powershell
python financial/sales_export_comparison/run.py --start "2026-03-01" --end "2026-03-06" --org century_austin
```

With explicit exports:

```powershell
python financial/sales_export_comparison/run.py --start "2026-03-01" --end "2026-03-06" --org century `
  --centech-csv "C:\path\to\centech_export.xlsx" `
  --source-csv "C:\path\to\client_export.csv"
```

The runner prints the period, organization, stores, mode, inputs, template, and output workbook, then asks:

```text
Continue? [Y/n]:
```

### Sales run modes

| Mode | Left side | Right side | Flags |
|---|---|---|---|
| `centech_vs_client` | CenTech export | Client GL export | default |
| `centech_vs_flexe` | CenTech export | Flexe scrape export | `--flexe-source --source-csv <flexe.csv>` |
| `centech_vs_qa` | CenTech export | QA/POS-computed sales | `--pos-data-dir pos_data` |
| `qa_vs_client` | QA/POS-computed sales | Client GL export | `--pos-data-dir pos_data --qa-left` |
| `qa_vs_flexe` | QA/POS-computed sales | Flexe scrape export | `--pos-data-dir pos_data --qa-left --flexe-source --source-csv <flexe.csv>` |
| `centech_only` | CenTech export | blank | `--centech-only` |
| structure only | workbook shell only | blank | `--skip-data` |

Output workbooks are written under:

```text
financial/sales_export_comparison/runs/<start>_<end>/<org>/<mode>/output/
```

Current sales workbook names include the mode:

```text
Sales_CenTech_vs_Client_<start>_<end>.xlsx
Sales_CenTech_vs_Flexe_<start>_<end>.xlsx
Sales_CenTech_vs_QA_<start>_<end>.xlsx
Sales_QA_vs_Client_<start>_<end>.xlsx
Sales_QA_vs_Flexe_<start>_<end>.xlsx
Sales_CenTech_only_<start>_<end>.xlsx
```

Inputs used for the run are archived under the matching `input/` folder. QA runs also write:

```text
pos_computed.csv
```

### QA/POS sales runs

QA mode computes every sales category directly from raw POS files in `pos_data/`. See:

```text
financial/sales_export_comparison/CATEGORY_SPEC.md
financial/sales_export_comparison/CATEGORY_CALCULATIONS.md
financial/sales_export_comparison/CALCULATION_DATA_FLOW_DIAGRAM.md
```

Run QA vs Client:

```powershell
python financial/sales_export_comparison/run.py `
  --start "2026-04-01" --end "2026-04-30" `
  --org century_austin `
  --qa-left `
  --pos-data-dir pos_data `
  --source-csv "financial/sales_export_comparison/runs/2026-04-01_2026-04-30/century_austin/centech_vs_client/input/client_export.csv"
```

Run CenTech vs Flexe:

```powershell
python financial/sales_export_comparison/run.py `
  --start "2026-07-01" --end "2026-07-05" `
  --org century `
  --flexe-source `
  --centech-csv "sales_report_2026-07-01_to_2026-07-05.xlsx" `
  --source-csv "flexepos/runs/2026-07-01_2026-07-06/century/financial/scraped_data_flexe.csv"
```

Run QA vs Flexe:

```powershell
python financial/sales_export_comparison/run.py `
  --start "2026-07-01" --end "2026-07-05" `
  --org century `
  --qa-left `
  --pos-data-dir pos_data `
  --include-cross-date-lookahead `
  --flexe-source `
  --source-csv "flexepos/runs/2026-07-01_2026-07-06/century/financial/scraped_data_flexe.csv"
```

Run CenTech vs QA:

```powershell
python financial/sales_export_comparison/run.py `
  --start "2026-04-01" --end "2026-04-30" `
  --org century_austin `
  --pos-data-dir pos_data `
  --centech-csv "financial/sales_export_comparison/runs/2026-04-01_2026-04-30/century_austin/centech_vs_client/input/centech_export.xlsx"
```

By default, the verifier scans:

```text
start_date - 3 days through end_date + 30 days
```

It re-attributes tickets by `Payment_Date` and store transactions by `Transaction_Date`, so payments, sales-ticket summaries, payouts, and payins recorded in a nearby folder still land on the correct business date.

Use `--strict-date-range` only for diagnostics where you intentionally want to scan the selected folders and ignore cross-date attribution. Use `--include-cross-date-lookahead` to force the default scan mode in a non-interactive command.

Use `--pos-source-date` when every selected business date should be computed from one POS folder date:

```powershell
python financial/sales_export_comparison/run.py `
  --start "2026-04-01" --end "2026-04-03" `
  --org century_austin `
  --pos-data-dir pos_data `
  --pos-source-date "2026-04-05" `
  --centech-csv "C:\path\to\centech_export.xlsx"
```

This is a targeted diagnostic mode. It reads the per-day source files from the chosen POS folder while emitting rows for the selected business dates.

### Structure-only and CenTech-only

Build the workbook shell only:

```powershell
python financial/sales_export_comparison/run.py --skip-data --start "2026-03-01" --end "2026-03-06" --org century
```

Fill only the CenTech side, with no client file or heatmap:

```powershell
python financial/sales_export_comparison/run.py --centech-only --start "2026-03-01" --end "2026-03-06" --org century
```

### Sales stages

| Stage | Module | Purpose |
|---|---|---|
| Template | `stages/template_builder.py` | Creates one sheet per day and one store block per configured store |
| Generator | `stages/generator.py` | Reads exports, normalizes categories, and writes debits/credits |
| Heatmap | `stages/heatmap.py` | Highlights mismatches, missing rows, and category differences |
| Diagnostics | `stages/diagnostics.py` | Adds a diagnostics tab with per-store/category summaries |
| QA Verifier | `stages/verifier.py` | Computes `pos_computed.csv` from raw POS files |

Stage 2, 3, and 4 are skipped when `--skip-data` is set.

### Sales verifier behavior

Key behaviors:

- Cross-date payments and ticket sales: `Payment.txt`, `Sales_Ticket.txt`, and `Sales_Ticket_Summary.txt` are scanned across the 3-day lookback and 30-day lookahead window, then attributed by `Payment_Date`.
- Cross-date transactions: `Store_Transactions.txt` uses the same scan window and attributes payouts/payins by `Transaction_Date`.
- Status 2 card rows: included for ISCC/ISCCT only when the ticket has exactly one type-14 row in the scan window.
- Status 8 card rows: excluded from ISCC/ISCCT because they are provisional.
- Voided payouts: inserted payout rows with a matching void row are excluded.
- Gift Card Sold in ISCC: only the credit-card-paid portion of gift-card-sold tickets is added to ISCC; cash-paid gift-card purchases do not inflate card totals.
- Online refund handling: online/token refund rows stay in `Online Credit card`; in-store refund rows with short transaction IDs remain in ISCC/ISCCT and net there.

### Standalone template builder

Commands assume repo root, venv on, and `python` on PATH.

```powershell
python financial/sales_export_comparison/stages/template_builder.py `
  --start "2026-03-01" --end "2026-03-06" `
  --output "financial/sales_export_comparison/runs/manual/shell.xlsx" `
  --org century_austin
```

With explicit stores:

```powershell
python financial/sales_export_comparison/stages/template_builder.py `
  --start "2026-03-01" --end "2026-03-06" `
  --output "out.xlsx" `
  --stores "4028,4041"
```

Optional flags include `--template`, `--rules-dir`, `--source-label`, and `--sheet-date-format`.

---

## Organization Rules

Sales and royalties both use org YAML files under:

```text
financial/sales_export_comparison/rules/
```

Each org file can define:

- `stores`: store numbers included in the workbook
- `category_rows`: sales comparison category row positions
- `centech`, `client`, and `qa` input blocks
- `mismatch_tolerance`
- `sheet_date_format`
- `client_header_label`

Adding a new org usually means copying an existing YAML, changing the store list and column mappings, then running with `--org <new_stem>`.

---

## Royalties Comparison

Detailed royalty instructions live in:

```text
financial/royalties/README.md
financial/royalties/ROYALTY_CALCULATIONS.md
```

### Royalty inputs

The range-mode CenTech export is usually named:

```text
royalties_report_<start>_to_<end>.xlsx
```

The runner also accepts these fallback names:

```text
centech_royalties.xlsx
centech_royalties.xls
centech_royalties.csv
```

Client export:

```text
client_royalties.csv
client_royalties.xlsx
client_royalties.xls
```

Flexe scraped royalty export:

```text
flexe_royalties.csv
flexe_royalties.xlsx
flexe_royalties.xls
```

For daily royalty comparison, provide one CenTech/client pair per date. Preferred CenTech daily names:

```text
royalties_report_2026-05-04_to_2026-05-04.xlsx
royalties_report_2026-05-05_to_2026-05-05.xlsx
```

Client daily files are numbered:

```text
client_royalties_1.csv
client_royalties_2.csv
```

The older `centech_royalties_1.xlsx` naming pattern is still accepted when date-named CenTech files are not present.

### Royalty run modes

| Mode | Left side | Right side | Flags |
|---|---|---|---|
| `centech_vs_client` | range CenTech export | range client export | default |
| `centech_vs_flexe` | range CenTech export | Flexe royalty scrape | `--flexe-source --source-csv <flexe.csv>` |
| `centech_vs_client_daily` | daily CenTech files | daily client files | `--daily-inputs` |
| `centech_vs_client_combined` | range + daily CenTech files | range + daily client files | `--combined-inputs` |
| `centech_vs_qa` | CenTech export | QA/POS-computed royalties | `--pos-data-dir pos_data` |
| `qa_vs_client` | QA/POS-computed royalties | client export | `--pos-data-dir pos_data --qa-left` |
| `qa_vs_flexe` | QA/POS-computed royalties | Flexe royalty scrape | `--pos-data-dir pos_data --qa-left --flexe-source --source-csv <flexe.csv>` |

Output workbooks are written under:

```text
financial/royalties/runs/<start>_<end>/<org>/<mode>/output/
```

Workbook names use the compared labels:

```text
Royalties_CenTech_vs_Client_<start>_<end>.xlsx
Royalties_CenTech_vs_Flexe_<start>_<end>.xlsx
Royalties_CenTech_vs_QA_<start>_<end>.xlsx
Royalties_QA_vs_Client_<start>_<end>.xlsx
Royalties_QA_vs_Flexe_<start>_<end>.xlsx
```

Royalty QA runs also write:

```text
pos_computed.csv
pos_computed_detail.csv
pos_computed_summary.csv
pos_computed_skipped_store_days.csv
```

### Royalty examples

Range comparison:

```powershell
python financial/royalties/run.py --start 2026-05-04 --end 2026-05-10 --org century
```

Daily files:

```powershell
python financial/royalties/run.py --start 2026-05-04 --end 2026-05-10 --org century --daily-inputs
```

Daily files from another folder:

```powershell
python financial/royalties/run.py --start 2026-05-04 --end 2026-05-10 --org century --daily-inputs --daily-input-dir inputs/royalties_may_4_10
```

Range plus daily tabs in one workbook:

```powershell
python financial/royalties/run.py --start 2026-05-04 --end 2026-05-10 --org century --combined-inputs
```

CenTech vs QA:

```powershell
python financial/royalties/run.py --start 2026-06-01 --end 2026-06-07 --org century --pos-data-dir pos_data
```

QA vs Client:

```powershell
python financial/royalties/run.py --start 2026-06-01 --end 2026-06-07 --org century --pos-data-dir pos_data --qa-left
```

CenTech vs Flexe:

```powershell
python financial/royalties/run.py `
  --start 2026-07-01 --end 2026-07-07 `
  --org century `
  --flexe-source `
  --centech "royalties_report_2026-07-01_to_2026-07-07.xlsx" `
  --source-csv "flexepos/runs/2026-07-01_2026-07-07/century/royalties/client_royalties.csv"
```

QA vs Flexe:

```powershell
python financial/royalties/run.py `
  --start 2026-07-01 --end 2026-07-07 `
  --org century `
  --pos-data-dir pos_data `
  --qa-left `
  --flexe-source `
  --source-csv "flexepos/runs/2026-07-01_2026-07-07/century/royalties/client_royalties.csv"
```

Use `--yes` to skip the confirmation prompt in automated runs.

Royalty QA mode uses a royalty-specific lookback/lookahead scan window for payment-date attribution. Use `--strict-date-range` only for diagnostics.

---

## Troubleshooting

### `FileNotFoundError` for a template

Create or restore the matching template under `financial/.../templates/`, or pass `--template`.

### `No rule files found` / invalid org

Check `financial/sales_export_comparison/rules/` for `*.yaml` files. The org key is the filename without `.yaml`.

### Wrong columns or empty sales data

Open the org YAML and verify `date_column`, `store_column`, `category_column`, `debit_column`, and `credit_column` match the export headers exactly. For Excel dates, set `date_parse_format` if default parsing fails.

### Category rows do not line up

`category_rows` keys must match normalized category strings after rewrites. Adjust the YAML or add `category_rewrites` / `category_starts_with` on the appropriate side.

### Existing QA output is reused

If `pos_computed.csv` already exists, the runner asks whether to regenerate it. Answer `y` to recompute from `pos_data/`, or press Enter to reuse the existing file.

### Import errors when running scripts

Run from the repository root so `financial` resolves as a package:

```powershell
python financial/sales_export_comparison/run.py
python financial/royalties/run.py
```
