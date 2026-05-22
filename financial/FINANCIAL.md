# Financial Sales Export Comparison — Operations Guide

This document covers how to run the sales export comparison pipeline end to end: build a dated workbook from the sales template, load CenTech and client/GL exports, and apply mismatch highlighting.

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

The pipeline uses **pandas**, **openpyxl**, **PyYAML**, and **python-dateutil**. No AWS or S3 access is required; all inputs are local CSV or Excel files.

### Template workbook

The default template path is:

```text
financial/sales_export_comparison/templates/Sales_Template.xlsx
```

Ensure that file exists (or pass `--template` to point at your copy). The template defines the layout the builder clones per day and per store block.

---

## Folder Structure

```text
centech-scripts/
  financial/
    FINANCIAL.md                     ← this guide
    sales_export_comparison/
      run.py                         ← pipeline entrypoint
      CATEGORY_CALCULATIONS.md      ← verifier formula reference
      rules/                         ← org-specific column mappings and stores
        century.yaml
        century_austin.yaml
      templates/
        Sales_Template.xlsx          ← base layout (required)
      stages/
        template_builder.py          ← Stage 1: workbook shell
        generator.py                 ← Stage 2: fill from exports
        heatmap.py                   ← Stage 3: mismatch formatting
        verifier.py                  ← QA: computes categories from raw POS files
        diagnostics.py               ← Stage 4: diagnostics tab
      runs/                          ← auto-created per period + org
        2026-04-01_2026-04-30/
          century_austin/
            centech_vs_client/       ← CenTech export vs client GL
            centech_vs_qa/           ← CenTech export vs QA (POS-computed)
            qa_vs_client/            ← QA (POS-computed) vs client GL
              input/                 ← client_export archived here
              output/
                Sales_Comparison_2026-04-01_2026-04-30.xlsx
                pos_computed.csv     ← QA-computed values written here
  pos_data/                          ← raw POS export folders (YYYY-MM-DD/)
    2026-04-01/
      Sales_Ticket.txt
      Sales_Ticket_Summary.txt
      Payment.txt
      Store_Transactions.txt
      DailyJournal.txt
      Store.txt
```

You may drop the two input files in the **repo root** before the first run; the pipeline moves them into the run folder’s `input/` directory (same idea as payroll moving `Timesheet*.csv`).

---

## Manual Inputs

Before running (unless you pass explicit paths on the command line), place exports where the script can find them.

### CenTech side

Filename stem must be **`centech_export`**, with extension `.csv`, `.xlsx`, or `.xls`:

```text
centech-scripts/centech_export.xlsx
```

### Client / GL side

Filename stem must be **`client_export`**:

```text
centech-scripts/client_export.csv
```

### Re-running the same period and org

If you already ran once, copies may live under:

```text
financial/sales_export_comparison/runs/<period>/<org>/input/
```

The pipeline prefers those files on rerun so you do not have to copy them back to the repo root.

If nothing is found, the script prompts you to drop the files and press Enter.

---

## Running the Pipeline

### Step 1: Activate virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
```

### Step 2: Run the pipeline

From the **repo root**:

```powershell
python financial/sales_export_comparison/run.py
```

You will be prompted for:

- Start and end dates (inclusive), e.g. `Mar 1 2026` and `Mar 6 2026`
- Organization — pick a name or number matching a file in `rules/` (e.g. `century`, `century_austin`)
- Client column header label (for Excel columns D/E), defaulting to the org rule’s `client_header_label`

Pass dates and org directly:

```powershell
python financial/sales_export_comparison/run.py --start "Mar 1 2026" --end "Mar 6 2026" --org century_austin
```

Pass explicit export paths:

```powershell
python financial/sales_export_comparison/run.py --start "2026-03-01" --end "2026-03-06" --org century `
  --centech-csv "C:\path\to\centech_export.xlsx" `
  --source-csv "C:\path\to\client_export.csv"
```

### Step 3: Review the summary and confirm

The pipeline prints period, organization, store list, template path, output path, and input paths, then asks:

```text
Continue? [Y/n]:
```

Type `Y` to proceed (or `n` to cancel).

### Step 4: Outputs

After a successful run:

- **Workbook:** `financial/sales_export_comparison/runs/<start>_<end>/<org>/output/Sales_Comparison_<start>_<end>.xlsx`
- **Archived inputs:** `.../runs/<period>/<org>/input/centech_export.*` and `client_export.*`

---

## Structure-only mode (no CSV comparison)

To build the workbook shell only (date tabs, headers, store blocks) without reading exports or applying the heatmap:

```powershell
python financial/sales_export_comparison/run.py --skip-data --start "Mar 1 2026" --end "Mar 6 2026" --org century
```

You will not be prompted for `centech_export` / `client_export` in this mode.

---

## Organization rules (`rules/*.yaml`)

Each org is a YAML file named `<org_key>.yaml`. It defines:

- **stores** — store numbers included in the workbook
- **category_rows** — maps category labels to row indices in the template tables
- **centech** and **client** blocks — format (`csv` or `excel`), column names, optional `date_parse_format`, category rewrites, `read_csv` / `read_excel` options, etc.
- **mismatch_tolerance** — numeric tolerance for heatmap comparison (default `0.0`)
- **sheet_date_format** — `strftime` pattern for daily sheet names (default `%b %d`)

Adding a new org: copy an existing YAML, adjust keys and columns to match that client’s export, and run with `--org <new_stem>`.

---

## Run Modes

| Mode | Left side | Right side | Flag |
|------|-----------|------------|------|
| CenTech vs Client | CenTech export | Client GL export | (default) |
| CenTech vs QA | CenTech export | QA (POS-computed) | `--pos-data-dir` |
| QA vs Client | QA (POS-computed) | Client GL export | `--pos-data-dir --qa-left` |

**QA mode** computes every financial category directly from raw POS files in `pos_data/`. See `CATEGORY_CALCULATIONS.md` for the full formula reference.

### Running QA vs Client

```powershell
python financial/sales_export_comparison/run.py `
  --start "Apr 1 2026" --end "Apr 30 2026" `
  --org century_austin `
  --qa-left `
  --pos-data-dir pos_data `
  --source-csv "financial/sales_export_comparison/runs/2026-04-01_2026-04-30/century_austin/centech_vs_client/input/client_export.csv"
```

The verifier scans `pos_data/` plus 14 extra days past `--end` to capture payments, transactions, and ticket summaries recorded in later folders but attributed to dates in the requested period. It writes `pos_computed.csv` to the run’s `output/` folder before filling the workbook.

---

## Stages (Status)

| Stage | Module | Status |
| ----- | ------ | ------ |
| 1 — Template | `stages/template_builder.py` | Done |
| 2 — Generator | `stages/generator.py` | Done |
| 3 — Heatmap | `stages/heatmap.py` | Done |
| 4 — Diagnostics | `stages/diagnostics.py` | Done |
| QA Verifier | `stages/verifier.py` | Done |

All stages are wired into `financial/sales_export_comparison/run.py` (except Stage 2, 3, and 4 are skipped when `--skip-data` is set).

### Stage 1 — Template builder

Creates one sheet per day in the period, duplicates the template’s store/category grid for each configured store, and sets CenTech (B/C) vs client (D/E) headers using your source label.

### Stage 2 — Generator

Reads the CenTech and client files according to the org rule, filters by date range and store, normalizes categories (rewrites, optional memo rules), and writes debits/credits into the workbook.

### Stage 3 — Heatmap

Compares CenTech vs client amounts per category and store, applies fills for mismatches, missing-on-one-side, and color scales to surface discrepancies quickly.

### Stage 4 — Diagnostics

Writes a Diagnostics tab summarizing per-store category totals and known issues.

### QA Verifier (`verifier.py`)

Reads raw POS files from `pos_data/<YYYY-MM-DD>/` and computes all financial categories for each store × date. Output is `pos_computed.csv` which feeds into Stage 2 as the left (QA) or right (CenTech vs QA) side.

Key behaviors:
- **Cross-date payments and ticket sales**: Payment.txt, Sales_Ticket.txt, and Sales_Ticket_Summary.txt scanned across end_date + 14 days; paid tickets are attributed by `Payment_Date`, not folder date.
- **Cross-date transactions**: Store_Transactions.txt same 14-day window; payouts and payins attributed by `Transaction_Date`.
- **Voided payouts**: `Transaction_ID` entries with a matching `Status == "Void"` row in the same date slice are excluded from payout totals.
- **Gift Card Sold in ISCC**: only the CC-paid portion (`Payment_Type_ID == 14`) of gift card sold tickets is added to ISCC; cash-paid GC purchases are excluded from the CC total.
- **Online refund handling**: refund tickets with tlen=32 payments are excluded from ISCC/ISCCT (to prevent the Tip_Paid=False row misclassifying as in-store CC), but are **included** in Online CC — their negative rows net against the original charge, matching client OLO deposit behaviour.

---

## Running a stage standalone

Commands assume repo root, venv on, and `python` on PATH.

### Template only (no `run.py`)

Useful for generating an empty comparison workbook:

```powershell
python financial/sales_export_comparison/stages/template_builder.py `
  --start "2026-03-01" --end "2026-03-06" `
  --output "financial/sales_export_comparison/runs/manual/shell.xlsx" `
  --org century_austin
```

With explicit stores instead of `--org`:

```powershell
python financial/sales_export_comparison/stages/template_builder.py `
  --start "2026-03-01" --end "2026-03-06" `
  --output "out.xlsx" `
  --stores "4028,4041"
```

Optional: `--template`, `--rules-dir`, `--source-label`, `--sheet-date-format`.

**Stages 2 and 3** are intended to run through `run.py` (they expect a filled org rule and paths consistent with the main pipeline). If you need to re-fill an existing workbook, use the Python APIs in `generator.py` / `heatmap.py` or run the full pipeline again with the same period and org.

---

## Troubleshooting

### `FileNotFoundError` for `Sales_Template.xlsx`

Create or restore `financial/sales_export_comparison/templates/Sales_Template.xlsx`, or pass `--template` to `run.py` / `template_builder.py`.

### `No rule files found` / invalid org

Check `financial/sales_export_comparison/rules/` for `*.yaml` files. The org key is the filename without `.yaml`.

### Wrong columns or empty data

Open the org YAML and verify `date_column`, `store_column`, `category_column`, `debit_column`, and `credit_column` match the export headers exactly. For Excel dates, set `date_parse_format` if the default parsing fails.

### Category rows do not line up

`category_rows` keys must match the normalized category strings after rewrites. Adjust the YAML or add `category_rewrites` / `category_starts_with` on the appropriate side.

### Import errors when running scripts

Run from the **repository root** so `financial` resolves as a package, or use `python financial/sales_export_comparison/run.py` as shown above.
