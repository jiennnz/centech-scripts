# centech-scripts

Local Streamlit app for **data validation**: payroll and financial. Data is pulled from AWS S3 (`pos_data/` date folders with TXT files), processed locally, and compared to system exports (Excel/CSV reports).

## What we have so far

### App

- **Streamlit UI** (`app.py`) with three tabs:
  - **Payroll** — Payroll validation pipeline (dates, run type). Pipeline steps not yet wired.
  - **Financial** — Financial validation pipeline (dates). Pipeline steps not yet wired.
  - **Data** — Manual S3 sync: pick start/end date and run sync for that range.

### S3 sync (`modules/s3_sync/`)

- **Date-range sync** — Syncs only the selected range (start date through end date). Does not sync the day after; the timeclock parser will request that separately when needed.
- **Sync only when needed** — Only syncs folders that are missing or empty. If all folders for the range already have data, sync is skipped (no `aws s3 sync` runs).
- **No empty folders** — If a synced folder has no files, it is removed and a log message is written (e.g. “No data for YYYY-MM-DD, folder not kept”).
- **Day-after helper** — `ensure_day_after_folder(end_date)` for the timeclock parser: syncs the day after `end_date` only if that folder is missing or empty.

### Config (`config.py`)

- S3: `S3_BUCKET`, `S3_PREFIX`, `POS_DATA_DIR`
- `PAYROLL_EXCLUDED_STORES` (set)
- `FINANCIAL_EXCLUDED_STORES` (TODO)

### Not yet built

- Payroll: timeclock parser, hours calculator, tips calculator, CSV generator, comparison (our CSV vs system)
- Financial: data parser, report generator, comparison
- Wiring of pipeline steps and download buttons in the UI

## Running locally

```bash
streamlit run app.py
```

Ensure AWS CLI is configured (`aws configure`) so S3 sync can pull data.

## Repo layout

- `app.py` — Streamlit entrypoint  
- `config.py` — S3 and excluded-store config  
- `ui/` — Payroll, Financial, Data tabs  
- `modules/s3_sync/` — S3 sync by date range  
- `payroll/`, `financial/` — Pipeline packages (to be filled)  
- `input/`, `output/`, `pos_data/` — Data dirs (`pos_data/` and `output/` in `.gitignore`)

See `build.md` for the full build order and next steps.
