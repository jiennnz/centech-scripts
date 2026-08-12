# FlexePOS Command Guide

Read this file before generating or running any FlexePOS scrape or merge command.

## Working Directory

Run every command from the repository root:

```text
C:\Users\hpLap\Documents\Work\CenTech\centech-scripts
```

Commands use `npm --prefix flexepos`. The royalties runner resolves its two path
arguments from different locations:

- Auth states are resolved from the repository root, so use `flexepos/.auth/session-N.json`.
- Output directories are resolved from the npm package directory, so use `runs/...`.

Do not use `.auth/session-N.json`; that points to an auth folder at the repository
root. Do not use `flexepos/runs/...`; that creates `flexepos/flexepos/runs/...`.

Never add a second `flexepos` prefix while already working inside the
`flexepos` directory. The supported workflow is to return to the repository root
and run the commands shown below.

## Daily Sales Scrape

Sales data is one day behind. Use today's date for `--run-date` and yesterday's
date as the final range date.

Use one auth session per batch. Example with four batches:

```powershell
npm --prefix flexepos run financial:batches -- --run-date YYYY-MM-DD --sessions 4 --ranges START1:END1,START2:END2,START3:END3,START4:END4 --org century --mode headless
```

Batch output belongs under:

```text
flexepos/runs/RUN-DATE/financial_batches/
```

## Merge Sales Batches

Merge the requested range from the batches belonging to the specified run date:

```powershell
npm --prefix flexepos run financial:merge -- --run-date YYYY-MM-DD --start YYYY-MM-DD --end YYYY-MM-DD --org century
```

For the recurring reports, usually generate both ranges:

```powershell
npm --prefix flexepos run financial:merge -- --run-date RUN-DATE --start 2026-06-29 --end YESTERDAY --org century
npm --prefix flexepos run financial:merge -- --run-date RUN-DATE --start 2026-07-01 --end YESTERDAY --org century
```

## Royalties Scrape

Use session 4 unless the user requests another auth state:

```powershell
npm --prefix flexepos run royalties -- --start START-DATE --end END-DATE --org century --mode headless --auth-state flexepos/.auth/session-4.json --output-dir runs/RUN-DATE/START-DATE_END-DATE/century/royalties
```

Example for the July 21 run covering June 29 through July 20:

```powershell
npm --prefix flexepos run royalties -- --start 2026-06-29 --end 2026-07-20 --org century --mode headless --auth-state flexepos/.auth/session-4.json --output-dir runs/2026-07-21/2026-06-29_2026-07-20/century/royalties
```

Expected output:

```text
flexepos/runs/RUN-DATE/START-DATE_END-DATE/century/royalties/client_royalties.csv
```

## Payroll Scrape

Use session 4 unless the user requests another auth state. The payroll runner always
checks `Calculate Overtime` before submitting:

```powershell
npm --prefix flexepos run payroll -- --store STORE --start START-DATE --end END-DATE --mode headless --auth-state flexepos/.auth/session-4.json --output-dir runs/RUN-DATE/START-DATE_END-DATE/payroll
```

The payroll command prints authentication, payroll-summary, per-employee
timeclock, aggregate timeclock, and total durations. It also writes
`payroll_benchmark.json` to the output directory so timings from multiple runs
can be compared later. Per-employee `durationMs` values are included in
`employee_timeclocks.json`.

To scrape every Century store with two concurrent local sessions, a live
progress bar, per-store benchmarks, and an overall benchmark, run:

```powershell
npm --prefix flexepos run payroll:all -- 2026-07-27 2026-08-09
```

An optional third argument overrides the run date; otherwise it defaults to
today.

## Command Checklist

Before returning a command, verify:

1. The command is intended to run from the repository root.
2. Sales ends on yesterday's date unless the user specifies otherwise.
3. `--run-date` is today's date for daily work.
4. Auth paths start with `flexepos/.auth/`.
5. Royalties output paths start with `runs/`, without a `flexepos/` prefix.
6. The output range folder exactly matches `START-DATE_END-DATE`.
7. Royalties defaults to `session-4.json`.
