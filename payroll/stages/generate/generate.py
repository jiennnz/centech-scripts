from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

import chardet

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from payroll.stages.s3_sync.sync import (
    DEFAULT_POS_DATA_ROOT,
    build_pay_period_key,
    compute_sync_dates,
    fmt_iso,
    parse_date_flexible,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

INPUT_PROCESSED = "processed_employee_data.json"
INPUT_TIPS = "tips_summary.json"
OUTPUT_CSV = "payroll_report.csv"

CSV_COLUMNS = [
    "Store Number",
    "Employee Number",
    "Employee Name",
    "Regular Hours",
    "Overtime Hours",
    "Amount Code",
    "Coded Amount",
]


@dataclass
class GenerateConfig:
    start_date: date
    end_date: date
    pos_data_root: Path
    input_dir: Path
    output_dir: Path


@dataclass
class GenerateResult:
    payroll_csv_path: Path


def _detect_encoding(file_path: Path) -> str:
    with open(file_path, "rb") as f:
        return chardet.detect(f.read(10000))["encoding"] or "utf-8"


def _load_employee_name_mapping(pos_data_root: Path, sync_dates: list) -> Dict[str, str]:
    """
    Reads Employee.txt from the first available date folder.
    Maps Employee_Number (or Employee_ID as fallback) to full name.
    """
    employee_map = {}

    for d in sync_dates:
        emp_file = pos_data_root / fmt_iso(d) / "Employee.txt"
        if not emp_file.exists():
            continue

        encoding = _detect_encoding(emp_file)
        print(f"[generate] Loading employee names from {emp_file} (encoding: {encoding})")

        with open(emp_file, "r", encoding=encoding, errors="replace") as f:
            headers = f.readline().strip().split("|")

            if "Employee_ID" not in headers or "First_Name" not in headers:
                continue

            emp_id_idx = headers.index("Employee_ID")
            emp_num_idx = headers.index("Employee_Number") if "Employee_Number" in headers else None
            first_idx = headers.index("First_Name")
            middle_idx = headers.index("Middle_Name") if "Middle_Name" in headers else None
            last_idx = headers.index("Last_Name")

            for line in f:
                values = line.strip().split("|")
                required = [emp_id_idx, first_idx, last_idx]
                if emp_num_idx is not None:
                    required.append(emp_num_idx)
                if middle_idx is not None:
                    required.append(middle_idx)

                if len(values) <= max(required):
                    continue

                emp_id = values[emp_id_idx].strip()
                emp_num = values[emp_num_idx].strip() if emp_num_idx is not None else ""
                first = values[first_idx].strip()
                middle = values[middle_idx].strip() if middle_idx is not None else ""
                last = values[last_idx].strip()

                full_name = " ".join(p for p in [first, middle, last] if p)

                if emp_num:
                    employee_map[emp_num] = full_name
                else:
                    employee_map[emp_id] = full_name

        # Stop after first successful file — same data across all folders
        break

    print(f"[generate] {len(employee_map)} employee names loaded.")
    return employee_map


def _extract_employee_data(
    json_data: Dict,
    employee_mapping: Dict[str, str],
) -> Tuple[List[Dict], Dict[str, float]]:
    extracted = []
    store_hours = {}

    for store_number in sorted(json_data.keys(), key=lambda x: int(x) if x.strip().isdigit() else 0):
        employees = json_data[store_number]
        total_store_hours = 0.0

        valid_employees = []
        for emp_num in employees.keys():
            stripped = str(emp_num).strip()
            if stripped.isdigit():
                valid_employees.append((int(stripped), emp_num))
            else:
                valid_employees.append((0, emp_num))
                print(f"[generate] Invalid employee number in store {store_number}: '{emp_num}'")

        valid_employees.sort(key=lambda x: x[0])

        for numeric_emp_num, employee_number in valid_employees:
            weeks = employees[employee_number]
            total_reg = round(sum(w.get("Regular_Hours", 0) for w in weeks.values()), 2)
            total_ot = round(sum(w.get("Overtime_Hours", 0) for w in weeks.values()), 2)
            total_store_hours += total_reg + total_ot

            employee_name = employee_mapping.get(str(employee_number).strip(), "Unknown")

            extracted.append({
                "Store Number": int(store_number) if str(store_number).strip().isdigit() else 0,
                "Employee Number": numeric_emp_num,
                "Employee Name": employee_name,
                "Regular Hours": total_reg,
                "Overtime Hours": total_ot,
                "Amount Code": "Tips",
                "Coded Amount": "$0.00",
            })

        store_hours[store_number] = total_store_hours

    return extracted, store_hours


def _compute_coded_amounts(
    data: List[Dict],
    store_hours: Dict[str, float],
    tip_summary: Dict,
) -> None:
    for entry in data:
        store_number = str(entry["Store Number"])
        if store_number in tip_summary and store_number in store_hours:
            tip_total = tip_summary[store_number].get("total", 0)
            total_hours = store_hours[store_number]
            if total_hours > 0:
                tip_rate = tip_total / total_hours
                coded_amount = (entry["Regular Hours"] + entry["Overtime Hours"]) * tip_rate
                entry["Coded Amount"] = f"${coded_amount:.2f}"


def _write_csv(output_path: Path, data: List[Dict]) -> None:
    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(data)


def run(config: GenerateConfig) -> GenerateResult:
    config.output_dir.mkdir(parents=True, exist_ok=True)

    processed_path = config.input_dir / INPUT_PROCESSED
    tips_path = config.input_dir / INPUT_TIPS

    if not processed_path.exists():
        raise FileNotFoundError(f"[generate] Missing input: {processed_path}")
    if not tips_path.exists():
        raise FileNotFoundError(f"[generate] Missing input: {tips_path}")

    print(f"[generate] Loading {processed_path.name}")
    with open(processed_path, "r") as f:
        json_data = json.load(f)

    print(f"[generate] Loading {tips_path.name}")
    with open(tips_path, "r") as f:
        tip_summary = json.load(f)

    # Reverse so extra day folder (most recent) is checked first for employee name mapping
    sync_dates = list(reversed(compute_sync_dates(config.start_date, config.end_date)))
    employee_mapping = _load_employee_name_mapping(config.pos_data_root, sync_dates)

    data, store_hours = _extract_employee_data(json_data, employee_mapping)
    _compute_coded_amounts(data, store_hours, tip_summary)

    output_path = config.output_dir / OUTPUT_CSV
    _write_csv(output_path, data)

    print(f"[generate] Payroll CSV -> {output_path}")
    return GenerateResult(payroll_csv_path=output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate payroll CSV from processed hours and tips.")
    parser.add_argument("--start", type=str, help="Pay period start (e.g. 'Mar 9 2026')")
    parser.add_argument("--end", type=str, help="Pay period end (e.g. 'Mar 22 2026')")
    parser.add_argument("--pos-data-root", type=str, default=DEFAULT_POS_DATA_ROOT)
    parser.add_argument("--input-dir", type=str, default=None,
        help="Directory containing processed_employee_data.json and tips_summary.json")
    parser.add_argument("--output-dir", type=str, default=None,
        help="Output directory (default: payroll/runs/<period>/output)")
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

    run(GenerateConfig(
        start_date=start_date,
        end_date=end_date,
        pos_data_root=Path(args.pos_data_root),
        input_dir=input_dir,
        output_dir=output_dir,
    ))


if __name__ == "__main__":
    main()