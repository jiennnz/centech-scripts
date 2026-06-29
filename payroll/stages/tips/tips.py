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
    pos_source_date: date | None = None
    pos_source_date_through: date | None = None


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


def _get_tips(
    folder_path: Path,
    ticket_store_map: Dict[str, set],
    business_date: date | None = None,
) -> Dict[str, float]:
    tip_store_map = defaultdict(float)
    payment_file = folder_path / "Payment.txt"

    if payment_file.exists():
        with open(payment_file, "r", encoding="utf-8") as f:
            headers = f.readline().strip().split("|")
            required = ("Ticket_Number", "Tip_Amount", "Tip_Paid", "Payment_Date")
            if all(col in headers for col in required):
                ticket_idx = headers.index("Ticket_Number")
                tip_idx = headers.index("Tip_Amount")
                tip_paid_idx = headers.index("Tip_Paid")
                payment_date_idx = headers.index("Payment_Date")

                for line in f:
                    values = line.strip().split("|")
                    if len(values) > max(ticket_idx, tip_idx, tip_paid_idx, payment_date_idx):
                        payment_date = values[payment_date_idx].strip()[:10]
                        if business_date is not None and payment_date != fmt_iso(business_date):
                            continue
                        ticket_number = values[ticket_idx].strip()
                        tip_amount = float(values[tip_idx]) if values[tip_idx] else 0.0
                        tip_paid = values[tip_paid_idx].strip().lower() == "true"

                        if tip_paid:
                            for store_id, tickets in ticket_store_map.items():
                                if ticket_number in tickets:
                                    tip_store_map[store_id] += tip_amount

    return tip_store_map


def _add_payins(
    folder_path: Path,
    tip_store_map: Dict[str, float],
    business_date: date | None = None,
) -> None:
    store_transactions_file = folder_path / "Store_Transactions.txt"

    if store_transactions_file.exists():
        with open(store_transactions_file, "r", encoding="utf-8") as f:
            headers = f.readline().strip().split("|")
            required = ("Store_ID", "Transaction_Type_Name", "Amount", "Status", "Create_Date")
            if all(col in headers for col in required):
                store_idx = headers.index("Store_ID")
                type_idx = headers.index("Transaction_Type_Name")
                amount_idx = headers.index("Amount")
                status_idx = headers.index("Status")
                create_date_idx = headers.index("Create_Date")

                for line in f:
                    values = line.strip().split("|")
                    if len(values) > max(store_idx, type_idx, amount_idx, status_idx, create_date_idx):
                        create_date = values[create_date_idx].strip()[:10]
                        if business_date is not None and create_date != fmt_iso(business_date):
                            continue
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
    if config.pos_source_date is not None:
        if config.pos_source_date_through is not None:
            print(
                f"[tips] Reading days through {fmt_iso(config.pos_source_date_through)} "
                f"from source folder {fmt_iso(config.pos_source_date)}"
            )
        else:
            print(f"[tips] Reading all selected days from source folder {fmt_iso(config.pos_source_date)}")

    for d in tqdm(period_dates, desc="[tips] Processing days"):
        source_date = (
            config.pos_source_date
            if config.pos_source_date is not None
            and (
                config.pos_source_date_through is None
                or d <= config.pos_source_date_through
            )
            else d
        )
        folder_path = config.pos_data_root / fmt_iso(source_date)

        if not folder_path.exists():
            continue

        date_str = fmt_human(d)
        business_date = d if config.pos_source_date is not None else None

        _load_store_mapping(folder_path, store_mapping)
        ticket_store_map = _get_ticket_numbers(folder_path)
        tip_store_map = _get_tips(folder_path, ticket_store_map, business_date)
        _add_payins(folder_path, tip_store_map, business_date)

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
        "--pos-source-date",
        type=str,
        default=None,
        help=(
            "Read every selected business day from this POS folder date. "
            "Use for consolidated exports stored under one date folder."
        ),
    )
    parser.add_argument(
        "--pos-source-date-through",
        type=str,
        default=None,
        help=(
            "Use --pos-source-date only through this business date; later days "
            "read their own daily POS folders."
        ),
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
    pos_source_date = parse_date_flexible(args.pos_source_date) if args.pos_source_date else None
    pos_source_date_through = (
        parse_date_flexible(args.pos_source_date_through)
        if args.pos_source_date_through
        else None
    )

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
        pos_source_date=pos_source_date,
        pos_source_date_through=pos_source_date_through,
    ))


if __name__ == "__main__":
    main()
