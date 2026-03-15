
from datetime import datetime, timedelta

from .get_date_folders import get_date_folders
from .get_missing_folders import get_missing_folders
from .sync_folder import sync_folder


def ensure_day_after_folder(end_date: str, log_fn=print) -> bool:
    """
    Ensures the day-after end_date folder is synced (for timeclock parser).
    Only syncs if the folder is missing or empty.

    :param end_date: Pay period end date (YYYY-MM-DD)
    :param log_fn:   Callable for logging progress
    :return: True if folder is present (or sync succeeded), False if sync failed
    """
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    day_after = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    missing = get_missing_folders([day_after])
    if not missing:
        log_fn(f"  Day-after folder {day_after} already present.")
        return True
    return sync_folder(day_after, log_fn=log_fn)


def sync_s3_data(start_date: str, end_date: str, log_fn=print) -> bool:
    """
    Syncs the date range from S3. Only syncs folders that are missing or empty.
    Used by Data tab and payroll; if all folders already have data, skips sync.
    """
    date_folders = get_date_folders(start_date, end_date, include_day_after=False)
    missing = get_missing_folders(date_folders)

    if not missing:
        log_fn("✅ All folders already present, skipping S3 sync.")
        return True

    log_fn(f"📥 Syncing {len(missing)} missing folder(s) from S3...")

    success = True
    for folder in missing:
        if not sync_folder(folder, log_fn=log_fn):
            success = False

    if success:
        log_fn("✅ S3 sync complete.")
    else:
        log_fn("⚠️  S3 sync completed with errors. Check logs above.")

    return success