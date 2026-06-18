from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta


DT_FMT = "%Y-%m-%d %H:%M:%S"
WEEKLY_REGULAR_CAP = 40.0


def _to_dt(d: date, end_of_day: bool = False) -> datetime:
    if end_of_day:
        return datetime.strptime(f"{d.strftime('%Y-%m-%d')} 23:59:59", DT_FMT)
    return datetime.strptime(f"{d.strftime('%Y-%m-%d')} 00:00:00", DT_FMT)


def calculate_hours(clock_in: str, clock_out: str, week_end: datetime) -> float:
    start_dt = datetime.strptime(clock_in, DT_FMT)
    end_dt = datetime.strptime(clock_out, DT_FMT)

    if end_dt > week_end:
        end_dt = week_end

    if end_dt < start_dt:
        end_dt += timedelta(days=1)

    return round((end_dt - start_dt).total_seconds() / 3600, 2)


def _allocate(
    structured_data: dict,
    store_number: str,
    employee_number: str,
    week_key: str,
    hours: float,
    running_total: float,
) -> float:
    """Add `hours` to a store/employee/week, splitting between regular and
    overtime based on the running weekly total. Returns the new running total."""
    if hours <= 0:
        return running_total

    remaining_regular = max(0.0, WEEKLY_REGULAR_CAP - running_total)
    reg = min(hours, remaining_regular)
    ot = hours - reg

    bucket = structured_data[store_number][employee_number][week_key]
    bucket["Regular_Hours"] = round(bucket["Regular_Hours"] + reg, 2)
    bucket["Overtime_Hours"] = round(bucket["Overtime_Hours"] + ot, 2)

    return running_total + hours


def process_employee_data(
    employee_hours_data: dict,
    single_store_employees: dict,
    multi_store_employees: dict,
    week_1_start: date,
    week_1_end: date,
    week_2_start: date,
    week_2_end: date,
) -> dict:
    w1_start = _to_dt(week_1_start)
    w1_end = _to_dt(week_1_end, end_of_day=True)
    w2_start = _to_dt(week_2_start)
    w2_end = _to_dt(week_2_end, end_of_day=True)

    structured_data = defaultdict(lambda: defaultdict(lambda: {
        "Week_1": {"Regular_Hours": 0, "Overtime_Hours": 0},
        "Week_2": {"Regular_Hours": 0, "Overtime_Hours": 0},
    }))

    # ------------------------------------------------------------------
    # Single-store employees
    # ------------------------------------------------------------------
    for store_number, employees in single_store_employees.items():
        for employee_number in employees:
            total_w1 = 0.0
            total_w2 = 0.0

            shifts = (
                employee_hours_data["Stores"]
                .get(store_number, {})
                .get("Employees", {})
                .get(employee_number, [])
            )

            for shift in shifts:
                clock_in_dt = datetime.strptime(shift["Clock_In"], DT_FMT)
                clock_out_dt = datetime.strptime(shift["Clock_Out"], DT_FMT)
                hours = shift["Hours_Worked"]

                if w1_start <= clock_in_dt <= w1_end:
                    if clock_out_dt >= w2_start:
                        w1_hours = calculate_hours(
                            shift["Clock_In"], w1_end.strftime(DT_FMT), w2_end
                        )
                        total_w1 += w1_hours
                        total_w2 += hours - w1_hours
                    else:
                        total_w1 += hours

                elif w2_start <= clock_in_dt <= w2_end:
                    total_w2 += hours

            bucket = structured_data[store_number][employee_number]
            bucket["Week_1"]["Regular_Hours"] = round(min(total_w1, WEEKLY_REGULAR_CAP), 2)
            bucket["Week_1"]["Overtime_Hours"] = round(max(0.0, total_w1 - WEEKLY_REGULAR_CAP), 2)
            bucket["Week_2"]["Regular_Hours"] = round(min(total_w2, WEEKLY_REGULAR_CAP), 2)
            bucket["Week_2"]["Overtime_Hours"] = round(max(0.0, total_w2 - WEEKLY_REGULAR_CAP), 2)

    # ------------------------------------------------------------------
    # Multi-store employees
    # ------------------------------------------------------------------
    for employee_number, store_numbers in multi_store_employees.items():
        all_shifts = []

        for store_number in store_numbers:
            shifts = (
                employee_hours_data["Stores"]
                .get(store_number, {})
                .get("Employees", {})
                .get(employee_number, [])
            )
            for shift in shifts:
                s = shift.copy()
                s["Store_Number"] = store_number
                all_shifts.append(s)

        all_shifts.sort(key=lambda x: datetime.strptime(x["Clock_In"], DT_FMT))

        total_w1 = 0.0
        total_w2 = 0.0

        for shift in all_shifts:
            clock_in_dt = datetime.strptime(shift["Clock_In"], DT_FMT)
            clock_out_dt = datetime.strptime(shift["Clock_Out"], DT_FMT)
            hours = shift["Hours_Worked"]
            store_number = shift["Store_Number"]

            if w1_start <= clock_in_dt <= w1_end:
                if clock_out_dt >= w2_start:
                    w1_hours = calculate_hours(
                        shift["Clock_In"], w1_end.strftime(DT_FMT), w2_end
                    )
                    w2_hours = hours - w1_hours

                    total_w1 = _allocate(
                        structured_data, store_number, employee_number,
                        "Week_1", w1_hours, total_w1,
                    )
                    total_w2 = _allocate(
                        structured_data, store_number, employee_number,
                        "Week_2", w2_hours, total_w2,
                    )
                else:
                    total_w1 = _allocate(
                        structured_data, store_number, employee_number,
                        "Week_1", hours, total_w1,
                    )

            elif w2_start <= clock_in_dt <= w2_end:
                total_w2 = _allocate(
                    structured_data, store_number, employee_number,
                    "Week_2", hours, total_w2,
                )

    return structured_data