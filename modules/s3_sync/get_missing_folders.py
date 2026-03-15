import os

from config import POS_DATA_DIR


def get_missing_folders(date_folders: list[str]) -> list[str]:
    """
    Returns folders that need syncing: missing or present but empty (no data).

    :param date_folders: List of date folder names to check
    :return: List of folder names that are missing or empty
    """
    missing = []
    for folder in date_folders:
        folder_path = os.path.join(POS_DATA_DIR, folder)
        if not os.path.exists(folder_path):
            missing.append(folder)
        elif not os.listdir(folder_path):
            missing.append(folder)
    return missing