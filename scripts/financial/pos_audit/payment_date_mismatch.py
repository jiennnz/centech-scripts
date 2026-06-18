"""
Find Payment.txt rows where Payment_Date == target_date but Processed_Date differs.
Scans all date folders from start_date through end_date for the given store.
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


def _load_store_id(day_dir: Path, store_number: str) -> str:
    store = pd.read_csv(day_dir / "Store.txt", sep="|", dtype=str)
    match = store[store["Store_Number"].astype(str).str.strip() == str(store_number).strip()]
    if match.empty:
        raise ValueError(f"Store {store_number} not found in {day_dir / 'Store.txt'}")
    return str(match["Store_ID"].iloc[0]).strip()


def find_mismatches(
    pos_data_dir: Path,
    store_number: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    base_dir = pos_data_dir / start_date
    if not base_dir.is_dir():
        raise ValueError(f"Start date directory not found: {base_dir}")

    store_id = _load_store_id(base_dir, store_number)

    all_dirs = sorted(
        d for d in pos_data_dir.iterdir()
        if d.is_dir() and len(d.name) == 10 and d.name[4] == "-"
        and start_date <= d.name <= end_date
    )

    target_date = pd.to_datetime(start_date).date()

    # collect tickets for this store created on start_date — may appear in any folder
    store_tickets: set[str] = set()
    for day_dir in all_dirs:
        st_path = day_dir / "Sales_Ticket.txt"
        if st_path.exists():
            st = pd.read_csv(st_path, sep="|", dtype=str)
            st["_creation_date"] = pd.to_datetime(st["Creation_Date"], errors="coerce")
            store_tickets |= set(
                st[
                    (st["Store_ID"].astype(str).str.strip() == store_id)
                    & (st["_creation_date"].dt.date == target_date)
                ]["Ticket_Number"].astype(str)
            )

    frames: list[pd.DataFrame] = []

    for day_dir in all_dirs:
        if not (day_dir / "Payment.txt").exists():
            print(f"  Skipping {day_dir.name} — missing Payment.txt")
            continue

        pay = pd.read_csv(day_dir / "Payment.txt", sep="|", dtype=str)

        chunk = pay[pay["Ticket_Number"].astype(str).isin(store_tickets)].copy()

        chunk["_payment_date"] = pd.to_datetime(chunk["Payment_Date"], errors="coerce")
        chunk["_processed_date"] = pd.to_datetime(chunk["Processed_Date"], errors="coerce")

        mask = (
            (chunk["_payment_date"].dt.date == target_date)
            & (chunk["_processed_date"].dt.date != target_date)
        )
        chunk = chunk[mask].copy()
        chunk["source_folder"] = day_dir.name

        if not chunk.empty:
            frames.append(chunk)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df = df.drop(columns=["_payment_date", "_processed_date"])
    return df


def main() -> None:
    root = _repo_root()
    pos_data_dir = root / "pos_data"

    available = sorted(
        d.name for d in pos_data_dir.iterdir()
        if d.is_dir() and len(d.name) == 10 and d.name[4] == "-"
    ) if pos_data_dir.is_dir() else []
    if available:
        print(f"Available dates: {available[0]} → {available[-1]} ({len(available)} days)")

    start_date = input("Payment date to check (YYYY-MM-DD): ").strip()
    end_date = input("Scan folders up to (YYYY-MM-DD, inclusive): ").strip()
    store_number = input("Store number (e.g. 4064): ").strip()

    if end_date < start_date:
        print("End date must be on or after start date.")
        return

    print(f"\nScanning {start_date} → {end_date} for store {store_number}...")
    df = find_mismatches(
        pos_data_dir=pos_data_dir,
        store_number=store_number,
        start_date=start_date,
        end_date=end_date,
    )

    if df.empty:
        print("No mismatches found.")
        return

    print(f"Found {len(df)} row(s) where Payment_Date={start_date} but Processed_Date differs.\n")

    out_dir = _script_root() / "audits" / start_date / store_number
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_out = out_dir / "payment_date_mismatches.csv"
    df.to_csv(csv_out, index=False)
    print(f"CSV: {csv_out}")

    xlsx_out = out_dir / "payment_date_mismatches.xlsx"
    with pd.ExcelWriter(xlsx_out, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="mismatches", index=False)
        if "source_folder" in df.columns:
            for folder_name, group in df.groupby("source_folder"):
                group.to_excel(writer, sheet_name=str(folder_name), index=False)
    print(f"Excel: {xlsx_out}")


if __name__ == "__main__":
    main()
