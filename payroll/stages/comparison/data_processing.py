from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_and_clean_data(generated_csv: Path, webapp_csv: Path):
    """Reads and cleans the generated payroll CSV and the webapp export CSV."""
    try:
        generated_data = pd.read_csv(generated_csv)
        webapp_data = pd.read_csv(webapp_csv)

        generated_data.columns = generated_data.columns.str.strip()
        webapp_data.columns = webapp_data.columns.str.strip()

        return generated_data, webapp_data
    except Exception as e:
        print(f"[comparison] Error reading CSV files: {e}")
        return None, None


EXCLUDED_STORE_NUMBERS = {
    4055, 5005, 13067, 13070, 13099, 13109,
    4028, 4041, 4062, 4064, 4071, 4078,
    4079, 5124, 10013, 10023, 37017, 37019, 4069
}


def get_store_data(generated_data) -> list:
    """Extracts unique store numbers from the generated payroll data."""
    if generated_data is None:
        print("[comparison] No generated data available.")
        return []

    store_numbers = sorted(set(generated_data["Store Number"].dropna().unique()))
    store_numbers = [int(s) for s in store_numbers]
    store_numbers = [s for s in store_numbers if s not in EXCLUDED_STORE_NUMBERS]
    return store_numbers


def get_store_records(generated_data, webapp_data, store_number):
    """Filters records from both datasets for a given store number."""
    if generated_data is None or webapp_data is None:
        return None, None

    generated_store = generated_data[generated_data["Store Number"] == store_number][
        ["Store Number", "Employee Number", "Employee Name", "Regular Hours", "Overtime Hours", "Coded Amount"]
    ]

    webapp_store = webapp_data[webapp_data["Exception Department"] == store_number][
        ["Exception Department", "Employee Number", "Regular Hours", "Overtime Hours", "Coded Amount"]
    ]

    return generated_store, webapp_store