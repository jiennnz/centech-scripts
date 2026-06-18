"""Inspect the raw POS rows that make up any financial category for a given store + date.

Usage (interactive):
    python scripts/financial/pos_audit/inspect_pos_category.py

The script prompts for store, date, optional end-date (for cross-date CC lookup),
and category, then prints every contributing row plus the computed total.
Output is also written to CSV in scripts/financial/pos_audit/audits/.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pos_data").is_dir():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))

POS_DATA_DIR = ROOT / "pos_data"
AUDIT_OUT    = Path(__file__).resolve().parent / "audits"

# ── category registry ────────────────────────────────────────────────────────
# Each entry: (display_name, source, uses_cross_date)
# source: "payment" | "sts" | "store_txn" | "journal"

CATEGORIES: dict[str, tuple[str, bool]] = {
    "In-Store Credit Card":       ("payment", True),
    "In-Store Credit Card Tips":  ("payment", True),
    "Discarded CC":               ("payment", True),
    "Online Credit Card":         ("payment", False),
    "Online Credit Card Tips":    ("payment", False),
    "Gift Card":                  ("payment", False),
    "Gift Card Sold":             ("payment", False),
    "Online Gift Card":           ("payment", False),
    "Online Gift Card Tips":      ("payment", False),
    "House Account":              ("payment", False),
    "3rd Party - UberEats":       ("payment", False),
    "3rd Party - DoorDash":       ("payment", False),
    "3rd Party - GrubHub":        ("payment", False),
    "3rd Party - EZ Cater":       ("payment", False),
    "Subject to Tax":             ("sts",     False),
    "Non-Taxable Sales":          ("sts",     False),
    "3rd Party Tax Exempt":       ("sts",     False),
    "Tax Exempt":                 ("sts",     False),
    "Sales Tax":                  ("sts",     False),
    "Donation":                   ("sts",     False),
    "Register Audit":             ("store_txn", False),
    "Payout":                     ("store_txn", False),
    "Payin":                      ("store_txn", False),
    "Cash Over/Short Adjustment": ("journal", False),
}

_CAT_NAMES = list(CATEGORIES.keys())


# ── helpers ──────────────────────────────────────────────────────────────────

def _to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0.0)


def _load_store_id(day_dir: Path, store_number: str) -> str:
    df = pd.read_csv(day_dir / "Store.txt", sep="|", dtype=str)
    match = df[df["Store_Number"].str.strip() == store_number.strip()]
    if match.empty:
        raise ValueError(f"Store {store_number!r} not in {day_dir / 'Store.txt'}")
    return str(match["Store_ID"].iloc[0]).strip()


def _store_tickets(day_dir: Path, store_id: str) -> set[str]:
    st = pd.read_csv(day_dir / "Sales_Ticket.txt", sep="|", dtype=str)
    return set(st[st["Store_ID"].str.strip() == store_id]["Ticket_Number"].astype(str))


def _load_payments(
    day_dir: Path,
    store_tix: set[str],
    cross_dirs: list[Path] | None,
    date_str: str,
) -> pd.DataFrame:
    """Load Payment.txt rows for store tickets.

    For cross-date categories: scan additional folders and keep rows whose
    Payment_Date matches date_str (the original swipe date).
    For same-date categories: load only from day_dir.
    """
    target_date = pd.to_datetime(date_str).date()

    def _read_dir(d: Path, filter_by_pay_date: bool) -> pd.DataFrame | None:
        p = d / "Payment.txt"
        if not p.exists():
            return None
        df = pd.read_csv(p, sep="|", dtype=str)
        df = df[df["Ticket_Number"].astype(str).isin(store_tix)].copy()
        if df.empty:
            return None
        df["source_folder"] = d.name
        if filter_by_pay_date:
            df["_pay_date"] = pd.to_datetime(df["Payment_Date"], errors="coerce").dt.date
            df = df[df["_pay_date"] == target_date].drop(columns=["_pay_date"])
        return df if not df.empty else None

    frames: list[pd.DataFrame] = []

    if cross_dirs:
        for d in cross_dirs:
            chunk = _read_dir(d, filter_by_pay_date=True)
            if chunk is not None:
                frames.append(chunk)
    else:
        chunk = _read_dir(day_dir, filter_by_pay_date=False)
        if chunk is not None:
            frames.append(chunk)

    if not frames:
        return pd.DataFrame()

    pay = pd.concat(frames, ignore_index=True)
    for col in ["Tendered_Amount", "Change", "Tip_Amount"]:
        pay[col] = _to_num(pay[col])
    pay["_tlen"] = pay["Transaction_ID"].str.strip().str.len()
    return pay


# ── per-category inspectors ──────────────────────────────────────────────────

def _inspect_payment(category: str, pay: pd.DataFrame, store_tix: set[str], day_dir: Path, store_id: str) -> tuple[pd.DataFrame, float, str]:
    """Returns (rows_df, total, debit_or_credit)."""

    if pay.empty:
        return pd.DataFrame(), 0.0, "debit"

    p14 = pay[pay["Payment_Type_ID"].str.strip() == "14"].copy()

    if category == "In-Store Credit Card":
        st = pd.read_csv(day_dir / "Sales_Ticket.txt", sep="|", dtype=str)
        status8 = set(
            st[(st["Store_ID"].str.strip() == store_id) & (st["Status_ID"].str.strip() == "8")]
            ["Ticket_Number"].astype(str)
        )
        shape = (
            ((p14["_tlen"] == 6) & (p14["Tip_Paid"].str.strip() == "True"))
            | ((p14["_tlen"] == 32) & (p14["Tip_Paid"].str.strip() == "False"))
            | (p14["_tlen"] == 4)
        )
        rows = p14[
            shape
            & (p14["Processing_Status_ID"].str.strip() == "4")
            & ~p14["Ticket_Number"].astype(str).isin(status8)
        ].copy()
        rows["_contribution"] = rows["Tendered_Amount"] - rows["Change"] + rows["Tip_Amount"]
        total = float(rows["_contribution"].sum())
        return rows, total, "debit"

    if category == "In-Store Credit Card Tips":
        shape = (
            p14["_tlen"].isin([4, 6])
            | ((p14["_tlen"] == 32) & (p14["Tip_Paid"].str.strip() == "False"))
        )
        rows = p14[shape & (p14["Processing_Status_ID"].str.strip() == "4") & (p14["Tip_Amount"] != 0)].copy()
        rows["_contribution"] = rows["Tip_Amount"]
        total = float(rows["_contribution"].sum())
        return rows, total, "credit"

    if category == "Discarded CC":
        shape = (
            ((p14["_tlen"] == 6) & (p14["Tip_Paid"].str.strip() == "True"))
            | ((p14["_tlen"] == 32) & (p14["Tip_Paid"].str.strip() == "False"))
            | (p14["_tlen"] == 4)
        )
        rows = p14[shape & (p14["Processing_Status_ID"].str.strip() == "9")].copy()
        rows["_contribution"] = rows["Tendered_Amount"] - rows["Change"] + rows["Tip_Amount"]
        total = float(rows["_contribution"].sum())
        return rows, total, "debit"

    if category == "Online Credit Card":
        rows = p14[(p14["_tlen"] == 32) & (p14["Tip_Paid"].str.strip() == "True")].copy()
        rows["_contribution"] = rows["Tendered_Amount"] + rows["Tip_Amount"]
        total = float(rows["_contribution"].sum())
        return rows, total, "debit"

    if category == "Online Credit Card Tips":
        p14_3 = pay[pay["Payment_Type_ID"].str.strip().isin(["14", "3"])].copy()
        rows = p14_3[(p14_3["_tlen"] == 32) & (p14_3["Tip_Paid"].str.strip() == "True")].copy()
        rows["_contribution"] = rows["Tip_Amount"]
        total = float(rows["_contribution"].sum())
        return rows, total, "credit"

    if category == "Gift Card":
        p5 = pay[pay["Payment_Type_ID"].str.strip() == "5"].copy()
        rows = p5[p5["_tlen"] == 6].copy()
        rows["_contribution"] = rows["Tendered_Amount"]
        total = float(rows["_contribution"].sum())
        return rows, total, "debit"

    if category == "Gift Card Sold":
        st = pd.read_csv(day_dir / "Sales_Ticket.txt", sep="|", dtype=str)
        sts = pd.read_csv(day_dir / "Sales_Ticket_Summary.txt", sep="|", dtype=str)
        status8 = set(st[(st["Store_ID"].str.strip() == store_id) & (st["Status_ID"].str.strip() == "8")]["Ticket_Number"].astype(str))
        gc_rows = p14[p14["Ticket_Number"].astype(str).isin(status8)].copy()
        gc_rows["_contribution"] = gc_rows["Tendered_Amount"]
        for col in ["Taxable_Amount", "Non_Taxable_Amount", "Total"]:
            sts[col] = _to_num(sts[col])
        sts_mask = (
            sts["Ticket_Number"].astype(str).isin(status8)
            & (sts["Category_ID"].str.strip() == "1")
            & (sts["Taxable_Amount"] == 0)
            & (sts["Non_Taxable_Amount"] > 0)
        )
        sts_rows = sts[sts_mask].copy()
        sts_rows["_contribution"] = sts_rows["Non_Taxable_Amount"]
        gc_pay_total = float(gc_rows["_contribution"].sum())
        sts_total = float(sts_rows["_contribution"].sum())
        combined = pd.concat([
            gc_rows.assign(_source="Payment"),
            sts_rows.assign(_source="STS"),
        ], ignore_index=True)
        return combined, gc_pay_total + sts_total, "credit"

    if category == "Online Gift Card":
        p5 = pay[pay["Payment_Type_ID"].str.strip() == "5"].copy()
        rows = p5[p5["_tlen"] == 32].copy()
        rows["_contribution"] = rows["Tendered_Amount"] + rows["Tip_Amount"]
        total = float(rows["_contribution"].sum())
        return rows, total, "debit"

    if category == "Online Gift Card Tips":
        st = pd.read_csv(day_dir / "Sales_Ticket.txt", sep="|", dtype=str)
        tt5 = set(st[(st["Store_ID"].str.strip() == store_id) & (st["Ticket_Type_ID"].str.strip() == "5")]["Ticket_Number"].astype(str))
        paid = set(pay["Ticket_Number"].astype(str))
        valid = store_tix & tt5 & paid
        p5 = pay[pay["Payment_Type_ID"].str.strip() == "5"].copy()
        rows = p5[
            (p5["Payment_Name_ID"].str.strip() == "8")
            & p5["Ticket_Number"].astype(str).isin(valid)
        ].copy()
        rows["_contribution"] = rows["Tip_Amount"]
        total = float(rows["_contribution"].sum())
        return rows, total, "credit"

    if category == "House Account":
        rows = pay[pay["Payment_Type_ID"].str.strip() == "7"].copy()
        rows["_contribution"] = rows["Tendered_Amount"]
        total = float(rows["_contribution"].sum())
        return rows, total, "debit"

    p13_map = {
        "3rd Party - UberEats": "4001",
        "3rd Party - DoorDash": "4004",
        "3rd Party - GrubHub":  "4003",
        "3rd Party - EZ Cater": "74",
    }
    if category in p13_map:
        p13 = pay[pay["Payment_Type_ID"].str.strip() == "13"].copy()
        rows = p13[p13["Name"].str.strip() == p13_map[category]].copy()
        rows["_contribution"] = rows["Tendered_Amount"]
        total = float(rows["_contribution"].sum())
        return rows, total, "debit"

    return pd.DataFrame(), 0.0, "debit"


def _inspect_sts(category: str, day_dir: Path, store_tix: set[str], all_paid: set[str]) -> tuple[pd.DataFrame, float, str]:
    st  = pd.read_csv(day_dir / "Sales_Ticket.txt", sep="|", dtype=str)
    sts = pd.read_csv(day_dir / "Sales_Ticket_Summary.txt", sep="|", dtype=str)
    for col in ["Taxable_Amount", "Non_Taxable_Amount", "Total"]:
        sts[col] = _to_num(sts[col])

    store_paid    = store_tix & all_paid
    non_exempt    = set(st[st["Tax_Exempt"].str.strip() == "False"]["Ticket_Number"].astype(str))
    exempt        = set(st[st["Tax_Exempt"].str.strip() == "True"]["Ticket_Number"].astype(str))
    tt8           = set(st[st["Ticket_Type_ID"].str.strip() == "8"]["Ticket_Number"].astype(str))
    tt17          = set(st[st["Ticket_Type_ID"].str.strip().isin(["1", "7"])]["Ticket_Number"].astype(str))
    status8       = set(st[st["Status_ID"].str.strip() == "8"]["Ticket_Number"].astype(str))

    spec: dict[str, tuple[set, list[str], str, str]] = {
        "Subject to Tax":      (store_paid & non_exempt,              ["1", "2"], "Taxable_Amount",     "credit"),
        "Non-Taxable Sales":   (store_paid - (store_paid & status8),  ["1", "2", "7"], "mixed",         "credit"),
        "3rd Party Tax Exempt":(store_paid & exempt & tt8,            ["1", "2"], "Taxable_Amount",     "credit"),
        "Tax Exempt":          (store_paid & exempt & tt17,           ["1", "2"], "Taxable_Amount",     "credit"),
        "Sales Tax":           (store_paid & non_exempt,              ["5"],      "Total",              "credit"),
        "Donation":            (store_paid,                           ["7"],      "Total",              "credit"),
    }

    if category not in spec:
        return pd.DataFrame(), 0.0, "credit"

    ticket_set, cat_ids, field, side = spec[category]
    mask = sts["Ticket_Number"].astype(str).isin(ticket_set) & sts["Category_ID"].str.strip().isin(cat_ids)
    rows = sts[mask].copy()

    if field == "mixed":
        # Non-Taxable: cat 1 - cat 2 non_taxable, minus cat 7 total
        r1 = rows[rows["Category_ID"].str.strip() == "1"]["Non_Taxable_Amount"].sum()
        r2 = rows[rows["Category_ID"].str.strip() == "2"]["Non_Taxable_Amount"].sum()
        r7 = rows[rows["Category_ID"].str.strip() == "7"]["Total"].sum()
        total = float(r1 - r2 - r7)
        rows["_contribution"] = rows.apply(
            lambda r: r["Non_Taxable_Amount"] if r["Category_ID"].strip() in ["1", "2"] else -r["Total"],
            axis=1,
        )
    elif category in {"Subject to Tax", "3rd Party Tax Exempt", "Tax Exempt"}:
        r1 = rows[rows["Category_ID"].str.strip() == "1"][field].sum()
        r2 = rows[rows["Category_ID"].str.strip() == "2"][field].sum()
        total = float(r1 - r2)
        rows["_contribution"] = rows.apply(
            lambda r: r[field] if r["Category_ID"].strip() == "1" else -r[field],
            axis=1,
        )
    else:
        rows["_contribution"] = rows[field]
        total = float(rows["_contribution"].sum())

    return rows, total, side


def _inspect_store_txn(category: str, txn: pd.DataFrame, store_id: str, date_str: str) -> tuple[pd.DataFrame, float, str]:
    store_txn = txn[
        (txn["Store_ID"].str.strip() == store_id)
        & (txn["Transaction_Date"].str.startswith(date_str))
    ]
    txn_map = {
        "Register Audit": ("Register Audit",  "debit"),
        "Payout":         ("Store Payout",    "debit"),
        "Payin":          ("Payins",          "credit"),
    }
    txn_name, side = txn_map[category]
    rows = store_txn[store_txn["Transaction_Type_Name"].str.strip() == txn_name].copy()

    if category == "Register Audit":
        if rows.empty:
            return rows, 0.0, side
        last = rows.tail(1).copy()
        last["_contribution"] = _to_num(last["Amount"])
        return last, float(last["_contribution"].iloc[0]), side

    if category == "Payin":
        rows = rows[rows["Status"].str.strip() == "Inserted"].copy()

    rows["_contribution"] = _to_num(rows["Amount"])
    return rows, float(rows["_contribution"].sum()), side


def _inspect_journal(day_dir: Path, store_number: str) -> tuple[pd.DataFrame, float, str]:
    dj = pd.read_csv(day_dir / "DailyJournal.txt", sep="|", dtype=str)
    store_dj = dj[dj["Store_Number"].str.strip() == str(store_number)]
    ra = store_dj[store_dj["Action"].str.strip() == "Register Audit"]
    value = 0.0
    if not ra.empty:
        comment = ra["Comments"].iloc[-1]
        m = re.search(r"Over/Short:\s*([-\d.]+)", str(comment))
        if m:
            value = float(m.group(1))
    side = "credit" if value >= 0 else "debit"
    return ra, abs(value), side


# ── display ──────────────────────────────────────────────────────────────────

def _print_rows(rows: pd.DataFrame, total: float, side: str, category: str) -> None:
    print(f"\n{'─' * 70}")
    print(f"  Category : {category}")
    print(f"  Side     : {side.upper()}")
    print(f"  Rows     : {len(rows)}")
    print(f"  Total    : ${total:,.2f}")
    print(f"{'─' * 70}")
    if rows.empty:
        print("  (no rows matched)")
    else:
        with pd.option_context("display.max_columns", None, "display.width", 200, "display.float_format", "${:,.2f}".format):
            print(rows.to_string(index=False))
    print()


# ── main ─────────────────────────────────────────────────────────────────────

def _pick_category() -> str:
    print("\nAvailable categories:")
    for i, name in enumerate(_CAT_NAMES, 1):
        src, cross = CATEGORIES[name]
        tag = " [cross-date]" if cross else ""
        print(f"  {i:2d}. {name}{tag}")
    raw = input("\nCategory number or name: ").strip()
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(_CAT_NAMES):
            return _CAT_NAMES[idx]
    for name in _CAT_NAMES:
        if raw.lower() == name.lower():
            return name
    raise ValueError(f"Unknown category: {raw!r}")


def main() -> None:
    print("=== POS Category Inspector ===")

    available = sorted(
        d.name for d in POS_DATA_DIR.iterdir()
        if d.is_dir() and len(d.name) == 10 and d.name[4] == "-"
    ) if POS_DATA_DIR.is_dir() else []
    if available:
        print(f"Available dates: {available[0]} → {available[-1]} ({len(available)} days)")

    date_str    = input("Date (YYYY-MM-DD): ").strip()
    store_number = input("Store number: ").strip()
    category    = _pick_category()

    _, uses_cross = CATEGORIES[category]
    end_date_str = date_str
    if uses_cross:
        end_date_str = input(f"Scan folders up to (YYYY-MM-DD, default={date_str}): ").strip() or date_str

    day_dir = POS_DATA_DIR / date_str
    if not day_dir.is_dir():
        print(f"ERROR: {day_dir} does not exist.")
        return

    store_id  = _load_store_id(day_dir, store_number)
    store_tix = _store_tickets(day_dir, store_id)
    print(f"\nStore ID={store_id}  Tickets in date folder={len(store_tix)}")

    src, uses_cross = CATEGORIES[category]

    # Build cross-date folder list if needed
    cross_dirs: list[Path] | None = None
    if uses_cross and end_date_str >= date_str:
        cross_dirs = sorted(
            d for d in POS_DATA_DIR.iterdir()
            if d.is_dir() and len(d.name) == 10 and d.name[4] == "-"
            and date_str <= d.name <= end_date_str
        )
        print(f"Cross-date scan: {len(cross_dirs)} folder(s) up to {end_date_str}")

    if src == "payment":
        pay = _load_payments(day_dir, store_tix, cross_dirs, date_str)
        all_paid = set(pay["Ticket_Number"].astype(str)) if not pay.empty else set()
        rows, total, side = _inspect_payment(category, pay, store_tix, day_dir, store_id)

    elif src == "sts":
        pay_same = _load_payments(day_dir, store_tix, None, date_str)
        all_paid = set(pay_same["Ticket_Number"].astype(str)) if not pay_same.empty else set()
        rows, total, side = _inspect_sts(category, day_dir, store_tix, all_paid)

    elif src == "store_txn":
        txn = pd.read_csv(day_dir / "Store_Transactions.txt", sep="|", dtype=str)
        rows, total, side = _inspect_store_txn(category, txn, store_id, date_str)

    elif src == "journal":
        rows, total, side = _inspect_journal(day_dir, store_number)

    else:
        print(f"Unknown source: {src}")
        return

    _print_rows(rows, total, side, category)

    # Write CSV
    out_dir = AUDIT_OUT / date_str / store_number
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_cat = category.replace(" ", "_").replace("/", "-")
    out_path = out_dir / f"inspect_{safe_cat}.csv"
    rows.to_csv(out_path, index=False)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
