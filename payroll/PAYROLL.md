# Payroll Pipeline — Operations Guide

This document covers how to run the payroll pipeline end to end.
It will be updated as each stage is completed.

---

## Prerequisites

### Python

- Python 3.10 or higher
- Virtual environment activated (see `README.md` for setup)

### AWS CLI Access

You need AWS CLI credentials to pull POS data from S3.

If you do not have access yet, ask DevOps for:

- IAM account
- AWS Access Key
- AWS Secret

Verify access with:

```powershell
aws sts get-caller-identity
aws s3 ls s3://century-data/pos_data/
```

---

## Folder Structure

```text
centech-scripts/
  pos_data/                          ← synced POS data (shared, not per-run)
    2026-03-09/
    2026-03-16/
    2026-03-23/
  Timesheet_03-22-2026.csv          ← drop webapp export here before running
  payroll/
    run_payroll.py                   ← pipeline entrypoint
    runs/
      Mar-09-2026_Mar-22-2026/       ← auto-created per pay period
        input/                       ← pipeline moves the Timesheet CSV here
        output/                      ← all generated outputs land here
```

---

## Running the Pipeline

### Step 0: Place the webapp export CSV

Before running anything, export the timesheet from the webapp and drop it in the repo root.

The filename must start with `Timesheet`:

```text
centech-scripts/Timesheet_Mar-09-2026.csv
```

The pipeline will detect it automatically and move it to the run folder's `input/` directory.

### Step 1: Activate virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
```

### Step 2: Run the pipeline

```powershell
python payroll/run_payroll.py
```

It will prompt you:

```text
Start date: Mar 9 2026
End date:   Mar 22 2026
Employee_Time_Clock source: use end+1 date folder? [Y/n]:
```

You can also pass dates directly:

```powershell
python payroll/run_payroll.py --start "Mar 9 2026" --end "Mar 22 2026"
```

To choose the time-clock source non-interactively:

```powershell
python payroll/run_payroll.py --start "Mar 9 2026" --end "Mar 22 2026" --timeclock-source end+1
python payroll/run_payroll.py --start "Mar 9 2026" --end "Mar 22 2026" --timeclock-source end
```

### Step 3: Review the sync summary

Before proceeding, the pipeline will print:

```text
=== Payroll Pipeline ===
Pay period   : Mar-09-2026_Mar-22-2026
Run folder   : payroll/runs/Mar-09-2026_Mar-22-2026
POS data     : pos_data/
Sync folders : 2026-03-09, 2026-03-16, 2026-03-23
Time clocks  : Employee_Time_Clock.txt from 2026-03-23

Continue? [Y/n]:
```

Type `Y` to proceed.

### Step 4: Wait for S3 sync to complete

The pipeline will pull any missing POS data folders into `pos_data/`.
Folders already present locally are reused automatically.

To force a fresh download even if data exists:

```powershell
python payroll/run_payroll.py --force-sync
```

---

## Re-running a Pay Period

If you run the same pay period again, the pipeline detects the existing folder
and creates a new timestamped rerun folder automatically:

```text
payroll/runs/Mar-09-2026_Mar-22-2026_run_2_20260324-101530/
```

---

## Stages (Status)

| Stage          | Script                                       | Status    |
| -------------- | -------------------------------------------- | --------- |
| 1 — S3 Sync    | `stages/s3_sync/sync.py`                     | Done      |
| 2 — Attendance | `stages/attendance/attendance_all_stores.py` | Done      |
| 3 — Hours      | `stages/hours/main.py`                       | Done      |
| 4 — Tips       | `stages/tips/tips.py`                        | Done      |
| 5 — Generate   | `stages/generate/generate.py`                | Done      |
| 6 — Comparison | `stages/comparison/main.py`                  | Done      |

All stages are now wired into `run_payroll.py`.

---

## Manual Input (Stage 6)

Before starting the pipeline, export the timesheet from the webapp and place it in the repo root.

The filename must start with `Timesheet`:

```text
centech-scripts/Timesheet_<anything>.csv
```

The pipeline will automatically find it, move it into the run folder, and use it for comparison:

```text
payroll/runs/<period>/input/Timesheet_<original-name>.csv
```

If no matching file is found when Stage 6 is reached, the pipeline will pause and prompt you to drop it before continuing. Type `skip` to skip the comparison stage entirely.

---

## Running a Stage Standalone

All commands should be run from the repo root with the virtual environment activated.

### Stage 1 — S3 Sync

Interactive:

```powershell
python payroll/stages/s3_sync/sync.py
```

With args:

```powershell
python payroll/stages/s3_sync/sync.py --start "Mar 9 2026" --end "Mar 22 2026"
```

Optional flags:

```text
--pos-data-root   Override default pos_data/ location
--s3-prefix       Override default S3 bucket prefix
--force-sync      Re-download even if local data already exists
```

### Stage 2 — Attendance

Interactive:

```powershell
python payroll/stages/attendance/attendance_all_stores.py
```

With args:

```powershell
python payroll/stages/attendance/attendance_all_stores.py --start "Mar 9 2026" --end "Mar 22 2026"
```

Optional flags:

```text
--pos-data-root   Override default pos_data/ location
--output-dir      Override default output directory
--timeclock-source end+1|end
```

Outputs written to `payroll/runs/<period>/output/`:

```text
Employee_Hours_Summary.json
Employee_Total_Hours.json
```

What this stage does:

- Reads start-folder spillover candidates, then reads main `Employee_Time_Clock.txt` rows from either the end+1 folder or the pay period end folder
- Clips timeclock entries that spill across the pay period boundaries
- Maps Employee_ID and Store_ID to their human-readable numbers
- Excludes internal/non-payroll stores
- Groups hours by store and employee
- Outputs per-store hours summary and per-employee totals

### Stage 3 — Hours

Interactive:

```powershell
python payroll/stages/hours/main.py
```

With args:

```powershell
python payroll/stages/hours/main.py --start "Mar 9 2026" --end "Mar 22 2026"
```

Optional flags:

```text
--input-dir    Directory containing Employee_Hours_Summary.json (default: payroll/runs/<period>/output)
--output-dir   Output directory (default: payroll/runs/<period>/output)
```

Outputs written to `payroll/runs/<period>/output/`:

```text
processed_employee_data.json
store_hours_report.json
```

What this stage does:

- Reads `Employee_Hours_Summary.json` from the output of Stage 2
- Splits pay period into Week 1 and Week 2 based on start and end dates
- Calculates regular hours (up to 40) and overtime for each week per employee
- Handles employees working across multiple stores — tracks cumulative hours before applying OT
- Splits timeclock entries that cross the Week 1 / Week 2 boundary
- Outputs per-employee breakdown by store and per-store totals

### Stage 4 — Tips

Interactive:

```powershell
python payroll/stages/tips/tips.py
```

With args:

```powershell
python payroll/stages/tips/tips.py --start "Mar 9 2026" --end "Mar 22 2026"
```

Optional flags:

```text
--pos-data-root   Override default pos_data/ location
--output-dir      Override default output directory
```

Output written to `payroll/runs/<period>/output/`:

```text
tips_summary.json
```

What this stage does:

- Processes every day in the pay period from `pos_data/`
- For each day: reads `Sales_Ticket.txt`, matches tickets in `Payment.txt` for paid tips, adds Payins from `Store_Transactions.txt`
- Maps Store_ID to Store_Number using `Store.txt`
- Outputs per-store tips broken down by date (format: `Mar-09-2026`) plus a running total
- The extra end+1 day folder is excluded — that folder is for timeclocks only

### Stage 5 — Generate CSV

Interactive:

```powershell
python payroll/stages/generate/generate.py
```

With args:

```powershell
python payroll/stages/generate/generate.py --start "Mar 9 2026" --end "Mar 22 2026"
```

Optional flags:

```text
--pos-data-root   Override default pos_data/ location
--input-dir       Directory containing processed_employee_data.json and tips_summary.json
--output-dir      Override default output directory
```

Output written to `payroll/runs/<period>/output/`:

```text
payroll_report.csv
```

What this stage does:

- Reads `processed_employee_data.json` (from Stage 3) and `tips_summary.json` (from Stage 4)
- Loads employee names from `Employee.txt` in `pos_data/`
- Sums regular and overtime hours per employee across both weeks
- Computes tip rate per store: total tips / total hours worked
- Calculates coded amount (tip payout) per employee based on their hours
- Outputs a CSV with one row per employee per store

### Stage 6 — Comparison

Interactive:

```powershell
python payroll/stages/comparison/main.py
```

With args:

```powershell
python payroll/stages/comparison/main.py --start "Mar 9 2026" --end "Mar 22 2026"
```

Optional flags:

```text
--generated-csv   Path to payroll_report.csv (default: payroll/runs/<period>/output/payroll_report.csv)
--webapp-csv      Path to Timesheet*.csv (default: scans input/ then repo root)
--output-dir      Override default output directory
```

Output written to `payroll/runs/<period>/output/`:

```text
Payroll_Comparison_<period>.xlsx
```

What this stage does:

- Reads `payroll_report.csv` (from Stage 5) and the webapp export `Timesheet*.csv`
- Filters stores by number, excluding internal/non-payroll stores
- Creates one Excel sheet per store comparing QA (generated) vs Century (webapp) data side by side
- Highlights employees only in one source (orange = only in generated, yellow = only in webapp)
- Flags mismatched regular or overtime hours in red
- Shows per-store totals for hours, tips, and tip rate for both sources

---

## Troubleshooting

### AWS CLI not found

Install AWS CLI, reopen the terminal, and verify with `aws --version`.

### Access denied on S3

Contact DevOps to confirm your IAM user has `s3:GetObject` and `s3:ListBucket` on `century-data`.

### No folders downloaded

Check that the date folders exist in S3:

```powershell
aws s3 ls s3://century-data/pos_data/
```

Dates must follow `YYYY-MM-DD` format in S3.
