from __future__ import annotations

import argparse
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List


DEFAULT_S3_PREFIX = "s3://century-data/pos_data"
DEFAULT_POS_DATA_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent / "pos_data")


@dataclass
class SyncConfig:
    start_date: date
    end_date: date
    pos_data_root: Path
    s3_prefix: str = DEFAULT_S3_PREFIX
    force_sync: bool = False


@dataclass
class SyncResult:
    pos_data_root: Path
    synced_dates_iso: List[str]
    local_dirs: List[Path]


def parse_date_flexible(raw: str) -> date:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%b %d %Y", "%b-%d-%Y", "%B %d %Y", "%B-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f"Invalid date '{raw}'. Try formats like '2026-03-09' or 'Mar 9 2026'."
    )


def fmt_iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def fmt_human(d: date) -> str:
    return d.strftime("%b-%d-%Y")


def build_pay_period_key(start_date: date, end_date: date) -> str:
    return f"{fmt_human(start_date)}_{fmt_human(end_date)}"


def compute_sync_dates(start_date: date, end_date: date) -> List[date]:
    if start_date > end_date:
        raise ValueError("Start date must be <= end date.")
    dates: List[date] = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    dates.append(end_date + timedelta(days=1))
    return dates


def _assert_aws_cli() -> None:
    if shutil.which("aws") is None:
        raise RuntimeError("AWS CLI is not installed or not in PATH.")


def run(config: SyncConfig) -> SyncResult:
    _assert_aws_cli()

    config.pos_data_root.mkdir(parents=True, exist_ok=True)
    sync_dates = compute_sync_dates(config.start_date, config.end_date)

    local_dirs: List[Path] = []

    for d in sync_dates:
        src = f"{config.s3_prefix}/{fmt_iso(d)}"
        dst = config.pos_data_root / fmt_iso(d)

        has_local_data = dst.exists() and any(dst.iterdir())
        if has_local_data and not config.force_sync:
            print(f"[s3_sync] Reusing existing: {dst}")
            local_dirs.append(dst)
            continue

        dst.mkdir(parents=True, exist_ok=True)
        cmd = ["aws", "s3", "sync", src, str(dst)]
        print(f"[s3_sync] Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        local_dirs.append(dst)

    print(f"[s3_sync] Done. POS data root: {config.pos_data_root}")
    return SyncResult(
        pos_data_root=config.pos_data_root,
        synced_dates_iso=[fmt_iso(d) for d in sync_dates],
        local_dirs=local_dirs,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync payroll POS data from S3.")
    parser.add_argument("--start", type=str, help="Start date (e.g. 'Mar 9 2026')")
    parser.add_argument("--end", type=str, help="End date (e.g. 'Mar 22 2026')")
    parser.add_argument(
        "--pos-data-root",
        type=str,
        default=DEFAULT_POS_DATA_ROOT,
        help=f"Local folder for POS data (default: {DEFAULT_POS_DATA_ROOT})",
    )
    parser.add_argument(
        "--s3-prefix",
        type=str,
        default=DEFAULT_S3_PREFIX,
        help=f"S3 prefix (default: {DEFAULT_S3_PREFIX})",
    )
    parser.add_argument(
        "--force-sync",
        action="store_true",
        help="Force sync even if local folder already has data",
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

    start_date = parse_date_flexible(args.start) if args.start else _prompt_date("Start date (e.g. 'Mar 9 2026'): ")
    end_date = parse_date_flexible(args.end) if args.end else _prompt_date("End date (e.g. 'Mar 22 2026'): ")

    if start_date > end_date:
        raise SystemExit("Start date must be <= end date.")

    period_key = build_pay_period_key(start_date, end_date)
    sync_dates = compute_sync_dates(start_date, end_date)

    print(f"\nPay period : {period_key}")
    print(f"Folders    : {', '.join(fmt_iso(d) for d in sync_dates)}")
    print(f"Destination: {args.pos_data_root}/")

    proceed = input("\nProceed with sync? [Y/n]: ").strip().lower()
    if proceed in {"n", "no"}:
        raise SystemExit("Cancelled.")

    cfg = SyncConfig(
        start_date=start_date,
        end_date=end_date,
        pos_data_root=Path(args.pos_data_root),
        s3_prefix=args.s3_prefix,
        force_sync=args.force_sync,
    )
    run(cfg)


if __name__ == "__main__":
    main()