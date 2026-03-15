"""App configuration: S3, paths, and excluded stores."""

# S3 — matches: aws s3 sync s3://century-data/pos_data/2026-03-01 ./pos_data/2026-03-01
S3_BUCKET = "century-data"
S3_PREFIX = "pos_data"
POS_DATA_DIR = "pos_data"

PAYROLL_EXCLUDED_STORES = {
    4055, 5005, 13067, 13070, 13099, 13109,
    4028, 4041, 4062, 4064, 4071, 4078,
    4079, 5124, 10013, 10023, 37017, 37019, 4069,
}

FINANCIAL_EXCLUDED_STORES = {
    # TODO: add financial excluded stores
}
