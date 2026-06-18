from __future__ import annotations

from pathlib import Path

import pandas as pd


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pos_data").is_dir():
            return parent
    return Path(__file__).resolve().parents[3]


def main() -> None:
    pos_data_dir = _repo_root() / "pos_data"

    available = sorted(
        d.name for d in pos_data_dir.iterdir()
        if d.is_dir() and len(d.name) == 10 and d.name[4] == "-"
    ) if pos_data_dir.is_dir() else []
    if available:
        print(f"Available dates: {available[0]} → {available[-1]} ({len(available)} days)")

    ticket_number = input("Ticket number to find: ").strip()
    start_date = input("Start date (YYYY-MM-DD): ").strip()
    end_date = input("End date (YYYY-MM-DD, inclusive): ").strip()

    if end_date < start_date:
        print("End date must be on or after start date.")
        return

    all_dirs = sorted(
        d for d in pos_data_dir.iterdir()
        if d.is_dir() and len(d.name) == 10 and d.name[4] == "-"
        and start_date <= d.name <= end_date
    )

    frames: list[pd.DataFrame] = []
    for day_dir in all_dirs:
        pay_path = day_dir / "Payment.txt"
        if not pay_path.exists():
            print(f"  Skipping {day_dir.name} — no Payment.txt")
            continue
        pay = pd.read_csv(pay_path, sep="|", dtype=str)
        match = pay[pay["Ticket_Number"].astype(str).str.strip() == ticket_number].copy()
        if not match.empty:
            match.insert(0, "source_folder", day_dir.name)
            frames.append(match)

    if not frames:
        print(f"No rows found for ticket {ticket_number} in {start_date} → {end_date}.")
        return

    df = pd.concat(frames, ignore_index=True)
    print(f"Found {len(df)} row(s) across {len(frames)} folder(s).")

    out_path = Path(f"ticket_{ticket_number}_{start_date}_{end_date}.csv")
    df.to_csv(out_path, index=False)
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
