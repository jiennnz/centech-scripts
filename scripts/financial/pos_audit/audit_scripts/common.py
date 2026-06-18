from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

DEFAULT_LOOKBACK_DAYS = 10
DEFAULT_LOOKAHEAD_DAYS = 30


@dataclass(frozen=True)
class ScanWindow:
    target_date: date
    start_date: date
    end_date: date

    @property
    def target_date_str(self) -> str:
        return self.target_date.isoformat()

    @property
    def start_date_str(self) -> str:
        return self.start_date.isoformat()

    @property
    def end_date_str(self) -> str:
        return self.end_date.isoformat()

    @property
    def scan_dates(self) -> list[date]:
        current = self.start_date
        out: list[date] = []
        while current <= self.end_date:
            out.append(current)
            current += timedelta(days=1)
        return out


@dataclass(frozen=True)
class SalesContext:
    target_date_str: str
    store_number: str
    store_id: str
    store_st: pd.DataFrame
    sts: pd.DataFrame
    store_tix: set[str]
    store_paid: set[str]
    non_exempt_tix: set[str]
    exempt_tix: set[str]
    tt_8_tix: set[str]
    tt_1_7_tix: set[str]
    tt_5_tix: set[str]
    status_8_tix: set[str]
    cancelled_tix: set[str]
    refund_tix: set[str]


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pos_data").is_dir():
            return parent
    return Path(__file__).resolve().parents[4]


def script_root() -> Path:
    return Path(__file__).resolve().parents[1]


def list_available_dates(pos_data_dir: Path) -> list[str]:
    if not pos_data_dir.is_dir():
        return []
    return sorted(
        d.name
        for d in pos_data_dir.iterdir()
        if d.is_dir() and len(d.name) == 10 and d.name[4] == "-"
    )


def build_scan_window(
    target_date_str: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS,
) -> ScanWindow:
    target = date.fromisoformat(target_date_str)
    return ScanWindow(
        target_date=target,
        start_date=target - timedelta(days=lookback_days),
        end_date=target + timedelta(days=lookahead_days),
    )


def prompt_audit_inputs(title: str, pos_data_dir: Path) -> tuple[ScanWindow, str]:
    print(f"=== {title} ===")
    available_dates = list_available_dates(pos_data_dir)
    if available_dates:
        print(
            f"Available dates: {available_dates[0]} -> {available_dates[-1]} "
            f"({len(available_dates)} days)"
        )
    target_date_str = input("Start date to audit (YYYY-MM-DD): ").strip()
    store_number = input("Store number (e.g. 4064): ").strip()
    window = build_scan_window(target_date_str)
    print(
        "Scan window: "
        f"{window.start_date_str} -> {window.end_date_str} "
        f"(10-day backcheck, 30-day forward check)"
    )
    return window, store_number


def to_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def normalize_bool(raw: object) -> str:
    s = str(raw or "").strip()
    if s.lower() in {"true", "false"}:
        return "True" if s.lower() == "true" else "False"
    return s


def load_store_id(day_dir: Path, store_number: str) -> str:
    store = pd.read_csv(day_dir / "Store.txt", sep="|", dtype=str)
    match = store[
        store["Store_Number"].astype(str).str.strip() == str(store_number).strip()
    ]
    if match.empty:
        raise ValueError(f"Store {store_number} not found in {day_dir / 'Store.txt'}")
    return str(match["Store_ID"].iloc[0]).strip()


def existing_scan_dirs(pos_data_dir: Path, scan_dates: list[date]) -> list[Path]:
    return [pos_data_dir / d.isoformat() for d in scan_dates if (pos_data_dir / d.isoformat()).is_dir()]


def output_dir_for(category_slug: str, target_date_str: str, store_number: str) -> Path:
    root = script_root()
    return (
        root
        / "audits"
        / category_slug
        / target_date_str
        / str(store_number)
    )


def _build_cross_date_sales_context(
    pos_data_dir: Path, scan_dates: list[date]
) -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
    st_frames: list[pd.DataFrame] = []
    sts_frames: list[pd.DataFrame] = []
    for day in scan_dates:
        day_dir = pos_data_dir / day.isoformat()
        try:
            st = pd.read_csv(day_dir / "Sales_Ticket.txt", sep="|", dtype=str)
            sts = pd.read_csv(day_dir / "Sales_Ticket_Summary.txt", sep="|", dtype=str)
            pay = pd.read_csv(
                day_dir / "Payment.txt",
                sep="|",
                dtype=str,
                usecols=["Ticket_Number", "Payment_Date"],
            )
        except (FileNotFoundError, ValueError):
            continue

        pay["_pay_date"] = pd.to_datetime(pay["Payment_Date"], errors="coerce").dt.strftime("%Y-%m-%d")
        ticket_dates = pay[["Ticket_Number", "_pay_date"]].dropna().drop_duplicates()
        if ticket_dates.empty:
            continue

        st["sales_ticket_pos_date_found"] = day.isoformat()
        sts["pos_date_found"] = day.isoformat()
        st_attr = st.merge(ticket_dates, on="Ticket_Number", how="inner")
        ticket_pos_dates = st_attr[
            ["Ticket_Number", "sales_ticket_pos_date_found"]
        ].drop_duplicates()
        sts_attr = sts.merge(ticket_dates, on="Ticket_Number", how="inner").merge(
            ticket_pos_dates, on="Ticket_Number", how="left"
        )
        if not st_attr.empty:
            st_frames.append(st_attr)
        if not sts_attr.empty:
            sts_frames.append(sts_attr)

    if not st_frames or not sts_frames:
        return {}

    st_all = pd.concat(st_frames, ignore_index=True).drop_duplicates()
    sts_all = pd.concat(sts_frames, ignore_index=True).drop_duplicates()
    out: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for date_str, st_grp in st_all.groupby("_pay_date"):
        sts_grp = sts_all[sts_all["_pay_date"] == date_str]
        out[date_str] = (
            st_grp.drop(columns=["_pay_date"]).reset_index(drop=True),
            sts_grp.drop(columns=["_pay_date"]).reset_index(drop=True),
        )
    return out


def _build_cross_date_payments(
    pos_data_dir: Path, scan_dates: list[date]
) -> dict[str, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for day in scan_dates:
        pay_path = pos_data_dir / day.isoformat() / "Payment.txt"
        if not pay_path.exists():
            continue
        try:
            frames.append(pd.read_csv(pay_path, sep="|", dtype=str))
        except Exception:
            continue
    if not frames:
        return {}
    combined = pd.concat(frames, ignore_index=True)
    combined["_pay_date"] = pd.to_datetime(
        combined["Payment_Date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    return {
        date_str: grp.reset_index(drop=True)
        for date_str, grp in combined.groupby("_pay_date")
    }


def _build_cross_date_txns(
    pos_data_dir: Path, scan_dates: list[date]
) -> dict[str, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for day in scan_dates:
        txn_path = pos_data_dir / day.isoformat() / "Store_Transactions.txt"
        if not txn_path.exists():
            continue
        try:
            frames.append(pd.read_csv(txn_path, sep="|", dtype=str))
        except Exception:
            continue
    if not frames:
        return {}
    combined = pd.concat(frames, ignore_index=True)
    combined["Amount"] = to_num(combined["Amount"])
    combined["_txn_date"] = pd.to_datetime(
        combined["Transaction_Date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    return {
        date_str: grp.reset_index(drop=True)
        for date_str, grp in combined.groupby("_txn_date")
    }


def load_sales_context(
    pos_data_dir: Path,
    target_date_str: str,
    store_number: str,
    scan_dates: list[date],
) -> SalesContext:
    base_dir = pos_data_dir / target_date_str
    if not base_dir.is_dir():
        raise ValueError(f"Date directory not found: {base_dir}")

    store_id = load_store_id(base_dir, store_number)
    cross_date_sales = _build_cross_date_sales_context(pos_data_dir, scan_dates)
    cross_date_pay = _build_cross_date_payments(pos_data_dir, scan_dates)

    if target_date_str not in cross_date_sales:
        raise ValueError(f"No cross-date sales context found for {target_date_str}")

    store_st, sts = cross_date_sales[target_date_str]
    pay = cross_date_pay.get(target_date_str, pd.DataFrame())

    store_st = store_st[store_st["Store_ID"].astype(str).str.strip() == str(store_id)]
    store_tix = set(store_st["Ticket_Number"].astype(str))
    all_paid = set(pay["Ticket_Number"].astype(str)) if not pay.empty else set()
    store_paid = store_tix & all_paid

    def ticket_attr(col: str, values: list[str]) -> set[str]:
        if col not in store_st.columns:
            return set()
        return set(
            store_st[store_st[col].astype(str).str.strip().isin(values)]["Ticket_Number"].astype(str)
        )

    for col in ["Taxable_Amount", "Non_Taxable_Amount", "Total"]:
        if col in sts.columns:
            sts[col] = to_num(sts[col])

    return SalesContext(
        target_date_str=target_date_str,
        store_number=str(store_number),
        store_id=str(store_id),
        store_st=store_st.reset_index(drop=True),
        sts=sts.reset_index(drop=True),
        store_tix=store_tix,
        store_paid=store_paid,
        non_exempt_tix=ticket_attr("Tax_Exempt", ["False"]),
        exempt_tix=ticket_attr("Tax_Exempt", ["True"]),
        tt_8_tix=ticket_attr("Ticket_Type_ID", ["8"]),
        tt_1_7_tix=ticket_attr("Ticket_Type_ID", ["1", "7"]),
        tt_5_tix=ticket_attr("Ticket_Type_ID", ["5"]),
        status_8_tix=ticket_attr("Status_ID", ["8"]),
        cancelled_tix=ticket_attr("Status_ID", ["2"]),
        refund_tix=ticket_attr("Refund", ["True"]),
    )


def sts_sum(sts: pd.DataFrame, ticket_set: set[str], cat_ids: list[int], field: str) -> float:
    if sts.empty or not ticket_set:
        return 0.0
    mask = sts["Ticket_Number"].astype(str).isin(ticket_set) & sts["Category_ID"].astype(str).isin(
        [str(c) for c in cat_ids]
    )
    return float(sts.loc[mask, field].sum())


def load_store_transactions(
    pos_data_dir: Path,
    target_date_str: str,
    store_number: str,
    scan_dates: list[date],
) -> tuple[str, pd.DataFrame]:
    base_dir = pos_data_dir / target_date_str
    if not base_dir.is_dir():
        raise ValueError(f"Date directory not found: {base_dir}")
    store_id = load_store_id(base_dir, store_number)
    by_date = _build_cross_date_txns(pos_data_dir, scan_dates)
    txn = by_date.get(target_date_str, pd.DataFrame()).copy()
    if txn.empty:
        return store_id, txn
    txn = txn[txn["Store_ID"].astype(str).str.strip() == str(store_id)].copy()
    return store_id, txn.reset_index(drop=True)
