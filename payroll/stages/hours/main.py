from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from payroll.stages.s3_sync.sync import (
    build_pay_period_key,
    parse_date_flexible,
)
from payroll.stages.hours.employee_store_utils import get_employee_store_data
from payroll.stages.hours.employee_processing import process_employee_data
from payroll.stages.hours.store_hours_report import generate_store_hours_report

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

INPUT_FILE = "Employee_Hours_Summary.json"
OUTPUT_PROCESSED = "processed_employee_data.json"
OUTPUT_STORE_REPORT = "store_hours_report.json"


@dataclass
class HoursConfig:
    start_date: date
    end_date: date
    input_dir: Path
    output_dir: Path


@dataclass
class HoursResult:
    processed_data_path: Path
    store_hours_report_path: Path


def run(config: HoursConfig) -> HoursResult:
    config.output_dir.mkdir(parents=True, exist_ok=True)

    input_path = config.input_dir / INPUT_FILE
    if not input_path.exists():
        raise FileNotFoundError(f"[hours] Input file not found: {input_path}")

    print(f"[hours] Loading {input_path}")
    with open(input_path, "r") as f:
        employee_hours_data = json.load(f)

    # Week boundaries derived from pay period dates
    week_1_start = config.start_date
    week_1_end = config.start_date + timedelta(days=6)
    week_2_start = config.start_date + timedelta(days=7)
    week_2_end = config.end_date

    print(f"[hours] Week 1: {week_1_start} to {week_1_end}")
    print(f"[hours] Week 2: {week_2_start} to {week_2_end}")

    single_store_employees, multi_store_employees = get_employee_store_data(employee_hours_data)
    print(f"[hours] Single-store employees: {sum(len(v) for v in single_store_employees.values())}")
    print(f"[hours] Multi-store employees : {len(multi_store_employees)}")

    processed_data = process_employee_data(
        employee_hours_data,
        single_store_employees,
        multi_store_employees,
        week_1_start,
        week_1_end,
        week_2_start,
        week_2_end,
    )

    store_hours_report = generate_store_hours_report(processed_data)

    processed_path = config.output_dir / OUTPUT_PROCESSED
    store_report_path = config.output_dir / OUTPUT_STORE_REPORT

    with open(processed_path, "w") as f:
        json.dump(processed_data, f, indent=4)

    with open(store_report_path, "w") as f:
        json.dump(store_hours_report, f, indent=4)

    print(f"[hours] Processed data   -> {processed_path}")
    print(f"[hours] Store hours report -> {store_report_path}")

    return HoursResult(
        processed_data_path=processed_path,
        store_hours_report_path=store_report_path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process employee hours for pay period.")
    parser.add_argument("--start", type=str, help="Pay period start (e.g. 'Mar 9 2026')")
    parser.add_argument("--end", type=str, help="Pay period end (e.g. 'Mar 22 2026')")
    parser.add_argument(
        "--input-dir",
        type=str,
        default=None,
        help="Directory containing Employee_Hours_Summary.json (default: payroll/runs/<period>/output)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: payroll/runs/<period>/output)",
    )
    return parser


def _prompt_date(label: str) -> date:
    while True:
        raw = input(label).strip()
        if not raw:
            print("Input required.")
            continue
        try:
            return parse_date_flexible(raw)
        except ValueError as exc:
            print(exc)


def main() -> None:
    args = build_parser().parse_args()

    start_date = parse_date_flexible(args.start) if args.start else _prompt_date("Start date: ")
    end_date = parse_date_flexible(args.end) if args.end else _prompt_date("End date: ")

    if start_date > end_date:
        raise SystemExit("Start date must be <= end date.")

    period_key = build_pay_period_key(start_date, end_date)
    default_dir = _REPO_ROOT / "payroll" / "runs" / period_key / "output"

    input_dir = Path(args.input_dir) if args.input_dir else default_dir
    output_dir = Path(args.output_dir) if args.output_dir else default_dir

    run(HoursConfig(
        start_date=start_date,
        end_date=end_date,
        input_dir=input_dir,
        output_dir=output_dir,
    ))


if __name__ == "__main__":
    main()