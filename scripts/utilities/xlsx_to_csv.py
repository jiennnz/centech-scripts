import argparse
import sys
from pathlib import Path

import pandas as pd


def _is_empty(v) -> bool:
    return pd.isna(v) or str(v).strip() in ('', 'nan')


def _merge_continuation_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Rows with empty first column are continuations — append their values to previous full row."""
    rows = df.values.tolist()
    cols = list(df.columns)
    merged = []
    for row in rows:
        if _is_empty(row[0]):
            if not merged:
                continue
            for j, v in enumerate(row):
                if not _is_empty(v):
                    prev = merged[-1][j]
                    merged[-1][j] = f"{prev} | {v}" if not _is_empty(prev) else str(v)
        else:
            merged.append([None if _is_empty(v) else v for v in row])
    return pd.DataFrame(merged, columns=cols)


def convert(xlsx_path: Path, output_dir: Path, all_sheets: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    xf = pd.ExcelFile(xlsx_path)
    sheets = xf.sheet_names if all_sheets else [xf.sheet_names[0]]

    for sheet in sheets:
        df = pd.read_excel(xf, sheet_name=sheet)
        df = df.apply(lambda col: col.map(lambda v: ''.join(c for c in v if ord(c) >= 32) if isinstance(v, str) else v))
        df = _merge_continuation_rows(df)
        stem = xlsx_path.stem
        name = f"{stem}_{sheet}.csv" if all_sheets else f"{stem}.csv"
        out = output_dir / name
        df.to_csv(out, index=False, lineterminator='\n')
        print(f"  -> {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert xlsx to CSV.")
    parser.add_argument("input", nargs="+", help="xlsx file(s) to convert")
    parser.add_argument("-o", "--output-dir", default=None, help="output directory (default: same as input)")
    parser.add_argument("-a", "--all-sheets", action="store_true", help="convert all sheets (default: first sheet only)")
    args = parser.parse_args()

    for path_str in args.input:
        xlsx_path = Path(path_str).resolve()
        if not xlsx_path.exists():
            print(f"ERROR: not found: {xlsx_path}", file=sys.stderr)
            continue
        out_dir = Path(args.output_dir).resolve() if args.output_dir else xlsx_path.parent
        print(f"Converting: {xlsx_path}")
        convert(xlsx_path, out_dir, args.all_sheets)


if __name__ == "__main__":
    main()
