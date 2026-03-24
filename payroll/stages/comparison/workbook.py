from __future__ import annotations

import openpyxl
from openpyxl.styles import Alignment, PatternFill
from pathlib import Path

from payroll.stages.comparison.style import (
    autofit_columns,
    style_sheet,
    style_summary_row,
    apply_red_text,
    apply_alternating_color,
)


def create_workbook():
    wb = openpyxl.Workbook()
    if "Sheet" in wb.sheetnames:
        wb.remove(wb["Sheet"])
    return wb


def add_store_data_to_sheet(wb, store, generated_store_data, webapp_store_data) -> None:
    generated_sorted = generated_store_data.sort_values(by="Employee Number")
    webapp_sorted = webapp_store_data.sort_values(by="Employee Number")

    ws = wb.create_sheet(title=str(store))
    style_sheet(ws)

    total_hours_generated = 0.0
    total_tip_generated = 0.0
    total_hours_webapp = 0.0
    total_tip_webapp = 0.0
    generated_data_map = {}

    for index, row in enumerate(generated_sorted.iterrows(), start=5):
        employee_number = row[1]["Employee Number"]
        employee_name = row[1]["Employee Name"]
        regular_hours = float(row[1]["Regular Hours"] or 0)
        overtime_hours = float(row[1]["Overtime Hours"] or 0)
        coded_amount = row[1]["Coded Amount"]

        if isinstance(coded_amount, str):
            coded_amount = float(coded_amount.replace("$", "").replace(",", ""))
        else:
            coded_amount = float(coded_amount)

        total_hours = regular_hours + overtime_hours
        tip_rate = coded_amount / total_hours if total_hours > 0 else 0

        total_hours_generated += total_hours
        total_tip_generated += coded_amount

        ws.cell(row=index, column=1, value=employee_number)
        ws.cell(row=index, column=2, value=employee_name)
        ws.cell(row=index, column=3, value=regular_hours)
        ws.cell(row=index, column=4, value=overtime_hours)
        ws.cell(row=index, column=5, value=coded_amount)
        ws.cell(row=index, column=6, value=tip_rate)

        generated_data_map[employee_number] = {
            "row": index,
            "regular_hours": regular_hours,
            "overtime_hours": overtime_hours,
        }

        for col_num in range(1, 7):
            ws.cell(row=index, column=col_num).alignment = Alignment(horizontal="center", vertical="center")

    for index, row in enumerate(webapp_sorted.iterrows(), start=5):
        employee_number = row[1]["Employee Number"]
        regular_hours = float(row[1]["Regular Hours"] or 0)
        overtime_hours = float(row[1]["Overtime Hours"] or 0)
        coded_amount = row[1]["Coded Amount"]

        if isinstance(coded_amount, str):
            coded_amount = float(coded_amount.replace("$", "").replace(",", ""))
        else:
            coded_amount = float(coded_amount)

        total_hours = regular_hours + overtime_hours
        tip_rate = coded_amount / total_hours if total_hours > 0 else 0

        total_hours_webapp += total_hours
        total_tip_webapp += coded_amount

        ws.cell(row=index, column=8, value=employee_number)
        ws.cell(row=index, column=9, value=regular_hours)
        ws.cell(row=index, column=10, value=overtime_hours)
        ws.cell(row=index, column=11, value=coded_amount)
        ws.cell(row=index, column=12, value=tip_rate)

        for col_num in range(8, 13):
            ws.cell(row=index, column=col_num).alignment = Alignment(horizontal="center", vertical="center")

        if employee_number in generated_data_map:
            gen_row = generated_data_map[employee_number]["row"]
            gen_regular = generated_data_map[employee_number]["regular_hours"]
            gen_overtime = generated_data_map[employee_number]["overtime_hours"]

            if regular_hours != gen_regular or overtime_hours != gen_overtime:
                apply_red_text(ws, gen_row, [2, 3, 4])
                apply_red_text(ws, index, [9, 10])
                alternate_row = (index % 3) + 1
                apply_alternating_color(ws, gen_row, [1], alternate_row)
                apply_alternating_color(ws, index, [8], alternate_row)

    generated_only = set(generated_sorted["Employee Number"]) - set(webapp_sorted["Employee Number"])
    for index, row in enumerate(generated_sorted.iterrows(), start=5):
        if row[1]["Employee Number"] in generated_only:
            ws.cell(row=index, column=1).fill = PatternFill(
                start_color="FFA500", end_color="FFA500", fill_type="solid"
            )

    webapp_only = set(webapp_sorted["Employee Number"]) - set(generated_sorted["Employee Number"])
    for index, row in enumerate(webapp_sorted.iterrows(), start=5):
        if row[1]["Employee Number"] in webapp_only:
            ws.cell(row=index, column=8).fill = PatternFill(
                start_color="FFFF00", end_color="FFFF00", fill_type="solid"
            )

    tip_rate_generated = total_tip_generated / total_hours_generated if total_hours_generated > 0 else 0
    tip_rate_webapp = total_tip_webapp / total_hours_webapp if total_hours_webapp > 0 else 0

    last_row = max(len(generated_sorted), len(webapp_sorted)) + 7

    ws.cell(row=last_row, column=1, value="Total Hours")
    ws.cell(row=last_row, column=2, value=total_hours_generated)
    ws.cell(row=last_row, column=8, value="Total Hours")
    ws.cell(row=last_row, column=9, value=total_hours_webapp)

    ws.cell(row=last_row + 1, column=1, value="Total Tips")
    ws.cell(row=last_row + 1, column=2, value=total_tip_generated)
    ws.cell(row=last_row + 1, column=8, value="Total Tips")
    ws.cell(row=last_row + 1, column=9, value=total_tip_webapp)

    ws.cell(row=last_row + 2, column=1, value="Tip Rate")
    ws.cell(row=last_row + 2, column=2, value=tip_rate_generated)
    ws.cell(row=last_row + 2, column=8, value="Tip Rate")
    ws.cell(row=last_row + 2, column=9, value=tip_rate_webapp)

    style_summary_row(ws, start_row=last_row, columns=[1, 8])
    style_summary_row(ws, start_row=last_row + 1, columns=[1, 8])
    style_summary_row(ws, start_row=last_row + 2, columns=[1, 8])

    autofit_columns(ws)


def save_workbook(wb, output_path: Path) -> None:
    wb.save(output_path)