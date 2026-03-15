from datetime import datetime, timedelta


def get_date_folders(start_date: str, end_date: str, include_day_after: bool = False) -> list[str]:
    """
    Returns a list of date folder names (YYYY-MM-DD) for the given range.
    Sync uses include_day_after=False; timeclock parser should request the
    day-after folder separately via ensure_day_after_folder().

    :param start_date:        Start date (YYYY-MM-DD)
    :param end_date:          End date (YYYY-MM-DD)
    :param include_day_after: If True, include the day after end_date
    :return: List of date strings
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    if include_day_after:
        end += timedelta(days=1)

    folders = []
    current = start
    while current <= end:
        folders.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)

    return folders