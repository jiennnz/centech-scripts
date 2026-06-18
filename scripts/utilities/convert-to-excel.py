import os
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


def detect_encoding(file_path):
    """
    Detect file encoding by trying common ones first, then falling back to chardet.
    Order matters: cp1252 before latin1 because latin1 never raises UnicodeDecodeError
    (it accepts all 256 byte values) but silently misreads Windows-1252 characters
    like 0x92 (curly apostrophe), 0xa2 (cent sign), 0x96 (en-dash), etc.
    """
    for encoding in ['utf-8-sig', 'utf-8', 'cp1252', 'utf-16']:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                f.read()
            return encoding
        except (UnicodeDecodeError, UnicodeError):
            continue

    try:
        import chardet
        with open(file_path, 'rb') as f:
            raw = f.read()
        result = chardet.detect(raw)
        if result and result['encoding'] and result['confidence'] > 0.5:
            return result['encoding']
    except ImportError:
        pass

    return 'latin1'


def format_folder_name(folder_name):
    """Convert YYYY-MM-DD folder name to 'Mon DD YYYY' format (e.g. Apr 03 2026)."""
    try:
        dt = datetime.strptime(folder_name, "%Y-%m-%d")
        return dt.strftime("%b %d %Y")
    except ValueError:
        return folder_name


def read_pipe_delimited(file_path, encoding):
    """
    Read a pipe-delimited file that may have inconsistent column counts.
    Uses a two-pass approach: first sniff the max column count, then read
    with enough named columns so no row is ever 'too wide'.
    """
    with open(file_path, 'r', encoding=encoding, errors='replace') as f:
        max_cols = max((line.count('|') + 1 for line in f), default=1)

    return pd.read_csv(
        file_path,
        sep='|',
        encoding=encoding,
        header=None,
        dtype=str,
        low_memory=False,
        names=range(max_cols),   # pre-declare enough columns for the widest row
        on_bad_lines='warn',     # safety net for truly malformed lines
    )


def process_folder(args):
    """Process a single folder into an Excel file."""
    folder_path, folder_name, output_dir = args
    display_name = format_folder_name(folder_name)
    output_file = os.path.join(output_dir, f"{display_name}.xlsx")

    txt_files = [f for f in os.listdir(folder_path) if f.endswith('.txt')]
    if not txt_files:
        return f"Skipped (no .txt files): {folder_name}"

    try:
        with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
            for file_name in txt_files:
                file_path = os.path.join(folder_path, file_name)
                sheet_name = os.path.splitext(file_name)[0][:31]

                encoding = detect_encoding(file_path)
                try:
                    df = read_pipe_delimited(file_path, encoding)
                    df.to_excel(writer, sheet_name=sheet_name, index=False, header=False)
                except Exception as e:
                    print(f"Error processing {file_name} in {folder_name}: {e}")

        return f"Done: {folder_name} -> {display_name}.xlsx"
    except Exception as e:
        return f"Failed: {folder_name} - {e}"


def prompt_date_range():
    """Ask the user for a start and end date, return as datetime objects."""
    date_fmt = "%Y-%m-%d"
    print("\n=== POS Data Converter ===")
    print("Enter a date range to filter folders (format: YYYY-MM-DD).")
    print("Leave both blank to process ALL dates.\n")

    while True:
        start_input = input("Start date (e.g. 2026-03-01) or press Enter to skip: ").strip()
        end_input   = input("End date   (e.g. 2026-04-30) or press Enter to skip: ").strip()

        start_date = end_date = None
        try:
            if start_input:
                start_date = datetime.strptime(start_input, date_fmt)
            if end_input:
                end_date = datetime.strptime(end_input, date_fmt)
        except ValueError:
            print("  x Invalid date format. Please use YYYY-MM-DD.\n")
            continue

        if start_date and end_date and start_date > end_date:
            print("  x Start date must be on or before end date.\n")
            continue

        return start_date, end_date


def process_all_folders(max_workers=4):
    script_path = Path(__file__).resolve()
    repo_root = next((p for p in script_path.parents if (p / "pos_data").is_dir()), script_path.parents[2])
    pos_data_folder = repo_root / "pos_data"
    output_dir = script_path.parents[1] / "data" / "excel_conversions"
    os.makedirs(output_dir, exist_ok=True)

    if not os.path.isdir(pos_data_folder):
        print(f"Could not find pos_data folder at: {pos_data_folder}")
        return

    start_date, end_date = prompt_date_range()

    subfolders = []
    skipped = []
    for f in sorted(os.listdir(pos_data_folder)):
        full_path = os.path.join(pos_data_folder, f)
        if not os.path.isdir(full_path):
            continue
        try:
            folder_date = datetime.strptime(f, "%Y-%m-%d")
            if start_date and folder_date < start_date:
                skipped.append(f)
                continue
            if end_date and folder_date > end_date:
                skipped.append(f)
                continue
            subfolders.append(f)
        except ValueError:
            subfolders.append(f)

    if not subfolders:
        print("\nNo folders matched the selected date range.")
        return

    label_start = start_date.strftime("%b %d %Y") if start_date else "beginning"
    label_end   = end_date.strftime("%b %d %Y")   if end_date   else "end"
    print(f"\nRange   : {label_start} -> {label_end}")
    print(f"Matched : {len(subfolders)} folder(s)")
    if skipped:
        print(f"Skipped : {len(skipped)} folder(s) outside range")
    print()

    tasks = [
        (os.path.join(pos_data_folder, f), f, output_dir)
        for f in subfolders
    ]

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_folder, task): task[1] for task in tasks}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing folders"):
            print(future.result())


if __name__ == "__main__":
    process_all_folders(max_workers=4)
