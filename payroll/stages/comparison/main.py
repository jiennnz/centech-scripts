from __future__ import annotations

import argparse
import glob
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from payroll.stages.s3_sync.sync import (
    build_pay_period_key,
    parse_date_flexible,
)
from payroll.stages.comparison.constants import get_output_filename
from payroll.stages.comparison.data_processing import (
    read_and_clean_data,
    get_store_data,
    get_store_records,
    load_centech_tips,
)
from payroll.stages.comparison.workbook import (
    add_discrepancy_sheets,
    create_workbook,
    create_discrepancy_collector,
    add_store_data_to_sheet,
    save_workbook,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@dataclass
class ComparisonConfig:
    start_date: date
    end_date: date
    generated_csv: Path
    webapp_csv: Path
    output_dir: Path
    tips_csv: Path | None = None


@dataclass
class ComparisonResult:
    comparison_xlsx_path: Path


def _find_webapp_csv(input_dir: Path) -> Path | None:
    # Check input/ first (pipeline already moved it there)
    matches = list(input_dir.glob("Timesheet*.csv"))
    if matches:
        return matches[0]
    # Fallback: check repo root for standalone runs
    matches = list(_REPO_ROOT.glob("Timesheet*.csv"))
    if matches:
        return matches[0]
    return None


def run(config: ComparisonConfig) -> ComparisonResult:
    config.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[comparison] Generated CSV : {config.generated_csv}")
    print(f"[comparison] Webapp CSV    : {config.webapp_csv}")

    generated_data, webapp_data = read_and_clean_data(config.generated_csv, config.webapp_csv)
    if generated_data is None or webapp_data is None:
        raise RuntimeError("[comparison] Failed to read input CSV files.")

    tips_csv = config.tips_csv or (config.webapp_csv.parent / "centech_tips.csv")
    if not tips_csv.exists():
        tips_csv = _REPO_ROOT / "centech_tips.csv"
    centech_tips = None
    if tips_csv.exists():
        centech_tips = load_centech_tips(tips_csv)
        print(f"[comparison] CenTech tips CSV: {tips_csv} ({len(centech_tips)} stores)")
    else:
        print(f"[comparison] Warning: centech_tips.csv not found, falling back to calculated totals.")

    store_numbers = get_store_data(generated_data)
    print(f"[comparison] Processing {len(store_numbers)} stores.")

    wb = create_workbook()
    discrepancies = create_discrepancy_collector()
    tip_date_label = config.end_date.strftime("%b-%d-%Y")

    for store in store_numbers:
        print(f"[comparison] Store {store}")
        generated_store, webapp_store = get_store_records(generated_data, webapp_data, store)
        add_store_data_to_sheet(
            wb,
            store,
            generated_store,
            webapp_store,
            centech_tips=centech_tips,
            discrepancies=discrepancies,
            tip_date_label=tip_date_label,
        )

    add_discrepancy_sheets(wb, discrepancies)

    period_key = build_pay_period_key(config.start_date, config.end_date)
    output_path = config.output_dir / get_output_filename(period_key)
    save_workbook(wb, output_path)

    print(f"[comparison] Workbook -> {output_path}")
    return ComparisonResult(comparison_xlsx_path=output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate payroll comparison workbook.")
    parser.add_argument("--start", type=str, help="Pay period start (e.g. 'Mar 9 2026')")
    parser.add_argument("--end", type=str, help="Pay period end (e.g. 'Mar 22 2026')")
    parser.add_argument("--generated-csv", type=str, default=None,
        help="Path to generated payroll CSV (default: payroll/runs/<period>/output/payroll_report.csv)")
    parser.add_argument("--webapp-csv", type=str, default=None,
        help="Path to webapp export CSV (default: scans payroll/runs/<period>/input/Timesheet*.csv)")
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
    default_run_dir = _REPO_ROOT / "payroll" / "runs" / period_key

    generated_csv = (
        Path(args.generated_csv) if args.generated_csv
        else default_run_dir / "output" / "payroll_report.csv"
    )
    output_dir = (
        Path(args.output_dir) if args.output_dir
        else default_run_dir / "output"
    )

    if args.webapp_csv:
        webapp_csv = Path(args.webapp_csv)
    else:
        webapp_csv = _find_webapp_csv(default_run_dir / "input")
        while webapp_csv is None:
            print(f"[comparison] No Timesheet*.csv found in {default_run_dir / 'input'}")
            input("Drop the webapp export CSV there, then press Enter...")
            webapp_csv = _find_webapp_csv(default_run_dir / "input")

    run(ComparisonConfig(
        start_date=start_date,
        end_date=end_date,
        generated_csv=generated_csv,
        webapp_csv=webapp_csv,
        output_dir=output_dir,
    ))


if __name__ == "__main__":
    main()
