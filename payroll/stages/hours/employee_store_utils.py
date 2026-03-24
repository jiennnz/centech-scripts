from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Tuple


def get_employee_store_data(
    employee_hours_data: dict,
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """
    Returns:
      single_store_employees: { store_number: [employee_number, ...] }
      multi_store_employees:  { employee_number: [store_number, ...] }
    """
    employee_store_map: Dict[str, set] = defaultdict(set)

    for store_id, store_data in employee_hours_data.get("Stores", {}).items():
        for employee_id in store_data.get("Employees", {}):
            employee_store_map[employee_id].add(store_id)

    single_store: Dict[str, List[str]] = defaultdict(list)
    multi_store: Dict[str, List[str]] = {}

    for employee_id, stores in employee_store_map.items():
        if len(stores) == 1:
            single_store[list(stores)[0]].append(employee_id)
        else:
            multi_store[employee_id] = list(stores)

    return single_store, multi_store