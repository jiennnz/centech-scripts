from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT_ROOT = (
    REPO_ROOT
    / "scripts"
    / "financial"
    / "pos_audit"
    / "audits"
    / "pos_folder_comparison"
)


@dataclass
class Table:
    headers: list[str]
    rows: list[tuple[str, ...]]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_table(path: Path) -> Table:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as source:
        reader = csv.reader(source, delimiter="|")
        headers = next(reader, [])
        rows = [tuple(row) for row in reader]
    return Table(headers=headers, rows=rows)


def normalized_row(row: tuple[str, ...], width: int) -> tuple[str, ...]:
    return row[:width] + ("",) * max(0, width - len(row))


def identifier_columns(headers: list[str]) -> list[str]:
    preferred = [
        "Ticket_Number",
        "Transaction_ID",
        "Payment_Item_ID",
        "Employee_ID",
        "Store_ID",
        "Register_ID",
        "Client_ID",
    ]
    candidates = [name for name in preferred if name in headers]
    candidates.extend(
        name
        for name in headers
        if name not in candidates
        and (
            name.endswith("_ID")
            or name.endswith("_Number")
            or name in {"Creation_Date", "Create_Date", "Start", "End"}
        )
    )
    return candidates[:10]


def is_unique_key(
    rows: list[tuple[str, ...]], indexes: tuple[int, ...], width: int
) -> bool:
    seen: set[tuple[str, ...]] = set()
    for raw_row in rows:
        row = normalized_row(raw_row, width)
        key = tuple(row[index] for index in indexes)
        if not any(key) or key in seen:
            return False
        seen.add(key)
    return True


def infer_key_columns(left: Table, right: Table) -> list[str]:
    if left.headers != right.headers or not left.headers:
        return []
    candidates = identifier_columns(left.headers)
    indexes = {name: left.headers.index(name) for name in candidates}
    width = len(left.headers)
    for size in range(1, min(3, len(candidates)) + 1):
        for names in combinations(candidates, size):
            key_indexes = tuple(indexes[name] for name in names)
            if is_unique_key(left.rows, key_indexes, width) and is_unique_key(
                right.rows, key_indexes, width
            ):
                return list(names)
    return []


def keyed_rows(table: Table, key_columns: list[str]) -> dict[tuple[str, ...], tuple[str, ...]]:
    width = len(table.headers)
    indexes = tuple(table.headers.index(name) for name in key_columns)
    result = {}
    for raw_row in table.rows:
        row = normalized_row(raw_row, width)
        result[tuple(row[index] for index in indexes)] = row
    return result


def write_csv(path: Path, headers: list[str], rows: Iterable[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def compare_folders(left_dir: Path, right_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    left_files = {path.name: path for path in left_dir.iterdir() if path.is_file()}
    right_files = {path.name: path for path in right_dir.iterdir() if path.is_file()}

    summary_rows: list[dict[str, object]] = []
    row_diff_rows: list[dict[str, object]] = []
    field_diff_rows: list[dict[str, object]] = []

    for filename in sorted(left_files.keys() | right_files.keys()):
        left_path = left_files.get(filename)
        right_path = right_files.get(filename)
        if left_path is None or right_path is None:
            summary_rows.append(
                {
                    "file": filename,
                    "status": "only_left" if right_path is None else "only_right",
                    "left_rows": "",
                    "right_rows": "",
                    "added_rows": "",
                    "removed_rows": "",
                    "changed_rows": "",
                    "key_columns": "",
                }
            )
            continue

        if file_hash(left_path) == file_hash(right_path):
            row_count = max(sum(1 for _ in left_path.open("rb")) - 1, 0)
            summary_rows.append(
                {
                    "file": filename,
                    "status": "identical",
                    "left_rows": row_count,
                    "right_rows": row_count,
                    "added_rows": 0,
                    "removed_rows": 0,
                    "changed_rows": 0,
                    "key_columns": "",
                }
            )
            continue

        left = read_table(left_path)
        right = read_table(right_path)
        if left.headers != right.headers:
            summary_rows.append(
                {
                    "file": filename,
                    "status": "headers_changed",
                    "left_rows": len(left.rows),
                    "right_rows": len(right.rows),
                    "added_rows": "",
                    "removed_rows": "",
                    "changed_rows": "",
                    "key_columns": "",
                }
            )
            field_diff_rows.append(
                {
                    "file": filename,
                    "key": "",
                    "column": "__headers__",
                    "left_value": json.dumps(left.headers),
                    "right_value": json.dumps(right.headers),
                }
            )
            continue

        key_columns = infer_key_columns(left, right)
        changed_count = 0
        added_count = 0
        removed_count = 0

        if key_columns:
            left_by_key = keyed_rows(left, key_columns)
            right_by_key = keyed_rows(right, key_columns)
            left_keys = set(left_by_key)
            right_keys = set(right_by_key)
            added_keys = right_keys - left_keys
            removed_keys = left_keys - right_keys
            common_keys = left_keys & right_keys
            added_count = len(added_keys)
            removed_count = len(removed_keys)

            for key in sorted(removed_keys):
                row_diff_rows.append(
                    {
                        "file": filename,
                        "change": "removed",
                        "key": json.dumps(key),
                        "row": json.dumps(
                            dict(zip(left.headers, left_by_key[key])), ensure_ascii=True
                        ),
                        "count": 1,
                    }
                )
            for key in sorted(added_keys):
                row_diff_rows.append(
                    {
                        "file": filename,
                        "change": "added",
                        "key": json.dumps(key),
                        "row": json.dumps(
                            dict(zip(right.headers, right_by_key[key])), ensure_ascii=True
                        ),
                        "count": 1,
                    }
                )
            for key in sorted(common_keys):
                left_row = left_by_key[key]
                right_row = right_by_key[key]
                if left_row == right_row:
                    continue
                changed_count += 1
                for index, column in enumerate(left.headers):
                    if left_row[index] != right_row[index]:
                        field_diff_rows.append(
                            {
                                "file": filename,
                                "key": json.dumps(key),
                                "column": column,
                                "left_value": left_row[index],
                                "right_value": right_row[index],
                            }
                        )
        else:
            width = len(left.headers)
            left_counter = Counter(normalized_row(row, width) for row in left.rows)
            right_counter = Counter(normalized_row(row, width) for row in right.rows)
            for row, count in (left_counter - right_counter).items():
                removed_count += count
                row_diff_rows.append(
                    {
                        "file": filename,
                        "change": "removed",
                        "key": "",
                        "row": json.dumps(dict(zip(left.headers, row)), ensure_ascii=True),
                        "count": count,
                    }
                )
            for row, count in (right_counter - left_counter).items():
                added_count += count
                row_diff_rows.append(
                    {
                        "file": filename,
                        "change": "added",
                        "key": "",
                        "row": json.dumps(dict(zip(right.headers, row)), ensure_ascii=True),
                        "count": count,
                    }
                )

        status = (
            "rows_changed"
            if added_count or removed_count or changed_count
            else "formatting_changed"
        )
        summary_rows.append(
            {
                "file": filename,
                "status": status,
                "left_rows": len(left.rows),
                "right_rows": len(right.rows),
                "added_rows": added_count,
                "removed_rows": removed_count,
                "changed_rows": changed_count,
                "key_columns": ",".join(key_columns),
            }
        )

    write_csv(
        output_dir / "file_summary.csv",
        [
            "file",
            "status",
            "left_rows",
            "right_rows",
            "added_rows",
            "removed_rows",
            "changed_rows",
            "key_columns",
        ],
        summary_rows,
    )
    write_csv(
        output_dir / "row_differences.csv",
        ["file", "change", "key", "row", "count"],
        row_diff_rows,
    )
    write_csv(
        output_dir / "field_differences.csv",
        ["file", "key", "column", "left_value", "right_value"],
        field_diff_rows,
    )

    identical = sum(row["status"] == "identical" for row in summary_rows)
    different = len(summary_rows) - identical
    print(f"Compared {len(summary_rows)} file(s): {identical} identical, {different} different.")
    print(f"Audit output: {output_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare two POS export folders and write file/row/field audit CSVs."
    )
    parser.add_argument("left", type=Path, help="Original or earlier POS folder")
    parser.add_argument("right", type=Path, help="Updated or later POS folder")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Audit output directory",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    left = args.left.resolve()
    right = args.right.resolve()
    if not left.is_dir():
        raise SystemExit(f"Left folder not found: {left}")
    if not right.is_dir():
        raise SystemExit(f"Right folder not found: {right}")
    output_dir = args.output_dir or DEFAULT_AUDIT_ROOT / f"{left.name}_vs_{right.name}"
    compare_folders(left, right, output_dir.resolve())


if __name__ == "__main__":
    main()
