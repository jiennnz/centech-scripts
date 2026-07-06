# AWS Sales and Payroll Automation Plan

## 1. What We Are Building

We will automate the existing sales and payroll comparison processes and run
them in AWS.

The system will initially support two organizations:

| Organization key | Stores |
| --- | ---: |
| `century` | 87 |
| `century_austin` | 14 |

Each organization will run separately. A failure for one organization must not
overwrite or stop the completed work for another organization.

The automation will:

- Run without someone opening a terminal.
- Wait for backend-generated Flexe and CenTech exports in S3.
- Wait for required POS data in S3.
- Run the existing comparison code.
- Save inputs and outputs in S3.
- Keep previous runs for auditing.
- Send success and failure notifications by email.
- Support manual reruns and historical backfills.

## 2. High-Level Design

```text
AWS schedule starts the workflow
              |
              v
 Wait for Flexe, CenTech, and POS
       deliveries in S3
              |
              v
    Run the comparison scripts
              |
              v
       Save reports in S3
              |
              v
          Send an email
```

This is not one large Lambda function. AWS will coordinate several smaller
services, each with a specific responsibility.

## 3. Daily Sales Process

### Schedule and dates

The sales workflow will start every day at 2:00 PM Philippine time using the
`Asia/Manila` time zone.

The newest business date is always one day behind:

```text
Run on July 2  -> newest business date is July 1
Run on July 3  -> newest business date is July 2
```

The CenTech export grows as the period progresses:

```text
July 2 run -> export July 1 through July 1
July 3 run -> export July 1 through July 2
July 8 run -> export July 1 through July 7
```

The exact period boundary must be configurable. The initial assumption is that
sales reset at the beginning of each month.

### Step 1: Start an organization run

For each enabled organization:

1. Calculate the run date, target date, and period start.
2. Create a unique run identifier.
3. Check whether that organization and target date already completed.
4. Skip duplicate work unless this is an intentional rerun.

Example run identifiers:

```text
SALES#century#2026-07-02
SALES#century_austin#2026-07-02
```

### Step 2: Wait for backend exports and POS data

The backend owns browser scraping, authentication, retries, and export
generation for both Flexe and CenTech. This repository does not scrape either
website as part of the AWS workflow.

The workflow waits for the Flexe export, the cumulative CenTech export, and the
target POS delivery to be complete in S3.

The preferred signal is a completion file:

```text
pos_data/2026-07-02/_SUCCESS
automation/sales/raw/flexe/org=century/business_date=2026-07-02/_SUCCESS
automation/sales/raw/centech/org=century/target_date=2026-07-02/_SUCCESS
```

The POS uploader should create this only after all files for the date finish
uploading.

If it does not exist:

```text
Wait 10 minutes -> check again
```

The workflow will stop and alert after a configured deadline.

If the uploader cannot create `_SUCCESS`, the application must verify the
expected files and make sure their sizes remain stable before continuing.

Each backend export must include an immutable original file and a manifest with
the organization, requested dates, store coverage, schema version, checksum,
generation time, and source observation time. `_SUCCESS` is written only after
the export and manifest are complete.

### Step 3: Compare the data

The Python comparison container will:

1. Download the Flexe and CenTech exports from S3.
2. Load the correct organization rules.
3. Run the existing sales comparison stages.
4. Generate the XLSX comparison workbook.
5. Generate aggregate audit CSVs.
6. Upload the outputs and a run manifest to S3.

The run manifest will record:

- Organization
- Date range
- Source file locations
- Source checksums or S3 versions
- Expected and completed store counts
- Start and completion times
- Final status

### Step 4: Send an email

The workflow will send an operational email containing:

- Organization
- Date range
- Success or failure
- Aggregate discrepancy summary
- Output location
- Link to the AWS execution logs

AWS SNS will deliver these emails. Every recipient or distribution list must
confirm its SNS subscription before AWS can send notifications to it.

Emails must not include customer, employee, ticket, payment, or
transaction identifiers.

## 4. Payroll Process

Payroll will use a separate workflow because it runs by pay period rather than
every day.

```text
Pay-period schedule
        |
        v
Wait for all required POS folders
        |
        v
Export CenTech Timesheet and Tips
        |
        v
Run attendance, hours, tips, and payroll generation
        |
        v
Generate payroll comparison workbook
        |
        v
Save outputs and notify
```

For each organization, payroll configuration must specify:

- Included stores
- Pay-period start and end rules
- Whether time clocks come from `end` or `end + 1`
- Tips source-date rules
- CenTech account

The current payroll runner is interactive and is not organization-aware. It
must be refactored before deployment.

## 5. Technologies Needed

### Existing application technologies

| Technology | Use |
| --- | --- |
| Python | Runs sales and payroll processing |
| pandas | Reads, transforms, and compares tabular data |
| openpyxl/XlsxWriter | Creates Excel comparison workbooks |
| YAML | Stores organization and calculation configuration |

### Docker technologies

| Technology | Use |
| --- | --- |
| Dockerfile | Recipe for building a runnable application package |
| Docker image | Packaged code, runtime, and dependencies |
| Docker container | A running instance of an image |
| `.dockerignore` | Prevents secrets, raw data, and unnecessary files from entering images |

The AWS workflow needs one application image:

```text
Comparison image
├── Python
├── pandas
├── Excel libraries
└── Sales and payroll code
```

### AWS technologies

| AWS service | Why it is needed |
| --- | --- |
| EventBridge Scheduler | Starts sales at 2:00 PM PHT and starts payroll on its schedule |
| Step Functions Standard | Controls the order of work, waiting, retries, and failures |
| ECS Fargate | Runs Docker containers without maintaining a server |
| ECR | Stores Docker images for Fargate |
| Lambda | Runs short tasks such as date calculation and S3 readiness checks |
| S3 | Stores POS files, raw exports, audit files, and final reports |
| DynamoDB | Stores job status and prevents duplicate runs |
| Secrets Manager | Stores approved credentials and authentication material |
| CloudWatch | Stores logs, metrics, dashboards, and alarms |
| SNS | Sends success and failure emails through confirmed email subscriptions |
| IAM | Gives each AWS component only the permissions it needs |
| KMS | Encrypts sensitive files and secrets |

### Deployment technologies

DevOps should select the organization's standard infrastructure tool:

- Terraform
- AWS CDK
- CloudFormation
- AWS SAM

A deployment pipeline, such as GitHub Actions or the company's existing CI/CD
system, will:

1. Test the code.
2. Build Docker images.
3. Upload images to ECR.
4. Deploy infrastructure changes.
5. Deploy the new application version.

## 6. How Docker Fits Into the System

The Dockerfile is a machine-readable recipe. It does not replace the repository.
It tells Docker which repository files to copy and what to install.

Example:

```dockerfile
FROM node:20

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY src/ ./src/

CMD ["node", "src/financial/run.js"]
```

The build process is:

```text
Repository files + Dockerfile
              |
              v
         Docker image
              |
              v
      Upload image to ECR
              |
              v
     Fargate runs a container
```

The image includes code and dependencies, but it must not contain:

- Passwords
- `.env` files
- Raw POS data
- Generated reports

AWS provides secrets and data when the container starts.

## 7. S3 File Organization

Use separate paths for each organization, source, date, and observation.

```text
automation/
  sales/
    raw/
      flexe/
        org=century/
          business_date=2026-07-02/
            observed_at=2026-07-03T140000/
      centech/
        org=century/
          target_date=2026-07-02/
            observed_at=2026-07-03T150000/
    output/
      org=century/
        target_date=2026-07-02/
          comparison.xlsx
          run_manifest.json

  payroll/
    raw/
      org=century/
        period=2026-07-01_2026-07-15/
    output/
      org=century/
        period=2026-07-01_2026-07-15/
```

S3 versioning and encryption must be enabled. Previous evidence should not be
silently replaced.

## 8. Repository Work Required

### Backend delivery contract

- The backend uploads Flexe and CenTech exports, manifests, and `_SUCCESS`
  markers to the agreed S3 paths.
- Backend scraping and browser authentication are outside this repository.
- Deliveries are immutable; corrected or late data creates a new observation.
- The comparator validates dates, organization, schema, checksum, and expected
  store coverage before processing.

### Sales comparison

- Add a non-interactive cloud entry point.
- Remove confirmation prompts from automated execution.
- Accept explicit input and output paths.
- Return structured results.
- Upload outputs and manifests to S3.

### Payroll

- Add organization configuration and store filtering.
- Replace AWS CLI subprocess calls with the AWS SDK for Python.
- Remove terminal prompts and file-drop loops from automated execution.
- Accept explicit Timesheet and Tips paths.
- Separate calculation logic from local CLI behavior.

### Shared

- Add consistent logging.
- Add deterministic run identifiers.
- Add retry-safe behavior.
- Add unit and integration tests.
- Preserve the existing local/manual commands.

## 9. Authentication and Security

Website credentials, browser sessions, MFA, and CAPTCHA handling belong to the
backend scraping service and are not available to this comparison workflow.
The AWS job receives only approved S3 access for source exports, POS inputs,
and generated outputs.

## 10. Responsibilities

### Application development

Application developers will:

- Refactor sales and payroll into non-interactive jobs.
- Add organization support.
- Create Dockerfiles.
- Validate inputs and outputs.
- Create run manifests.
- Write automated tests.

### DevOps

DevOps will:

- Approve the AWS architecture.
- Select the AWS account and Region.
- Provision AWS resources.
- Configure IAM permissions and networking.
- Configure Secrets Manager and encryption.
- Create deployment pipelines.
- Configure logs, email alerts, and cost controls.
- Provide development and production environments.

### Shared decisions

Application development and DevOps must jointly decide:

- Lambda versus Fargate task boundaries
- S3 readiness mechanism
- Retry and timeout limits
- Email recipients and distribution lists
- Data retention
- Deployment and rollback process

## 11. Implementation Phases

### Phase 1: Confirm requirements

- Confirm the sales period boundary.
- Confirm payroll schedules for both organizations.
- Confirm required Flexe and CenTech reports.
- Confirm S3 completion behavior.
- Confirm the backend export manifest and completion-marker contract.
- Benchmark backend delivery and comparison durations.

### Phase 2: Make the repository automation-ready

- Implement and validate the backend-to-S3 input contract.
- Remove interactive behavior from cloud execution paths.
- Add organization-aware configuration.
- Add S3 adapters and run manifests.
- Add tests.

### Phase 3: Dockerize and test locally

- Create the comparison image.
- Run them locally with test inputs.
- Verify that secrets and operational data are excluded.
- Measure CPU, memory, storage, and execution time.

### Phase 4: Build AWS infrastructure

- Create ECR repositories.
- Create S3 locations and encryption.
- Create Secrets Manager entries.
- Create DynamoDB run-state storage.
- Deploy Fargate, Lambda, Step Functions, Scheduler, IAM, and monitoring.

### Phase 5: Shadow runs

- Run AWS automation alongside the existing manual process.
- Compare outputs for at least two sales weeks.
- Compare one complete payroll period.
- Fix differences before production approval.

### Phase 6: Production rollout

- Enable production schedules.
- Keep manual rerun and backfill commands.
- Document delivery-validation and failure-recovery procedures.

## 12. Completion Criteria

Sales is ready when:

- It starts at 2:00 PM Philippine time.
- It calculates the correct previous business date.
- Century and Austin run independently.
- Backend Flexe and CenTech exports pass manifest and coverage validation.
- Comparison starts only after Flexe, CenTech, and POS deliveries are complete.
- The comparison workbook and manifest are stored in S3.
- Duplicate schedules do not create duplicate successful runs.
- Failures produce safe, actionable emails.

Payroll is ready when:

- Pay periods are calculated correctly per organization.
- All required POS folders are ready.
- Timesheet and Tips exports are acquired automatically.
- Payroll outputs match an approved manual run.
- Reruns do not overwrite previous evidence.

## 13. Decisions Needed From DevOps

1. Which AWS account and Region should host the system?
2. Is Terraform, CDK, CloudFormation, or SAM the company standard?
3. Is Fargate approved for the Python comparison job?
4. What access can the automation receive to the existing POS S3 bucket?
5. Can every backend delivery create a manifest and `_SUCCESS` marker?
6. Which email addresses or distribution lists should receive alerts?
7. What data-retention and cost limits should be used?
8. Can separate development and production environments be provided?
