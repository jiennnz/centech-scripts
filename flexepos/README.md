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

Run commands from the repository root.

```powershell
npm --prefix flexepos run financial -- `
  --start 2026-06-01 `
  --end 2026-06-30 `
  --org century `
  --mode headless
```

For example, to scrape July 1 through July 2:

```powershell
npm --prefix flexepos run financial -- --start 2026-07-01 --end 2026-07-02 --org century --mode headed
```

The start and end dates are inclusive and must use `YYYY-MM-DD`.

`--mode` accepts `headed` (the default) or `headless`. Headless mode uses the
saved session under `flexepos/.auth/`. If that session is absent or expired, run
once with `--mode headed`, log in in the browser window, and complete MFA.
Credentials are not read or stored by the script. Session state is ignored by Git.

After login, the scraper normally opens **Corporate Reports > CSD Daily Sales**.
If that dropdown or report link is unavailable, it automatically falls back to:

```text
https://fms.flexepos.com/FlexeposWeb/reports/netsuite.seam?cid=29099
```

The scraper then enters each store and date and submits the CSD report. After
submission, FlexePOS may normalize the page URL to `reports/netsuite.seam`; this
is expected.

Century stores come from
`financial/sales_export_comparison/rules/century.yaml`. Use `--stores 2006,2016`
for a limited validation run.

```powershell
npm --prefix flexepos run financial -- --start 2026-07-02 --end 2026-07-02 --org century --stores 2006,2016 --mode headed
```

Outputs are written to:

```text
flexepos/runs/<start>_<end>/<org>/financial/
  csd_aggregates.jsonl
  scraped_data_flexe.csv
  export_manifest.csv
```

Completed store/date records are skipped on rerun. Stores that failed can
therefore be retried without repeating successful requests.

Use `export_manifest.csv` to check each store/date result:

- `success`: scraped during the current run
- `skipped`: already present in `csd_aggregates.jsonl`
- `failed`: inspect the `Error` column, then rerun the same command

If a headed run times out after login, leave the browser open until FlexePOS
finishes loading and the Logout link appears. If a saved session has expired,
run in headed mode again to refresh `flexepos/.auth/storage-state.json`.

`scraped_data_flexe.csv` uses the same schema as the financial QA verifier:

```text
Date,Class,Transaction Category,Debit,Credit
```
