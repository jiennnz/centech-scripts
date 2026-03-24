from __future__ import annotations


def generate_store_hours_report(structured_data: dict) -> dict:
    store_report = {}

    for store_number, employees in structured_data.items():
        w1_reg = w1_ot = w2_reg = w2_ot = 0.0

        for employee_data in employees.values():
            w1_reg += employee_data["Week_1"].get("Regular_Hours", 0)
            w1_ot += employee_data["Week_1"].get("Overtime_Hours", 0)
            w2_reg += employee_data["Week_2"].get("Regular_Hours", 0)
            w2_ot += employee_data["Week_2"].get("Overtime_Hours", 0)

        total_reg = w1_reg + w2_reg
        total_ot = w1_ot + w2_ot

        store_report[store_number] = {
            "Week_1": {
                "Regular_Hours": round(w1_reg, 2),
                "Overtime_Hours": round(w1_ot, 2),
            },
            "Week_2": {
                "Regular_Hours": round(w2_reg, 2),
                "Overtime_Hours": round(w2_ot, 2),
            },
            "Regular_Hours": round(total_reg, 2),
            "Overtime_Hours": round(total_ot, 2),
            "Total_Hours": round(total_reg + total_ot, 2),
        }

    return store_report