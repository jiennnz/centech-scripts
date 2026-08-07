from __future__ import annotations

import pandas as pd

from payroll.stages.comparison.workbook import (
    add_store_data_to_sheet,
    create_discrepancy_collector,
    create_workbook,
)


GENERATED_COLUMNS = [
    "Store Number",
    "Employee Number",
    "Employee Name",
    "Regular Hours",
    "Overtime Hours",
    "Coded Amount",
]
WEBAPP_COLUMNS = [
    "Exception Department",
    "Employee Number",
    "Regular Hours",
    "Overtime Hours",
    "Coded Amount",
]


def test_unmatched_zero_hour_employee_is_not_a_wrong_hours_discrepancy():
    generated = pd.DataFrame(
        [[2023, 998739, "Unknown", 0.0, 0.0, "$0.00"]],
        columns=GENERATED_COLUMNS,
    )
    webapp = pd.DataFrame(columns=WEBAPP_COLUMNS)
    discrepancies = create_discrepancy_collector()
    workbook = create_workbook()

    add_store_data_to_sheet(
        workbook,
        2023,
        generated,
        webapp,
        discrepancies=discrepancies,
    )

    assert discrepancies["wrong_hours"] == []
    assert workbook["2023"].sheet_properties.tabColor is None
    assert workbook["2023"]["A5"].fill.fill_type is None


def test_one_sided_hours_are_assigned_to_the_correct_source():
    generated = pd.DataFrame(
        [[2023, 111111, "QA only", 2.5, 0.5, "$0.00"]],
        columns=GENERATED_COLUMNS,
    )
    webapp = pd.DataFrame(
        [[2023, 222222, 3.5, 1.5, "$0.00"]],
        columns=WEBAPP_COLUMNS,
    )
    discrepancies = create_discrepancy_collector()
    workbook = create_workbook()

    add_store_data_to_sheet(
        workbook,
        2023,
        generated,
        webapp,
        discrepancies=discrepancies,
    )

    rows = {
        row["employee_number"]: row
        for row in discrepancies["wrong_hours"]
    }
    assert rows["111111"]["qa_regular_hours"] == 2.5
    assert rows["111111"]["qa_overtime_hours"] == 0.5
    assert rows["111111"]["centech_regular_hours"] is None
    assert rows["111111"]["centech_overtime_hours"] is None
    assert rows["222222"]["qa_regular_hours"] is None
    assert rows["222222"]["qa_overtime_hours"] is None
    assert rows["222222"]["centech_regular_hours"] == 3.5
    assert rows["222222"]["centech_overtime_hours"] == 1.5
