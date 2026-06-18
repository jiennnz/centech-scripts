import os
import csv
from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pos_data").is_dir():
            return parent
    return Path(__file__).resolve().parents[3]


# Austin store numbers to look for
AUSTIN_STORES = {
    "4028", "4041", "4055", "4062", "4064", "4071",
    "4078", "4079", "4089", "5124", "10013", "10023",
    "37017", "37019"
}

def find_date_folders(base_path: Path):
    """Find all folders matching the YYYY-MM-DD naming convention."""
    date_folders = []
    for item in sorted(base_path.iterdir()):
        if item.is_dir():
            parts = item.name.split("-")
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                date_folders.append(item)
    return date_folders

def read_pipe_delimited(filepath: Path):
    """Read a pipe-delimited file and return list of dicts."""
    rows = []
    with open(filepath, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="|")
        for row in reader:
            rows.append(row)
    return rows

def build_store_map(store_file: Path):
    """Build a mapping of Store_ID -> Store_Number from Store.txt."""
    store_map = {}
    if not store_file.exists():
        print(f"  [!] Store.txt not found at {store_file}")
        return store_map
    rows = read_pipe_delimited(store_file)
    for row in rows:
        store_id = row.get("Store_ID", "").strip()
        store_number = row.get("Store_Number", "").strip()
        if store_id and store_number:
            store_map[store_id] = store_number
    return store_map

def check_folder(date_folder: Path):
    """Check a single date folder for Austin stores in Sales_Ticket.txt."""
    sales_file = date_folder / "Sales_Ticket.txt"
    store_file = date_folder / "Store.txt"

    if not sales_file.exists():
        print(f"  [!] Sales_Ticket.txt not found — skipping.")
        return

    # Build Store_ID -> Store_Number mapping
    store_map = build_store_map(store_file)

    # Read sales tickets
    tickets = read_pipe_delimited(sales_file)

    # Count tickets per Austin store number
    found = {}  # store_number -> ticket count
    unmapped_ids = set()

    for row in tickets:
        store_id = row.get("Store_ID", "").strip()
        store_number = store_map.get(store_id)

        if store_number is None:
            unmapped_ids.add(store_id)
            continue

        if store_number in AUSTIN_STORES:
            found[store_number] = found.get(store_number, 0) + 1

    if found:
        print(f"  Austin stores found in sales tickets:")
        for store_num in sorted(found, key=lambda x: int(x)):
            print(f"    Store #{store_num:>6}  —  {found[store_num]:,} ticket(s)")
    else:
        print(f"  No Austin stores found in sales tickets.")

def main():
    base_path = _repo_root() / "pos_data"

    if not base_path.exists():
        print(f"[ERROR] Folder '{base_path}' not found. Run this script from the parent directory.")
        return

    date_folders = find_date_folders(base_path)

    if not date_folders:
        print(f"[ERROR] No date folders (YYYY-MM-DD) found inside '{base_path}'.")
        return

    print(f"Found {len(date_folders)} date folder(s) in '{base_path}'\n")

    for folder in date_folders:
        print(f"📁 {folder.name}")
        check_folder(folder)
        print()

if __name__ == "__main__":
    main()
