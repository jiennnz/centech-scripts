from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from payroll.stages.s3_sync.sync import (
    DEFAULT_POS_DATA_ROOT,
    build_pay_period_key,
    fmt_human,
    fmt_iso,
    parse_date_flexible,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
OUTPUT_FILE = "tips_summary.json"


@dataclass
class TipsConfig:
    start_date: date
    end_date: date
    pos_data_root: Path
    output_dir: Path


@dataclass
class TipsResult:
    tips_summary_path: Path


def _compute_period_dates(start_date: date, end_date: date):
    """Every day in the pay period inclusive — excludes the extra end+1 day."""
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def _get_ticket_numbers(folder_path: Path) -> Dict[str, set]:
    ticket_store_map = defaultdict(set)
    sales_ticket_file = folder_path / "Sales_Ticket.txt"

    if sales_ticket_file.exists():
        with open(sales_ticket_file, "r", encoding="utf-8") as f:
            headers = f.readline().strip().split("|")
            if "Ticket_Number" in headers and "Store_ID" in headers:
                ticket_idx = headers.index("Ticket_Number")
                store_idx = headers.index("Store_ID")
                for line in f:
                    values = line.strip().split("|")
                    if len(values) > max(ticket_idx, store_idx):
                        store_id = values[store_idx].strip()
                        ticket_number = values[ticket_idx].strip()
                        ticket_store_map[store_id].add(ticket_number)

    return ticket_store_map


def _get_tips(folder_path: Path, ticket_store_map: Dict[str, set]) -> Dict[str, float]:
    tip_store_map = defaultdict(float)
    payment_file = folder_path / "Payment.txt"

    if payment_file.exists():
        with open(payment_file, "r", encoding="utf-8") as f:
            headers = f.readline().strip().split("|")
            if all(col in headers for col in ("Ticket_Number", "Tip_Amount", "Tip_Paid")):
                ticket_idx = headers.index("Ticket_Number")
                tip_idx = headers.index("Tip_Amount")
                tip_paid_idx = headers.index("Tip_Paid")

                for line in f:
                    values = line.strip().split("|")
                    if len(values) > max(ticket_idx, tip_idx, tip_paid_idx):
                        ticket_number = values[ticket_idx].strip()
                        tip_amount = float(values[tip_idx]) if values[tip_idx] else 0.0
                        tip_paid = values[tip_paid_idx].strip().lower() == "true"

                        if tip_paid:
                            for store_id, tickets in ticket_store_map.items():
                                if ticket_number in tickets:
                                    tip_store_map[store_id] += tip_amount

    return tip_store_map


def _add_payins(folder_path: Path, tip_store_map: Dict[str, float]) -> None:
    store_transactions_file = folder_path / "Store_Transactions.txt"

    if store_transactions_file.exists():
        with open(store_transactions_file, "r", encoding="utf-8") as f:
            headers = f.readline().strip().split("|")
            required = ("Store_ID", "Transaction_Type_Name", "Amount", "Status")
            if all(col in headers for col in required):
                store_idx = headers.index("Store_ID")
                type_idx = headers.index("Transaction_Type_Name")
                amount_idx = headers.index("Amount")
                status_idx = headers.index("Status")

                for line in f:
                    values = line.strip().split("|")
                    if len(values) > max(store_idx, type_idx, amount_idx, status_idx):
                        store_id = values[store_idx].strip()
                        transaction_type = values[type_idx].strip()
                        amount = float(values[amount_idx]) if values[amount_idx] else 0.0
                        status = values[status_idx].strip()

                        if transaction_type == "Payins" and status == "Inserted":
                            tip_store_map[store_id] += amount


def _load_store_mapping(folder_path: Path, store_mapping: Dict[str, str]) -> None:
    store_file = folder_path / "Store.txt"

    if store_file.exists():
        with open(store_file, "r", encoding="utf-8") as f:
            headers = f.readline().strip().split("|")
            if "Store_ID" in headers and "Store_Number" in headers:
                store_id_idx = headers.index("Store_ID")
                store_number_idx = headers.index("Store_Number")

                for line in f:
                    values = line.strip().split("|")
                    if len(values) > max(store_id_idx, store_number_idx):
                        store_id = values[store_id_idx].strip()
                        store_number = values[store_number_idx].strip()
                        store_mapping[store_id] = store_number


def run(config: TipsConfig) -> TipsResult:
    config.output_dir.mkdir(parents=True, exist_ok=True)

    period_dates = _compute_period_dates(config.start_date, config.end_date)
    final_data: Dict[str, Dict] = {}
    store_mapping: Dict[str, str] = {}

    print(f"[tips] Processing {len(period_dates)} day(s) from {fmt_iso(config.start_date)} to {fmt_iso(config.end_date)}")

    for d in tqdm(period_dates, desc="[tips] Processing days"):
        folder_path = config.pos_data_root / fmt_iso(d)

        if not folder_path.exists():
            continue

        date_str = fmt_human(d)

        _load_store_mapping(folder_path, store_mapping)
        ticket_store_map = _get_ticket_numbers(folder_path)
        tip_store_map = _get_tips(folder_path, ticket_store_map)
        _add_payins(folder_path, tip_store_map)

        for store_id, total_tip in tip_store_map.items():
            store_number = store_mapping.get(store_id, f"Unknown-{store_id}")

            if store_number not in final_data:
                final_data[store_number] = {"total": 0.0}

            final_data[store_number][date_str] = total_tip
            final_data[store_number]["total"] += total_tip

    sorted_data = dict(
        sorted(final_data.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0])
    )

    output_path = config.output_dir / OUTPUT_FILE
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sorted_data, f, indent=4)

    print(f"[tips] Tips summary -> {output_path}")
    return TipsResult(tips_summary_path=output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate tips summary for pay period.")
    parser.add_argument("--start", type=str, help="Pay period start (e.g. 'Mar 9 2026')")
    parser.add_argument("--end", type=str, help="Pay period end (e.g. 'Mar 22 2026')")
    parser.add_argument("--pos-data-root", type=str, default=DEFAULT_POS_DATA_ROOT)
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
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else _REPO_ROOT / "payroll" / "runs" / period_key / "output"
    )

    run(TipsConfig(
        start_date=start_date,
        end_date=end_date,
        pos_data_root=Path(args.pos_data_root),
        output_dir=output_dir,
    ))


if __name__ == "__main__":
    main()