"""
For a store + creation date, find all tickets created that day.
For each ticket, dump every Payment.txt row found across the folder range into its own CSV.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pos_data").is_dir():
            return parent
    return Path(__file__).resolve().parents[3]


def _script_root() -> Path:
    return Path(__file__).resolve().parent


def main() -> None:
    root = _repo_root()
    pos_data_dir = root / "pos_data"

    available = sorted(
        d.name for d in pos_data_dir.iterdir()
        if d.is_dir() and len(d.name) == 10 and d.name[4] == "-"
    ) if pos_data_dir.is_dir() else []
    if available:
        print(f"Available dates: {available[0]} → {available[-1]} ({len(available)} days)")

    store_number = input("Store number (e.g. 4064): ").strip()
    creation_date = input("Ticket creation date (YYYY-MM-DD): ").strip()
    end_date = input("Scan folders up to (YYYY-MM-DD, inclusive): ").strip()

    if end_date < creation_date:
        print("End date must be on or after creation date.")
        return

    base_dir = pos_data_dir / creation_date
    if not base_dir.is_dir():
        raise ValueError(f"Creation date directory not found: {base_dir}")

    # resolve store_id
    store = pd.read_csv(base_dir / "Store.txt", sep="|", dtype=str)
    match = store[store["Store_Number"].astype(str).str.strip() == store_number]
    if match.empty:
        print(f"Store {store_number} not found in {base_dir / 'Store.txt'}.")
        return
    store_id = str(match["Store_ID"].iloc[0]).strip()

    all_dirs = sorted(
        d for d in pos_data_dir.iterdir()
        if d.is_dir() and len(d.name) == 10 and d.name[4] == "-"
        and creation_date <= d.name <= end_date
    )

    # collect tickets created on creation_date for this store (scan all folders)
    target_date = pd.to_datetime(creation_date).date()
    ticket_numbers: set[str] = set()
    for day_dir in all_dirs:
        st_path = day_dir / "Sales_Ticket.txt"
        if not st_path.exists():
            continue
        st = pd.read_csv(st_path, sep="|", dtype=str)
        st["_creation_date"] = pd.to_datetime(st["Creation_Date"], errors="coerce")
        hits = st[
            (st["Store_ID"].astype(str).str.strip() == store_id)
            & (st["_creation_date"].dt.date == target_date)
        ]["Ticket_Number"].astype(str).str.strip()
        ticket_numbers |= set(hits)

    if not ticket_numbers:
        print(f"No tickets found for store {store_number} created on {creation_date}.")
        return

    print(f"Found {len(ticket_numbers)} ticket(s). Scanning payments {creation_date} → {end_date}...")

    # collect all payment rows per ticket across all folders
    ticket_frames: dict[str, list[pd.DataFrame]] = {t: [] for t in ticket_numbers}
    for day_dir in all_dirs:
        pay_path = day_dir / "Payment.txt"
        if not pay_path.exists():
            continue
        pay = pd.read_csv(pay_path, sep="|", dtype=str)
        pay["_ticket"] = pay["Ticket_Number"].astype(str).str.strip()
        for ticket in ticket_numbers:
            chunk = pay[pay["_ticket"] == ticket].drop(columns=["_ticket"]).copy()
            if not chunk.empty:
                chunk.insert(0, "source_folder", day_dir.name)
                ticket_frames[ticket].append(chunk)

    out_dir = (
        _script_root() / "audits"
        / creation_date
        / store_number
        / "per_ticket"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for ticket, frames in ticket_frames.items():
        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True)
        # only output if payment rows span more than one source folder
        if df["source_folder"].nunique() <= 1:
            continue
        out_path = out_dir / f"ticket_{ticket}.csv"
        df.to_csv(out_path, index=False)
        written += 1

    print(f"Found {written} ticket(s) with payments across multiple folders.")
    if written:
        print(f"Output: {out_dir}")


if __name__ == "__main__":
    main()
