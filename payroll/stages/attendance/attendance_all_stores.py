from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import chardet
import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

from payroll.stages.s3_sync.sync import (
    DEFAULT_POS_DATA_ROOT,
    build_pay_period_key,
    fmt_iso,
    parse_date_flexible,
)

EXCLUDED_STORE_NUMBERS = {
    4055,
    5005,
    13067,
    13070,
    13099,
    13109,
    4028,
    4041,
    4062,
    4064,
    4071,
    4078,
    4079,
    5124,
    10013,
    10023,
    37017,
    37019,
    4069,
    4089,
}

OUTPUT_HOURS_SUMMARY = "Employee_Hours_Summary.json"
OUTPUT_TOTAL_HOURS = "Employee_Total_Hours.json"
DT_FMT = "%Y-%m-%d %H:%M:%S"


@dataclass
class AttendanceConfig:
    start_date: date
    end_date: date
    pos_data_root: Path
    output_dir: Path
    use_end_plus_one_timeclock: bool = True
    timeclock_source_date: date | None = None
    timeclock_source_dates: tuple[date, ...] = ()


@dataclass
class AttendanceResult:
    hours_summary_path: Path
    total_hours_path: Path
    spillover_count: int


def detect_encoding(file_path: Path) -> str:
    with open(file_path, "rb") as f:
        return chardet.detect(f.read())["encoding"]


def load_employee_mapping(
    pos_data_root: Path, sync_dates: List[date]
) -> Dict[str, str]:
    for d in sync_dates:
        emp_file = pos_data_root / fmt_iso(d) / "Employee.txt"
        if emp_file.exists():
            enc = detect_encoding(emp_file)
            df = pd.read_csv(emp_file, delimiter="|", encoding=enc, dtype=str)
            df.columns = df.columns.str.strip()
            if "Employee_ID" in df.columns and "Employee_Number" in df.columns:
                df = df.dropna(subset=["Employee_ID", "Employee_Number"])
                df["Employee_ID"] = df["Employee_ID"].astype(str)
                df["Employee_Number"] = df["Employee_Number"].astype(str)
                df = df[df["Employee_Number"].str.strip() != ""]
                print(f"[attendance] Employee mapping loaded from {emp_file}")
                return df.set_index("Employee_ID")["Employee_Number"].to_dict()
    print("[attendance] Warning: No Employee.txt found in any date folder.")
    return {}


def load_store_mapping(pos_data_root: Path, sync_dates: List[date]) -> Dict[str, str]:
    for d in sync_dates:
        store_file = pos_data_root / fmt_iso(d) / "Store.txt"
        if store_file.exists():
            enc = detect_encoding(store_file)
            df = pd.read_csv(store_file, delimiter="|", encoding=enc, dtype=str)
            df.columns = df.columns.str.strip()
            if "Store_ID" in df.columns and "Store_Number" in df.columns:
                df = df.dropna(subset=["Store_ID", "Store_Number"])
                df["Store_ID"] = df["Store_ID"].astype(str)
                df["Store_Number"] = df["Store_Number"].astype(str)
                print(f"[attendance] Store mapping loaded from {store_file}")
                return df.set_index("Store_ID")["Store_Number"].to_dict()
    print("[attendance] Warning: No Store.txt found in any date folder.")
    return {}


def load_timeclock_rows(tc_path: Path) -> List[Dict]:
    with open(tc_path, "r") as f:
        lines = f.read().strip().split("\n")
    if len(lines) < 2:
        return []
    header = lines[0].split("|")
    return [dict(zip(header, line.split("|"))) for line in lines[1:]]


def calculate_hours(start_str: str, end_str: str) -> float:
    try:
        start_dt = datetime.strptime(start_str, DT_FMT)
        end_dt = datetime.strptime(end_str, DT_FMT)
        return round((end_dt - start_dt).total_seconds() / 3600, 2)
    except ValueError as e:
        print(f"[attendance] Error calculating hours: {e}")
        return 0.0


def filter_and_clip_rows(
    rows: List[Dict],
    period_start: datetime,
    period_end: datetime,
) -> Tuple[List[Dict], int]:
    """
    Keep only rows that overlap with the pay period.
    Clip Clock_In to period_start for left spillovers.
    Clip Clock_Out to period_end for right spillovers.
    """
    filtered = []
    spillover_count = 0

    for row in rows:
        start_str = row.get("Start", "").strip()
        end_str = row.get("End", "").strip()

        if not start_str or not end_str:
            continue

        try:
            start_dt = datetime.strptime(start_str, DT_FMT)
            end_dt = datetime.strptime(end_str, DT_FMT)
        except ValueError as e:
            print(f"[attendance] Skipping row, date parse error: {e}")
            continue

        # Fully outside pay period
        if end_dt <= period_start or start_dt > period_end:
            continue

        clipped = dict(row)

        # Left boundary: Clock_In before period start, Clock_Out inside
        if start_dt < period_start and end_dt > period_start:
            clipped["Start"] = period_start.strftime(DT_FMT)
            clipped["_spillover"] = "left"
            spillover_count += 1

        # Right boundary: Clock_In inside period, Clock_Out beyond period end
        elif start_dt <= period_end and end_dt > period_end:
            clipped["End"] = period_end.strftime(DT_FMT)
            clipped["_spillover"] = "right"
            spillover_count += 1

        filtered.append(clipped)

    return filtered, spillover_count


def run(config: AttendanceConfig) -> AttendanceResult:
    config.output_dir.mkdir(parents=True, exist_ok=True)

    period_start = datetime.combine(config.start_date, datetime.min.time())
    period_end = datetime.strptime(
        f"{config.end_date.strftime('%Y-%m-%d')} 23:59:59", DT_FMT
    )
    extra_day = config.end_date + timedelta(days=1)
    configured_source_dates = config.timeclock_source_dates
    if not configured_source_dates and config.timeclock_source_date is not None:
        configured_source_dates = (config.timeclock_source_date,)
    timeclock_source_dates = configured_source_dates or (
        extra_day if config.use_end_plus_one_timeclock else config.end_date,
    )

    # Use the selected timeclock source first for mappings.
    all_date_folders = [*timeclock_source_dates, config.start_date]
    employee_mapping = load_employee_mapping(config.pos_data_root, all_date_folders)
    store_mapping = load_store_mapping(config.pos_data_root, all_date_folders)
    print(
        f"[attendance] {len(employee_mapping)} employees, {len(store_mapping)} stores."
    )

    # Load timeclock rows from exactly two files
    all_rows: List[Dict] = []

    # 1) Start date folder — spillover candidates only (Clock_In before pay period start)
    start_tc = (
        config.pos_data_root / fmt_iso(config.start_date) / "Employee_Time_Clock.txt"
    )
    if start_tc.exists():
        rows = load_timeclock_rows(start_tc)
        spillover_candidates = [
            r
            for r in rows
            if r.get("Start", "").strip()
            and datetime.strptime(r["Start"].strip(), DT_FMT) < period_start
        ]
        print(
            f"[attendance] {len(spillover_candidates)} spillover candidate(s) from start folder ({fmt_iso(config.start_date)}) out of {len(rows)} rows"
        )
        all_rows.extend(spillover_candidates)
    else:
        print(f"[attendance] No timeclock at start folder: {start_tc}")

    # 2) Selected source folders - main timeclock data for the pay period
    for source_date in timeclock_source_dates:
        main_tc = (
            config.pos_data_root
            / fmt_iso(source_date)
            / "Employee_Time_Clock.txt"
        )
        if main_tc.exists():
            rows = load_timeclock_rows(main_tc)
            print(
                f"[attendance] {len(rows)} rows from source folder "
                f"({fmt_iso(source_date)})"
            )
            all_rows.extend(rows)
        else:
            print(f"[attendance] No timeclock at source folder: {main_tc}")

    # Later snapshots contain corrections to punches identified by Creation_Time.
    rows_by_key = {}
    for row in all_rows:
        creation_time = row.get("Creation_Time")
        if creation_time:
            key = (
                row.get("Store_ID"),
                row.get("Employee_ID"),
                creation_time,
            )
        else:
            key = (
                row.get("Store_ID"),
                row.get("Employee_ID"),
                row.get("Start"),
                row.get("End"),
            )
        rows_by_key[key] = row
    unique_rows = list(rows_by_key.values())
    print(
        f"[attendance] {len(unique_rows)} unique rows (from {len(all_rows)} total after dedup)."
    )

    # Filter to pay period and clip boundaries
    filtered_rows, spillover_count = filter_and_clip_rows(
        unique_rows, period_start, period_end
    )
    print(
        f"[attendance] {len(filtered_rows)} rows in pay period. {spillover_count} spillover(s) clipped."
    )

    # Collect date range metadata
    all_dates = [r["Start"] for r in filtered_rows if r.get("Start")] + [
        r["End"] for r in filtered_rows if r.get("End")
    ]
    parsed_dates = [datetime.strptime(d, DT_FMT) for d in all_dates]
    min_date = (
        min(parsed_dates).strftime(DT_FMT)
        if parsed_dates
        else period_start.strftime(DT_FMT)
    )
    max_date = (
        max(parsed_dates).strftime(DT_FMT)
        if parsed_dates
        else period_end.strftime(DT_FMT)
    )

    # Group by store and compute hours
    store_data: Dict[str, List] = defaultdict(list)

    for row in tqdm(filtered_rows, desc="[attendance] Processing rows"):
        store_id = row.get("Store_ID", "").strip()
        employee_id = row.get("Employee_ID", "").strip()
        start = row.get("Start", "").strip()
        end = row.get("End", "").strip()

        if not start or not end:
            continue

        employee_number = (
            employee_mapping.get(employee_id, employee_id).strip() or employee_id
        )
        store_number = store_mapping.get(store_id, store_id)

        try:
            if int(store_number) in EXCLUDED_STORE_NUMBERS:
                continue
        except ValueError:
            continue

        entry = {
            "Employee_Number": employee_number,
            "Clock_In": start,
            "Clock_Out": end,
            "Hours_Worked": calculate_hours(start, end),
        }

        store_data[store_number].append(entry)

    # Build final outputs
    final_output = {
        "Stores": {},
        "Total_Hours_By_Store": {},
        "Date_Range": {"Start": min_date, "End": max_date},
        "Spillover_Count": spillover_count,
    }
    employee_hours_output = {}

    for store_number, entries in tqdm(
        store_data.items(), desc="[attendance] Computing totals"
    ):
        total_hours = 0.0
        employees: Dict[str, List] = defaultdict(list)

        for entry in entries:
            total_hours += entry["Hours_Worked"]
            emp_entry = {
                "Clock_In": entry["Clock_In"],
                "Clock_Out": entry["Clock_Out"],
                "Hours_Worked": entry["Hours_Worked"],
            }
            employees[entry["Employee_Number"]].append(emp_entry)

        final_output["Stores"][store_number] = {
            "Employees": dict(employees),
            "Total_Hours": round(total_hours, 2),
        }
        final_output["Total_Hours_By_Store"][store_number] = round(total_hours, 2)
        employee_hours_output[store_number] = {
            "Total Hours": round(total_hours, 2),
            "Employee_Hours": [
                {
                    "Employee_Number": emp_id,
                    "Total_Hours": round(sum(e["Hours_Worked"] for e in hours), 2),
                }
                for emp_id, hours in employees.items()
            ],
        }

    # Sort by store number
    final_output["Stores"] = dict(
        sorted(final_output["Stores"].items(), key=lambda x: int(x[0]))
    )
    final_output["Total_Hours_By_Store"] = dict(
        sorted(final_output["Total_Hours_By_Store"].items(), key=lambda x: int(x[0]))
    )
    employee_hours_output = {
        str(k): employee_hours_output[k]
        for k in sorted(employee_hours_output.keys(), key=int)
    }

    # Write outputs
    hours_summary_path = config.output_dir / OUTPUT_HOURS_SUMMARY
    total_hours_path = config.output_dir / OUTPUT_TOTAL_HOURS

    with open(hours_summary_path, "w") as f:
        json.dump(final_output, f, indent=4)

    with open(total_hours_path, "w") as f:
        json.dump(employee_hours_output, f, indent=4)

    print(f"[attendance] Hours summary -> {hours_summary_path}")
    print(f"[attendance] Total hours   -> {total_hours_path}")
    print(f"[attendance] Date range    : {min_date} to {max_date}")
    print(f"[attendance] Spillovers    : {spillover_count}")

    return AttendanceResult(
        hours_summary_path=hours_summary_path,
        total_hours_path=total_hours_path,
        spillover_count=spillover_count,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate employee hours summary from timeclock data."
    )
    parser.add_argument(
        "--start", type=str, help="Pay period start (e.g. 'Mar 9 2026')"
    )
    parser.add_argument("--end", type=str, help="Pay period end (e.g. 'Mar 22 2026')")
    parser.add_argument("--pos-data-root", type=str, default=DEFAULT_POS_DATA_ROOT)
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: payroll/runs/<period>/output)",
    )
    parser.add_argument(
        "--timeclock-source",
        choices=("end+1", "end"),
        default=None,
        help=(
            "Employee_Time_Clock source folder for main attendance rows: "
            "'end+1' uses the day after the pay period, 'end' uses the pay period end date."
        ),
    )
    parser.add_argument(
        "--timeclock-source-date",
        type=str,
        action="append",
        default=None,
        help=(
            "Read main Employee_Time_Clock.txt rows from this POS folder date. "
            "Repeat for split or consolidated exports."
        ),
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


def _prompt_timeclock_source() -> bool:
    while True:
        raw = input(
            "Employee_Time_Clock source: use end+1 date folder? [Y/n]: "
        ).strip().lower()
        if raw in {"", "y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Enter Y to use end+1, or N to use the end date folder.")


def main() -> None:
    args = build_parser().parse_args()

    start_date = (
        parse_date_flexible(args.start) if args.start else _prompt_date("Start date: ")
    )
    end_date = parse_date_flexible(args.end) if args.end else _prompt_date("End date: ")

    if start_date > end_date:
        raise SystemExit("Start date must be <= end date.")

    use_end_plus_one_timeclock = (
        args.timeclock_source == "end+1"
        if args.timeclock_source
        else _prompt_timeclock_source()
    )
    timeclock_source_dates = tuple(
        parse_date_flexible(raw) for raw in (args.timeclock_source_date or [])
    )

    period_key = build_pay_period_key(start_date, end_date)
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else _REPO_ROOT / "payroll" / "runs" / period_key / "output"
    )

    run(
        AttendanceConfig(
            start_date=start_date,
            end_date=end_date,
            pos_data_root=Path(args.pos_data_root),
            output_dir=output_dir,
            use_end_plus_one_timeclock=use_end_plus_one_timeclock,
            timeclock_source_dates=timeclock_source_dates,
        )
    )


if __name__ == "__main__":
    main()
