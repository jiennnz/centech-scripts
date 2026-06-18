"""Payout diagnostic: dump all Store Payout rows for a store on a specific business date.

  --date   : the business date to audit (Transaction_Date == this)
  --end    : scan folders up to this date (catches rows recorded late but attributed to --date)

Usage:
    python scripts/financial/payout_diagnostic.py
    python scripts/financial/payout_diagnostic.py --store 4041 --date "Apr 6 2026" --end "Apr 30 2026"
    python scripts/financial/payout_diagnostic.py --store 4041 --date "Apr 6 2026" --end "Apr 30 2026" --pos-data-dir pos_data

Output: CSV with every Store Payout row where Transaction_Date == audit date, found across
all folders up to scan_end. Annotated with Is_Voided and Counted. Summary printed to console.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd
from dateutil import parser as date_parser

DEFAULT_POS_DIR = REPO_ROOT / "pos_data"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "scripts" / "financial" / "payout_audits"


# ── helpers ────────────────────────────────────────────────────────────────────

def _parse_date(raw: str) -> date:
    try:
        return date_parser.parse(raw, fuzzy=True).date()
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Could not parse date: {raw!r}") from exc


def _prompt_date(label: str) -> date:
    while True:
        raw = input(label).strip()
        if not raw:
            print("Input required.")
            continue
        try:
            return _parse_date(raw)
        except ValueError as exc:
            print(exc)


def _prompt_str(label: str) -> str:
    while True:
        raw = input(label).strip()
        if raw:
            return raw
        print("Input required.")


def _prompt_path(label: str, default: Path | None = None) -> Path:
    while True:
        suffix = f" [{default}]" if default else ""
        raw = input(f"{label}{suffix}: ").strip().strip('"')
        if not raw and default is not None:
            if default.is_dir():
                return default
            print(f"Default path not found: {default}")
            continue
        candidate = Path(raw)
        if candidate.is_dir():
            return candidate
        from_root = REPO_ROOT / candidate
        if from_root.is_dir():
            return from_root
        print(f"Directory not found: {candidate}")


# ── core logic ─────────────────────────────────────────────────────────────────

def _resolve_store_id(pos_data_dir: Path, scan_dates: list[date], store_number: str) -> str | None:
    """Read Store.txt from any available folder to resolve Store_Number -> Store_ID."""
    for d in scan_dates:
        store_path = pos_data_dir / d.isoformat() / "Store.txt"
        if not store_path.exists():
            continue
        try:
            df = pd.read_csv(store_path, sep="|", dtype=str)
            match = df[df["Store_Number"].str.strip() == store_number.strip()]
            if not match.empty:
                return str(match["Store_ID"].iloc[0]).strip()
        except Exception:
            continue
    return None


def run_diagnostic(
    pos_data_dir: Path,
    store_number: str,
    audit_date: date,
    scan_end: date,
    output_path: Path,
) -> None:
    # Scan folders: audit_date through scan_end (user controls the window)
    scan_dates: list[date] = []
    d = audit_date
    while d <= scan_end:
        scan_dates.append(d)
        d += timedelta(days=1)

    audit_date_str = audit_date.isoformat()

    print(f"[payout] Resolving Store_ID for store {store_number!r}...")
    store_id = _resolve_store_id(pos_data_dir, scan_dates, store_number)
    if store_id is None:
        raise SystemExit(
            f"Store {store_number!r} not found in any Store.txt under {pos_data_dir}. "
            "Check store number and pos_data_dir."
        )
    print(f"[payout] Store_ID = {store_id}")
    print(f"[payout] Audit date : {audit_date_str}")
    print(f"[payout] Scan window: {audit_date_str} – {scan_end.isoformat()} ({len(scan_dates)} folders)")

    # Load Store_Transactions.txt across all folders in scan window
    frames: list[pd.DataFrame] = []
    missing_folders: list[str] = []
    for d in scan_dates:
        txn_path = pos_data_dir / d.isoformat() / "Store_Transactions.txt"
        if not txn_path.exists():
            missing_folders.append(d.isoformat())
            continue
        try:
            df = pd.read_csv(txn_path, sep="|", dtype=str)
            df["_folder_date"] = d.isoformat()
            frames.append(df)
        except Exception as exc:
            print(f"[payout] Warning: could not read {txn_path}: {exc}")

    if missing_folders:
        print(f"[payout] No Store_Transactions.txt in {len(missing_folders)} folder(s) "
              f"(first: {missing_folders[0]})")

    if not frames:
        raise SystemExit(f"No Store_Transactions.txt files found under {pos_data_dir}")

    combined = pd.concat(frames, ignore_index=True)
    combined["Amount"] = pd.to_numeric(combined["Amount"], errors="coerce").fillna(0)

    # Normalize Transaction_Date to YYYY-MM-DD
    combined["_txn_date"] = (
        pd.to_datetime(combined["Transaction_Date"], errors="coerce")
        .dt.strftime("%Y-%m-%d")
    )

    # Scope: this store, Store Payout type, Transaction_Date == audit_date
    store_mask  = combined["Store_ID"].str.strip() == store_id
    payout_mask = combined["Transaction_Type_Name"].str.strip() == "Store Payout"
    date_mask   = combined["_txn_date"] == audit_date_str

    scope = combined[store_mask & payout_mask & date_mask].copy()

    if scope.empty:
        print(f"[payout] No Store Payout rows found for store {store_number} on {audit_date_str}.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=[
            "Folder_Date", "Transaction_Date", "Store_ID", "Store_Number",
            "Transaction_ID", "Status", "Amount", "ABS_Amount",
            "Is_Voided", "Counted",
        ]).to_csv(output_path, index=False)
        print(f"[payout] Empty CSV written -> {output_path}")
        return

    scope["_status_clean"] = scope["Status"].str.strip()
    scope["_tid_clean"]    = scope["Transaction_ID"].str.strip()

    # Voided IDs: any Transaction_ID that has a Void row
    voided_ids: set[str] = set(
        scope[scope["_status_clean"] == "Void"]["_tid_clean"].unique()
    )

    scope["Is_Voided"] = (
        (scope["_status_clean"] == "Inserted") & scope["_tid_clean"].isin(voided_ids)
    )
    scope["ABS_Amount"]  = scope["Amount"].abs()
    scope["Counted"]     = (scope["_status_clean"] == "Inserted") & ~scope["Is_Voided"]
    scope["Store_Number"] = store_number

    # Build output columns
    out_cols_src = [
        "_folder_date", "_txn_date",
        "Store_ID", "Store_Number",
        "Transaction_ID", "Status",
        "Amount", "ABS_Amount",
        "Is_Voided", "Counted",
    ]
    # Extra columns from source file not already captured
    skip = (
        set(out_cols_src)
        | {"_status_clean", "_tid_clean", "Store_Number", "Transaction_Date", "Amount"}
    )
    extra_cols = [c for c in scope.columns if c not in skip and not c.startswith("_")]

    out_df = (
        scope[out_cols_src + extra_cols]
        .rename(columns={"_folder_date": "Folder_Date", "_txn_date": "Transaction_Date"})
        .reset_index(drop=True)
        .sort_values(["Transaction_ID", "Status"], ignore_index=True)
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(output_path, index=False)

    # Console summary
    counted_rows = scope[scope["Counted"]]
    total_payout = float(counted_rows["ABS_Amount"].sum())

    print(f"\n{'─'*50}")
    print(f"Store {store_number} ({store_id})  |  Audit: {audit_date_str}")
    print(f"{'─'*50}")
    print(f"Total rows    : {len(scope)}")
    print(f"  Inserted    : {(scope['_status_clean'] == 'Inserted').sum()}")
    print(f"  Void        : {(scope['_status_clean'] == 'Void').sum()}")
    print(f"  Counted     : {int(scope['Counted'].sum())}")
    print(f"  Voided out  : {int(scope['Is_Voided'].sum())}")
    print(f"{'─'*30}")
    print(f"  PAYOUT TOTAL: {total_payout:>10.2f}")
    print(f"\nOutput        : {output_path}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Payout diagnostic — dump raw Store Payout rows for an audit date.")
    p.add_argument("--store",        type=str, default=None, help="Store number (e.g. 4041)")
    p.add_argument("--date",         type=str, default=None, help="Date to audit (e.g. 'Apr 6 2026')")
    p.add_argument("--end",          type=str, default=None, help="Scan folders until this date (e.g. 'Apr 30 2026')")
    p.add_argument("--pos-data-dir", type=str, default=None, help="Path to pos_data root")
    p.add_argument("--output",       type=str, default=None, help="Output CSV path")
    return p


def main() -> None:
    args = _build_parser().parse_args()

    store_number = args.store or _prompt_str("Store number: ")

    audit_date = (
        _parse_date(args.date) if args.date
        else _prompt_date("Date to audit (e.g. 'Apr 6 2026'): ")
    )
    scan_end = (
        _parse_date(args.end) if args.end
        else _prompt_date("Scan folders until (e.g. 'Apr 30 2026'): ")
    )
    if audit_date > scan_end:
        raise SystemExit("Audit date must be <= scan end date.")

    if args.pos_data_dir:
        pos_data_dir = Path(args.pos_data_dir)
        if not pos_data_dir.is_dir():
            pos_data_dir = REPO_ROOT / args.pos_data_dir
        if not pos_data_dir.is_dir():
            raise SystemExit(f"pos_data_dir not found: {args.pos_data_dir}")
    else:
        pos_data_dir = _prompt_path("POS data directory", DEFAULT_POS_DIR)

    if args.output:
        output_path = Path(args.output)
    else:
        slug = f"{store_number}_{audit_date.isoformat()}"
        output_path = DEFAULT_OUTPUT_DIR / slug / "payout_rows.csv"

    run_diagnostic(
        pos_data_dir=pos_data_dir,
        store_number=store_number,
        audit_date=audit_date,
        scan_end=scan_end,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()
