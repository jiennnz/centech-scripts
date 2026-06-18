import os
import sys
import csv
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

PARENT_FOLDER = "pos_data"
TRANSACTION_FILE = "Store_Transactions.txt"
STORE_FILE = "Store.txt"
REPORT_FOLDER = "Store_Reports"
RULES_DIR = Path("financial/sales_export_comparison/rules")

ORG_YAML = {
    "austin": "century_austin",
    "century": "century",
}


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / PARENT_FOLDER).is_dir():
            return parent
    return Path(__file__).resolve().parents[3]


def load_store_numbers(org: str) -> list[str]:
    yaml_file = _repo_root() / "scripts" / RULES_DIR / f"{ORG_YAML[org]}.yaml"
    with open(yaml_file, "r") as f:
        config = yaml.safe_load(f)
    return config["stores"]


def get_date_folders(start: date, end: date) -> list[str]:
    folders = []
    d = start
    while d <= end:
        folders.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return folders


def build_store_id_map(store_numbers: set[str], date_folders: list[str]) -> dict[str, str]:
    pos_data_dir = _repo_root() / PARENT_FOLDER
    result = {}
    remaining = set(store_numbers)
    for folder in date_folders:
        if not remaining:
            break
        store_file = pos_data_dir / folder / STORE_FILE
        if not store_file.is_file():
            continue
        with open(store_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="|")
            for row in reader:
                sn = row.get("Store_Number", "")
                if sn in remaining:
                    result[sn] = row["Store_ID"]
                    remaining.discard(sn)
    return result


def load_register_audits(date_folders: list[str], store_ids: set[str]) -> dict[str, list[dict]]:
    """Load all register audit rows per folder for the given store IDs."""
    pos_data_dir = _repo_root() / PARENT_FOLDER
    data: dict[str, list[dict]] = {}
    for folder in date_folders:
        tx_file = pos_data_dir / folder / TRANSACTION_FILE
        if not tx_file.is_file():
            data[folder] = []
            continue
        rows = []
        with open(tx_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="|")
            for row in reader:
                if row.get("Store_ID") not in store_ids:
                    continue
                if "register audit" in row.get("Transaction_Type_Name", "").lower():
                    row["_folder"] = folder
                    rows.append(row)
        data[folder] = rows
    return data


def extract_date_part(dt_str: str) -> str:
    """Extract YYYY-MM-DD from '2026-03-01 21:58:00' or similar."""
    return dt_str[:10] if dt_str else ""


def find_misplaced_audits(
    date_folders: list[str],
    store_numbers: list[str],
    store_id_map: dict[str, str],
    audits_by_folder: dict[str, list[dict]],
    date_field: str,
) -> list[dict]:
    """
    For each date D and each store:
      - If no register audit row exists in folder D for that store,
        search folders D+1..end for rows where date_field date == D.
    Returns collected rows with metadata.
    """
    results = []

    for i, folder_d in enumerate(date_folders):
        present_store_ids = {row["Store_ID"] for row in audits_by_folder.get(folder_d, [])}

        for store_num in store_numbers:
            store_id = store_id_map.get(store_num)
            if not store_id:
                continue
            if store_id in present_store_ids:
                continue

            for later_folder in date_folders[i + 1:]:
                for row in audits_by_folder.get(later_folder, []):
                    if row["Store_ID"] != store_id:
                        continue
                    if extract_date_part(row.get(date_field, "")) == folder_d:
                        result_row = dict(row)
                        result_row["_expected_date"] = folder_d
                        result_row["_found_in_folder"] = later_folder
                        result_row["_store_number"] = store_num
                        results.append(result_row)

    return results


def write_csv(rows: list[dict], filepath: str):
    if not rows:
        print(f"  No results — skipping {filepath}")
        return
    meta_keys = ["_expected_date", "_found_in_folder", "_store_number", "_folder"]
    data_keys = [k for k in rows[0].keys() if k not in meta_keys]
    fieldnames = meta_keys + data_keys
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Written: {filepath} ({len(rows)} rows)")


def parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def main():
    print("=== Register Audit Checker ===\n")

    start_str = input("Start date (YYYY-MM-DD): ").strip()
    end_str = input("End date (YYYY-MM-DD): ").strip()
    org_choice = input("Organization [austin/century]: ").strip().lower()

    if org_choice not in ORG_YAML:
        print("Invalid org. Must be 'austin' or 'century'.")
        sys.exit(1)

    start = parse_date(start_str)
    end = parse_date(end_str)

    if start > end:
        print("Start date must be <= end date.")
        sys.exit(1)

    date_folders = get_date_folders(start, end)
    print(f"\nDate range: {start_str} to {end_str} ({len(date_folders)} days)")

    store_numbers = load_store_numbers(org_choice)
    print(f"Stores ({org_choice}): {len(store_numbers)} stores")

    print("\nBuilding Store_ID map...")
    store_id_map = build_store_id_map(set(store_numbers), date_folders)
    print(f"  Resolved {len(store_id_map)}/{len(store_numbers)} stores")

    store_ids = set(store_id_map.values())

    print("Loading register audit rows...")
    audits_by_folder = load_register_audits(date_folders, store_ids)
    total_rows = sum(len(v) for v in audits_by_folder.values())
    print(f"  {total_rows} register audit rows across {len(date_folders)} folders")

    os.makedirs(REPORT_FOLDER, exist_ok=True)
    prefix = f"{REPORT_FOLDER}/register_audit_check_{org_choice}_{start_str}_{end_str}"

    print("\nChecking by Transaction_Date...")
    tx_results = find_misplaced_audits(
        date_folders, store_numbers, store_id_map, audits_by_folder, "Transaction_Date"
    )
    write_csv(tx_results, f"{prefix}_by_transaction_date.csv")

    print("Checking by Create_Date...")
    cr_results = find_misplaced_audits(
        date_folders, store_numbers, store_id_map, audits_by_folder, "Create_Date"
    )
    write_csv(cr_results, f"{prefix}_by_create_date.csv")

    print("\nDone.")


if __name__ == "__main__":
    main()
