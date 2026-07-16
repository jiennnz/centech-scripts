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

By default, the scraper reads and refreshes
`flexepos/.auth/storage-state.json`. Use `--auth-state` to keep a separate saved
Flexe session for a parallel terminal without touching the default session:

```powershell
npm --prefix flexepos run financial -- --start 2026-07-06 --end 2026-07-06 --org century --stores 2006 --mode headed --auth-state flexepos/.auth/session2.json --output-dir flexepos/runs/auth_test/session2
```

After logging in once with the separate auth-state file, use it in headless mode
with a separate output directory:

```powershell
npm --prefix flexepos run financial -- --start 2026-07-06 --end 2026-07-09 --org century --mode headless --auth-state flexepos/.auth/session2.json --output-dir flexepos/runs/2026-07-06_2026-07-09/century/financial_session2
```

Do not run parallel scrapes against the same auth-state file. Flexe appears to
store report state server-side in the login session, so concurrent runs sharing
one session can read each other's CSD report result.

The default navigation timeout is 20 seconds. Timeouts can still be overridden
when needed. Values are in milliseconds. For example, this sets a 15 second
action timeout and a 20 second navigation timeout:

```powershell
npm --prefix flexepos run financial -- --start 2026-07-06 --end 2026-07-09 --org century --mode headless --timeout-ms 15000 --navigation-timeout-ms 20000
```

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

## Royalties run

The royalties scraper targets the Flexe/TQSR royalty review export and normalizes
it to the CSV shape consumed by `financial/royalties/run.py`. It submits each
configured store for the selected date range, then reads the result table:

```text
Store, Royalty Sales, Royalty, %, Advertising, %, Media, %, Days, State ID
```

Run commands from the repository root.

```powershell
npm --prefix flexepos run royalties -- `
  --start 2026-06-01 `
  --end 2026-06-30 `
  --org century `
  --mode headed
```

Headless mode uses the same saved Flexe session as the sales scraper:

```powershell
npm --prefix flexepos run royalties -- --start 2026-06-01 --end 2026-06-30 --org century --mode headless
```

The scraper looks for **Corporate Reports > Royalty Report**. If that dropdown
or link is unavailable, it automatically falls back to:

```text
https://fms.flexepos.com/FlexeposWeb/royalty.seam?cid=268311
```

If the report changes, pass a direct report URL or report cid:

```powershell
npm --prefix flexepos run royalties -- --start 2026-06-01 --end 2026-06-30 --org century --report-cid 268311 --mode headed
```

If you already downloaded the Flexe royalty CSV, normalize it without opening a
browser:

```powershell
npm --prefix flexepos run royalties -- `
  --start 2026-06-01 `
  --end 2026-06-30 `
  --org century `
  --source-csv "ERPRoyalityReviewReport-2026-07-07T15-12-28.csv"
```

Outputs are written to:

```text
flexepos/runs/<start>_<end>/<org>/royalties/
  royalty_aggregates.jsonl
  client_royalties.csv
  export_manifest.csv
```

`client_royalties.csv` can be used directly by the royalties comparison:

```powershell
python financial/royalties/run.py --start 2026-06-01 --end 2026-06-30 --org century --client "flexepos/runs/2026-06-01_2026-06-30/century/royalties/client_royalties.csv"
```

Use `--stores 2006,2016` for a limited validation run:

```powershell
npm --prefix flexepos run royalties -- --start 2026-06-01 --end 2026-06-07 --org century --stores 2006 --mode headed
```
