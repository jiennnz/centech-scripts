# Payroll Automation Options

This document summarizes the practical options for automating payroll scraping
and payroll comparison when a payroll file is created on the website/Flexe.

## Goal

Automate this flow:

```text
Payroll file is created on website/Flexe
        |
        v
Detect or scrape the new payroll export
        |
        v
Download Timesheet/Tips files
        |
        v
Run QA payroll generation and comparison
        |
        v
Save output and notify QA/PM
```

Current comparison output:

```text
payroll/runs/<period>/output/Payroll_Comparison_<period>.xlsx
```

## Key Constraint

For faster scraping, the date range can be divided into batches, for example:

```text
Jul 01-05
Jul 06-10
Jul 11-15
Jul 16-20
Jul 21-25
Jul 26-30
```

However, if Flexe auth/session cannot be shared, parallelism is limited by the
number of independent approved auth sessions.

```text
1 auth/session = 1 active scraper worker
```

So:

```text
1 Flexe login  -> 1 batch at a time
2 Flexe logins -> 2 batches in parallel
3 Flexe logins -> 3 batches in parallel
```

Multiple auth profiles should mean approved automation/service identities, not
random human accounts.

## Option 1: Laravel Queue Worker

Laravel owns orchestration and tracking. A Laravel queued job runs or calls a
scraper script.

```text
Laravel command/job
        |
        v
Create scrape run and 5-day batches
        |
        v
Queue ScrapeFlexePayrollBatch jobs
        |
        v
Worker runs Playwright scraper
        |
        v
Files saved to S3/local storage
        |
        v
Run payroll comparison
```

### Pros

- Cheapest if the Laravel infrastructure already exists.
- Fastest to integrate with the current backend.
- Laravel can own status pages, retries, audit records, and notifications.
- Simple to trigger from the website when payroll is created.

### Cons

- Browser scraping can consume CPU/RAM.
- Must isolate workers so scraping does not affect normal web traffic.
- Scaling parallel batches depends on available worker capacity and auth
  profiles.

### Best Use

Good first implementation if the team wants the lowest cost and fastest path.

## Option 2: Laravel + AWS ECS/Fargate Scraper Workers

Laravel controls the workflow, but scraping runs in containerized workers on
AWS Fargate.

```text
Laravel creates scrape run
        |
        v
Laravel queues batches in DB/SQS
        |
        v
Fargate workers run Playwright
        |
        v
Workers upload files to S3
        |
        v
Laravel triggers payroll comparison and notification
```

### Pros

- Better isolation than running browser scraping on the Laravel server.
- Good fit for Playwright/Chrome.
- Workers run only when needed.
- Easier to scale parallel workers by auth profile.
- Cleaner production setup for long or flaky scraping jobs.

### Cons

- More AWS setup: ECS, ECR, task definitions, IAM, S3, logs.
- Usually costs more per minute than Lambda.
- Slightly slower to implement than using an existing Laravel worker.

### Best Use

Best production option if reliability, isolation, and scaling matter.

## Option 3: AWS Lambda Scraper

Lambda runs the scraper directly.

```text
Trigger
        |
        v
Lambda starts browser scrape
        |
        v
Download file
        |
        v
Save to S3
        |
        v
Trigger comparison
```

### Pros

- Cheap for short jobs.
- No server to manage.
- Good for small glue tasks and notifications.

### Cons

- Browser scraping with Playwright/Chrome can be heavy.
- Runtime, package size, filesystem, and cold start limits can become problems.
- Not ideal for long-running July 1-30 scraping.
- Session handling can be awkward.

### Best Use

Good for light tasks:

```text
start run
check status
move files
send notifications
trigger comparison
```

Not recommended as the main scraper unless a proof of concept confirms each
batch finishes reliably.

## Option 4: GitHub Actions

GitHub Actions runs the payroll comparison or scraper on a schedule or manual
trigger.

```text
workflow_dispatch or schedule
        |
        v
Run scraper/comparison
        |
        v
Upload artifact or save to S3
```

### Pros

- Simple for QA automation.
- Easy manual runs with start/end inputs.
- Good for generating comparison files on demand.

### Cons

- Not ideal for event-driven production scraping.
- Secrets and payroll artifacts need careful access control.
- Browser scraping reliability depends on runner environment.
- GitHub artifact retention/access may not fit payroll data requirements.

### Best Use

Good for QA-side automation or manual reruns, not the main production trigger.

## Trigger Options

### Best: Website Event or Webhook

If the website can emit an event when payroll is created:

```text
Payroll file created
        |
        v
Webhook to Laravel
        |
        v
Create scrape/comparison run
```

This is the cleanest trigger.

### Good: File Lands in S3

If the website can save/export the file to S3:

```text
S3 object created
        |
        v
Trigger Lambda/Laravel/SQS
        |
        v
Run comparison
```

This avoids scraping entirely for the trigger.

### Fallback: Scheduled Checker

If there is no webhook/API/S3 event:

```text
Every N minutes
        |
        v
Check Flexe/website for new payroll file
        |
        v
Download only if new
```

This requires state tracking to avoid duplicate runs.

## Required Tracking

Use a database table or equivalent state store:

```text
payroll_scrape_runs
payroll_scrape_batches
payroll_scrape_files
```

Track at least:

```text
org
pay_period_start
pay_period_end
batch_start
batch_end
auth_profile_id
source_file_name
source_file_hash
status
attempt_count
started_at
completed_at
error_message
output_path
```

This makes the process idempotent:

```text
Same file hash seen twice = do not rerun unless forced
Failed batch = retry only that batch
Completed batch = skip
```

## Auth Design

Recommended auth layers:

```text
1. Reuse stored browser session/cookies
2. Automated login with approved automation account
3. Manual re-auth when MFA/captcha/device challenge appears
```

Avoid depending on many human accounts. If parallel scraping is required, use
approved dedicated auth profiles.

## Cost Summary

From cheapest to most production-ready:

```text
1. Existing Laravel worker
   Lowest added cost if infrastructure already exists.

2. AWS Lambda
   Cheap for short tasks, but risky for heavy browser scraping.

3. AWS ECS/Fargate
   Better production scraper isolation; pay only while workers run.

4. Always-on dedicated worker/EC2
   Simple but can be more expensive if idle most of the time.
```

## Recommendation

Start with:

```text
Laravel orchestrates the workflow
        |
        v
Scraper runs as a separate worker process
        |
        v
Files and outputs are stored in S3
        |
        v
Laravel tracks run/batch/file status
```

For the first version, use an existing Laravel queue worker if cost and speed
matter most.

For production, move the scraper worker to ECS/Fargate:

```text
Laravel + SQS/DB queue + Fargate Playwright workers + S3
```

Use Lambda only for light glue tasks, not as the primary browser scraper unless
testing proves the scrape is short and reliable.
