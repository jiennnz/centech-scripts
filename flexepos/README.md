# FlexePOS Automation

Reusable Playwright automation for approved FlexePOS reporting. The first adapter
collects aggregate `CSD Daily Sales` values for Century stores and creates a CSV
compatible with the financial sales comparison pipeline.

## Setup

```powershell
cd flexepos
npm install
npx playwright install chromium
cd ..
```

## Financial CSD run

```powershell
npm --prefix flexepos run financial -- `
  --start 2026-06-01 `
  --end 2026-06-30 `
  --org century `
  --mode headless
```

`--mode` accepts `headed` (the default) or `headless`. Headless mode uses the
saved session under `flexepos/.auth/`. If that session is absent or expired, run
once with `--mode headed`, log in in the browser window, and complete MFA.
Credentials are not read or stored by the script. Session state is ignored by Git.

Century stores come from
`financial/sales_export_comparison/rules/century.yaml`. Use `--stores 2006,2016`
for a limited validation run.

Outputs are written to:

```text
flexepos/runs/<start>_<end>/<org>/financial/
  csd_aggregates.jsonl
  scraped_data_flexe.csv
  export_manifest.csv
```

Completed store/date records are skipped on rerun. Stores that failed can
therefore be retried without repeating successful requests.

`scraped_data_flexe.csv` uses the same schema as the financial QA verifier:

```text
Date,Class,Transaction Category,Debit,Credit
```
