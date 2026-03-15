import os
import shutil
import subprocess

from config import POS_DATA_DIR, S3_BUCKET, S3_PREFIX


def sync_folder(date_folder: str, log_fn=print) -> bool:
    """
    Runs aws s3 sync for a single date folder.
    If the folder has no data after sync, removes it and logs.
    """
    s3_path = f"s3://{S3_BUCKET}/{S3_PREFIX}/{date_folder}"
    local_path = os.path.join(POS_DATA_DIR, date_folder)

    os.makedirs(local_path, exist_ok=True)
    log_fn(f"  Syncing {s3_path} → {local_path}")

    result = subprocess.run(
        ["aws", "s3", "sync", s3_path, local_path],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        log_fn(f"  ❌ Failed to sync {date_folder}: {result.stderr.strip()}")
        return False

    if not os.listdir(local_path):
        shutil.rmtree(local_path)
        log_fn(f"  ⚠️ No data for {date_folder}, folder not kept.")
        return True

    log_fn(f"  ✅ Synced {date_folder}")
    return True