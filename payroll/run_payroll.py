from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_ROOT = str(_REPO_ROOT / "payroll" / "runs")

from payroll.stages.s3_sync.sync import (
    DEFAULT_POS_DATA_ROOT,
    DEFAULT_S3_PREFIX,
    SyncConfig,
    build_pay_period_key,
    compute_sync_dates,
    fmt_iso,
    parse_date_flexible,
    run as run_s3_sync,
)

from payroll.stages.attendance.attendance_all_stores import (
    AttendanceConfig,
    run as run_attendance,
)

from payroll.stages.hours.main import (
    HoursConfig,
    run as run_hours,
)

from payroll.stages.tips.tips import (
    TipsConfig,
    run as run_tips,
)

from payroll.stages.generate.generate import (
    GenerateConfig,
    run as run_generate,
)

from payroll.stages.comparison.main import (
    ComparisonConfig,
    run as run_comparison,
)


@dataclass
class PipelineConfig:
    start_date: date
    end_date: date
    runs_root: Path
    pos_data_root: Path
    s3_prefix: str
    force_sync: bool


def _timestamp_now() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _next_run_dir(runs_root: Path, period_key: str) -> Path:
    base = runs_root / period_key
    if not base.exists():
        return base
    existing = [p for p in runs_root.glob(f"{period_key}*") if p.is_dir()]
    run_number = len(existing) + 1
    return runs_root / f"{period_key}_run-{run_number}_{_timestamp_now()}"


def _ensure_run_dirs(run_dir: Path) -> None:
    (run_dir / "input").mkdir(parents=True, exist_ok=True)
    (run_dir / "output").mkdir(parents=True, exist_ok=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Payroll pipeline runner.")
    parser.add_argument("--start", type=str, help="Start date (e.g. 'Mar 9 2026')")
    parser.add_argument("--end", type=str, help="End date (e.g. 'Mar 22 2026')")
    parser.add_argument("--runs-root", type=str, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--pos-data-root", type=str, default=DEFAULT_POS_DATA_ROOT)
    parser.add_argument("--s3-prefix", type=str, default=DEFAULT_S3_PREFIX)
    parser.add_argument("--force-sync", action="store_true")
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


def _resolve_config(args: argparse.Namespace) -> PipelineConfig:
    start_date = parse_date_flexible(args.start) if args.start else _prompt_date("Start date (e.g. 'Mar 9 2026'): ")
    end_date = parse_date_flexible(args.end) if args.end else _prompt_date("End date (e.g. 'Mar 22 2026'): ")

    if start_date > end_date:
        raise SystemExit("Start date must be <= end date.")

    return PipelineConfig(
        start_date=start_date,
        end_date=end_date,
        runs_root=Path(args.runs_root),
        pos_data_root=Path(args.pos_data_root),
        s3_prefix=args.s3_prefix,
        force_sync=args.force_sync,
    )


def main() -> None:
    args = _build_parser().parse_args()
    cfg = _resolve_config(args)

    period_key = build_pay_period_key(cfg.start_date, cfg.end_date)
    run_dir = _next_run_dir(cfg.runs_root, period_key)
    sync_dates = compute_sync_dates(cfg.start_date, cfg.end_date)

    print("\n=== Payroll Pipeline ===")
    print(f"Pay period   : {period_key}")
    print(f"Run folder   : {run_dir}")
    print(f"POS data     : {cfg.pos_data_root}/")
    print(f"Sync folders : {', '.join(fmt_iso(d) for d in sync_dates)}")

    if run_dir.name != period_key:
        print("Note: Existing run detected. New rerun folder will be created.")

    proceed = input("\nContinue? [Y/n]: ").strip().lower()
    if proceed in {"n", "no"}:
        raise SystemExit("Cancelled.")

    _ensure_run_dirs(run_dir)

    # Stage 1: S3 Sync
    print("\n--- Stage 1: S3 Sync ---")
    s3_result = run_s3_sync(
        SyncConfig(
            start_date=cfg.start_date,
            end_date=cfg.end_date,
            pos_data_root=cfg.pos_data_root,
            s3_prefix=cfg.s3_prefix,
            force_sync=cfg.force_sync,
        )
    )
    print(f"[Stage 1] Done. {len(s3_result.local_dirs)} folders ready.")
    
    # Stage 2: Attendance
    print("\n--- Stage 2: Attendance ---")
    attendance_result = run_attendance(
        AttendanceConfig(
            start_date=cfg.start_date,
            end_date=cfg.end_date,
            pos_data_root=cfg.pos_data_root,
            output_dir=run_dir / "output",
        )
    )
    print(f"[Stage 2] Done. Spillovers: {attendance_result.spillover_count}")
    
    # Stage 3: Hours
    print("\n--- Stage 3: Hours ---")
    hours_result = run_hours(
        HoursConfig(
            start_date=cfg.start_date,
            end_date=cfg.end_date,
            input_dir=run_dir / "output",
            output_dir=run_dir / "output",
        )
    )
    print(f"[Stage 3] Done. Processed data -> {hours_result.processed_data_path.name}")
    
    # Stage 4: Tips
    print("\n--- Stage 4: Tips ---")
    tips_result = run_tips(
        TipsConfig(
            start_date=cfg.start_date,
            end_date=cfg.end_date,
            pos_data_root=cfg.pos_data_root,
            output_dir=run_dir / "output",
        )
    )
    print(f"[Stage 4] Done. Tips summary -> {tips_result.tips_summary_path.name}")
    
    # Stage 5: Generate CSV
    print("\n--- Stage 5: Generate CSV ---")
    generate_result = run_generate(
        GenerateConfig(
            start_date=cfg.start_date,
            end_date=cfg.end_date,
            pos_data_root=cfg.pos_data_root,
            input_dir=run_dir / "output",
            output_dir=run_dir / "output",
        )
    )
    print(f"[Stage 5] Done. Payroll CSV -> {generate_result.payroll_csv_path.name}")

    # Stage 6: Comparison
    print("\n--- Stage 6: Comparison ---")

    # Check if already moved to input/ from a previous attempt
    webapp_csv = next((run_dir / "input").glob("Timesheet*.csv"), None)

    if webapp_csv is None:
        # Check repo root and move it to input/
        while True:
            root_match = next(_REPO_ROOT.glob("Timesheet*.csv"), None)
            if root_match:
                dst = run_dir / "input" / root_match.name
                root_match.rename(dst)
                webapp_csv = dst
                print(f"[Stage 6] Moved {root_match.name} -> {dst}")
                break
            print(f"[Stage 6] No Timesheet*.csv found in repo root: {_REPO_ROOT}")
            ans = input("Drop the file there, then press Enter (or type 'skip'): ").strip().lower()
            if ans == "skip":
                print("[Stage 6] Skipped.")
                break

    if webapp_csv:
        comparison_result = run_comparison(
            ComparisonConfig(
                start_date=cfg.start_date,
                end_date=cfg.end_date,
                generated_csv=run_dir / "output" / "payroll_report.csv",
                webapp_csv=webapp_csv,
                output_dir=run_dir / "output",
            )
        )
        print(f"[Stage 6] Done. Workbook -> {comparison_result.comparison_xlsx_path.name}")

    print(f"\n=== Pipeline Complete ===")
    print(f"All outputs in: {run_dir / 'output'}")

if __name__ == "__main__":
    main()