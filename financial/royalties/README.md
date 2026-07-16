# Royalties Pipeline

This folder documents the royalty audit and export logic.

Current script entry points:

```powershell
python scripts\financial\pos_audit\audit_royalty_fee.py
python scripts\financial\pos_audit\audit_royalty_fee_century.py
python financial\royalties\run.py
```

Use the per-store script for a single store audit. Use the Century script for all stores
configured in `financial/sales_export_comparison/rules/century.yaml`.

Use `financial\royalties\run.py` to build the royalties comparison workbook from:

```text
royalties_report_2026-05-04_to_2026-05-10.xlsx
client_royalties.csv
```

For a single-day run, the CenTech app export name has the same start and end date:

```text
royalties_report_2026-05-04_to_2026-05-04.xlsx
```

Example:

```powershell
python financial\royalties\run.py --start 2026-05-04 --end 2026-05-10 --org century
```

If you run without `--daily-inputs`, the interactive mode prompt also offers
`CenTech vs Client (daily files)` and `CenTech vs Client (date range + daily files)`.

To compare daily royalty exports for the same date range, put one numbered pair per
calendar day in the repo root, or pass `--daily-input-dir`:

```text
royalties_report_2026-05-04_to_2026-05-04.xlsx
client_royalties_1.csv
royalties_report_2026-05-05_to_2026-05-05.xlsx
client_royalties_2.csv
...
```

For May 4-10, the script expects the seven date-named CenTech files and client
files numbered `1` through `7`. It also still accepts the older numbered
`centech_royalties_1.xlsx` pattern. The workbook format is the same as the range
comparison; tabs come from the daily `DateRange` values in the input files.

```powershell
python financial\royalties\run.py --start 2026-05-04 --end 2026-05-10 --org century --daily-inputs
python financial\royalties\run.py --start 2026-05-04 --end 2026-05-10 --org century --daily-inputs --daily-input-dir inputs\royalties_may_4_10
```

To include both the date-range export tab and each daily export tab in one
workbook, provide the date-range files plus the daily files and use combined
mode:

```powershell
python financial\royalties\run.py --start 2026-05-04 --end 2026-05-10 --org century --combined-inputs
```

To compare a CenTech royalty export against QA/POS-computed royalties:

```powershell
python financial\royalties\run.py --start 2026-06-01 --end 2026-06-07 --org century --pos-data-dir pos_data
```

To compare QA/POS-computed royalties against a client export:

```powershell
python financial\royalties\run.py --start 2026-06-01 --end 2026-06-07 --org century --pos-data-dir pos_data --qa-left
```

To compare a CenTech royalty export against a Flexe scrape:

```powershell
python financial\royalties\run.py --start 2026-07-01 --end 2026-07-07 --org century --flexe-source --source-csv "flexepos/runs/2026-07-01_2026-07-07/century/royalties/client_royalties.csv"
```

If the scraped royalty file is in the repo root, name it:

```text
flexe_royalties.csv
```

Then run:

```powershell
python financial\royalties\run.py --start 2026-07-01 --end 2026-07-07 --org century --flexe-source
```

The comparison output is written under `financial/royalties/runs/<period>/<org>/<mode>/output/`,
where mode is `centech_vs_client`, `centech_vs_flexe`, `centech_vs_client_daily`, `centech_vs_client_combined`, `centech_vs_qa`, `qa_vs_client`, or `qa_vs_flexe`.
It includes DateRange comparison tabs, the standard heatmap/discrepancy tabs, and an `Account Mapping Check`
tab for Account Number / Account Name differences between the two exports.

Date-range input files are moved into the run `input/` folder when used. The
CenTech app filename is preserved. If a same-period run already has
`client_royalties.csv` archived, the runner asks whether to reuse that client
file or wait for a new `client_royalties` file in the repo root.

QA runs write `pos_computed.csv`, `pos_computed_detail.csv`, and `pos_computed_summary.csv`
under the run `output/` folder. The verifier uses the royalty formulas documented below and
does not emit ticket-level rows.

Calculation details live in:

```text
financial/royalties/ROYALTY_CALCULATIONS.md
```
