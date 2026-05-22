"""Batch POS verifier: computes all financial categories for every store × date
from raw POS text files and writes a CSV matching the centech/client export format.

The generated CSV can be passed as --centech-csv or --source-csv to run.py for
QA-vs-CenTech or QA-vs-Client comparison runs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from tqdm import tqdm

# Canonical category names — must match category_rows keys in org yaml files.
# "Online Credit card" (lowercase c) = row 13 sub-item.
# "Online Credit Card" (row 12) is a template formula row; not output here.
_CATEGORIES = {
    "subj_tax":        "Subject to Tax",
    "non_tax":         "Non-Taxable Sales",
    "exempt_3p":       "3rd Party Tax Exempt",
    "tax_exempt":      "Tax Exempt",
    "register_audit":  "Register Audit",
    "sales_tax":       "Sales Tax",
    "instore_cc":      "In-Store Credit Card",
    "payout":          "Payout",
    "online_cc":       "Online Credit card",
    "online_gc":       "Online Gift Card",
    "online_cc_tips":  "Online Credit Card Tips",
    "instore_cc_tips": "In-Store Credit Card Tips",
    "online_gc_tips":  "Online Gift Card Tips",
    "gift_card":       "Gift Card",
    "gift_card_sold":  "Gift Card Sold",
    "uber_eats":       "3rd Party - UberEats",
    "doordash":        "3rd Party - DoorDash",
    "grubhub":         "3rd Party - GrubHub",
    "ez_cater":        "3rd Party - EZ Cater",
    "house_account":   "House Account",
    "donation":        "Donation",
    "payin":           "Payin",
    "cos_adj":         "Cash Over/Short Adjustment",
    "discarded_cc":    "Discarded CC",
}


@dataclass(frozen=True)
class VerifierConfig:
    pos_data_dir: Path
    stores: list[str]
    start_date: date
    end_date: date
    output_csv_path: Path


def _build_cross_date_payments(pos_data_dir: Path, all_dates: list) -> dict[str, pd.DataFrame]:
    """Concat Payment.txt across all date folders, return dict keyed by Payment_Date (YYYY-MM-DD).

    Pre-partitioning by date means each store-day call filters a tiny slice instead of
    scanning the full multi-date frame.
    """
    frames = []
    for d in all_dates:
        pay_path = pos_data_dir / d.isoformat() / "Payment.txt"
        if pay_path.exists():
            try:
                frames.append(pd.read_csv(pay_path, sep="|", dtype=str))
            except Exception:
                pass
    if not frames:
        return {}
    combined = pd.concat(frames, ignore_index=True)
    for col in ["Tendered_Amount", "Change", "Tip_Amount"]:
        combined[col] = pd.to_numeric(combined[col], errors="coerce").fillna(0)
    combined["_tlen"] = combined["Transaction_ID"].str.strip().str.len()
    combined["_pay_date"] = (
        pd.to_datetime(combined["Payment_Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    )
    return {
        date_str: grp.reset_index(drop=True)
        for date_str, grp in combined.groupby("_pay_date")
    }


def _build_cross_date_txns(pos_data_dir: Path, all_dates: list) -> dict[str, pd.DataFrame]:
    """Concat Store_Transactions.txt across all date folders, return dict keyed by Transaction_Date (YYYY-MM-DD).

    Payouts recorded in a later folder but dated to an earlier day are captured here
    and attributed to their Transaction_Date, matching client export behaviour.
    """
    frames = []
    for d in all_dates:
        txn_path = pos_data_dir / d.isoformat() / "Store_Transactions.txt"
        if txn_path.exists():
            try:
                frames.append(pd.read_csv(txn_path, sep="|", dtype=str))
            except Exception:
                pass
    if not frames:
        return {}
    combined = pd.concat(frames, ignore_index=True)
    combined["Amount"] = pd.to_numeric(combined["Amount"], errors="coerce").fillna(0)
    combined["_txn_date"] = (
        pd.to_datetime(combined["Transaction_Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    )
    return {
        date_str: grp.reset_index(drop=True)
        for date_str, grp in combined.groupby("_txn_date")
    }


def _build_cross_date_sales_context(pos_data_dir: Path, all_dates: list) -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
    """Build Sales_Ticket/Summary slices keyed by Payment_Date.

    Tickets can be created in one POS folder but paid just after midnight, so the
    client export may post the sale, tax, and tender on the payment date. The
    verifier needs the ticket attributes and summary rows from the source folder,
    attributed to the payment date found in Payment.txt.
    """
    st_frames = []
    sts_frames = []
    for d in all_dates:
        data_dir = pos_data_dir / d.isoformat()
        try:
            st = pd.read_csv(data_dir / "Sales_Ticket.txt", sep="|", dtype=str)
            sts = pd.read_csv(data_dir / "Sales_Ticket_Summary.txt", sep="|", dtype=str)
            pay = pd.read_csv(
                data_dir / "Payment.txt",
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

        st_attr = st.merge(ticket_dates, on="Ticket_Number", how="inner")
        sts_attr = sts.merge(ticket_dates, on="Ticket_Number", how="inner")
        if not st_attr.empty:
            st_frames.append(st_attr)
        if not sts_attr.empty:
            sts_frames.append(sts_attr)

    if not st_frames or not sts_frames:
        return {}

    st_all = pd.concat(st_frames, ignore_index=True).drop_duplicates()
    sts_all = pd.concat(sts_frames, ignore_index=True).drop_duplicates()

    by_date: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for date_str, st_grp in st_all.groupby("_pay_date"):
        sts_grp = sts_all[sts_all["_pay_date"] == date_str]
        by_date[date_str] = (
            st_grp.drop(columns=["_pay_date"]).reset_index(drop=True),
            sts_grp.drop(columns=["_pay_date"]).reset_index(drop=True),
        )
    return by_date


def compute_store_day(
    store_number: int,
    date_str: str,
    pos_data_dir: Path,
    cross_date_pay: pd.DataFrame | None = None,
    cross_date_txn: pd.DataFrame | None = None,
    cross_date_sales: tuple[pd.DataFrame, pd.DataFrame] | None = None,
) -> list[tuple[str, float, float]] | None:
    """Compute all financial categories for one store + date.

    Returns list of (category_name, debit, credit), or None if data unavailable.
    Date format for pos_data_dir subdirectory: YYYY-MM-DD.
    cross_date_pay: pre-filtered payment slice for this date only
      (from _build_cross_date_payments[date_str]). ISCC/ISCCT/Discarded CC use this
      so settled transactions land on their Payment_Date, not the folder date.
    cross_date_txn: pre-filtered Store_Transactions slice for this date only
      (from _build_cross_date_txns[date_str]). Payouts dated to this day but written
      in a later folder are captured here.
    """
    data_dir = pos_data_dir / date_str
    if not data_dir.is_dir():
        return None

    try:
        st        = pd.read_csv(data_dir / "Sales_Ticket.txt",         sep="|", dtype=str)
        sts       = pd.read_csv(data_dir / "Sales_Ticket_Summary.txt", sep="|", dtype=str)
        pay       = pd.read_csv(data_dir / "Payment.txt",              sep="|", dtype=str)
        txn       = pd.read_csv(data_dir / "Store_Transactions.txt",   sep="|", dtype=str)
        dj        = pd.read_csv(data_dir / "DailyJournal.txt",         sep="|", dtype=str)
        store_ref = pd.read_csv(data_dir / "Store.txt",                sep="|", dtype=str)
    except FileNotFoundError:
        return None

    match = store_ref[store_ref["Store_Number"].str.strip() == str(store_number)]
    if match.empty:
        return None
    store_id = int(match["Store_ID"].iloc[0])

    for col in ["Taxable_Amount", "Non_Taxable_Amount", "Total"]:
        sts[col] = pd.to_numeric(sts[col], errors="coerce").fillna(0)
    for col in ["Tendered_Amount", "Change", "Tip_Amount"]:
        pay[col] = pd.to_numeric(pay[col], errors="coerce").fillna(0)
    txn["Amount"] = pd.to_numeric(txn["Amount"], errors="coerce").fillna(0)

    store_st   = st[st["Store_ID"] == str(store_id)]
    store_tix  = set(store_st["Ticket_Number"].unique())
    if cross_date_sales is not None:
        xst, xsts = cross_date_sales
        if not xst.empty:
            store_st = xst[xst["Store_ID"] == str(store_id)]
            store_tix = set(store_st["Ticket_Number"].unique())
            if not xsts.empty:
                sts = xsts.copy()
                for col in ["Taxable_Amount", "Non_Taxable_Amount", "Total"]:
                    sts[col] = pd.to_numeric(sts[col], errors="coerce").fillna(0)

    # Only count tickets whose payment is attributed to this date.
    # Payments in a different folder but with this Payment_Date belong to this day.
    if cross_date_pay is not None and not cross_date_pay.empty:
        all_paid = set(cross_date_pay["Ticket_Number"].unique())
    else:
        _pay_dates = pd.to_datetime(pay["Payment_Date"], errors="coerce").dt.strftime("%Y-%m-%d")
        all_paid = set(pay[_pay_dates == date_str]["Ticket_Number"].unique())
    store_paid = store_tix & all_paid

    def ticket_attr(col: str, values: list[str]) -> set:
        return set(store_st[store_st[col].str.strip().isin(values)]["Ticket_Number"])

    non_exempt_tix = ticket_attr("Tax_Exempt",    ["False"])
    exempt_tix     = ticket_attr("Tax_Exempt",    ["True"])
    tt_8_tix       = ticket_attr("Ticket_Type_ID", ["8"])
    tt_1_7_tix     = ticket_attr("Ticket_Type_ID", ["1", "7"])
    tt_5_tix       = ticket_attr("Ticket_Type_ID", ["5"])
    status_8_tix   = ticket_attr("Status_ID",      ["8"])
    refund_tix     = ticket_attr("Refund",          ["True"]) if "Refund" in store_st.columns else set()

    def sts_sum(ticket_set: set, cat_ids: list, field: str) -> float:
        mask = sts["Ticket_Number"].isin(ticket_set) & sts["Category_ID"].isin(
            [str(c) for c in cat_ids]
        )
        return float(sts.loc[mask, field].sum())

    if cross_date_pay is not None and not cross_date_pay.empty:
        pay_store = cross_date_pay[cross_date_pay["Ticket_Number"].isin(store_paid)].copy()
    else:
        pay_store = pay[pay["Ticket_Number"].isin(store_paid)].copy()
    pay_store["_tlen"] = pay_store["Transaction_ID"].str.strip().str.len()

    # Slice already filtered to this date by run(); just scope to store's tickets.
    # Falls back to same-date pay_store when cross_date_pay not provided.
    # Exclude gift-card-sold (status_8) from ISCC: their CC payments count in gift_card_sold.
    # Exclude ONLINE refund tickets (tlen=32) from ISCC: the Tip_Paid=False refund row would
    # misclassify into ISCC when both rows belong in Online CC. In-store refunds (tlen=4/6)
    # stay in ISCC — client includes them as negative rows that net correctly.
    _online_refund_tix = set(
        pay_store[pay_store["Ticket_Number"].isin(refund_tix) & (pay_store["_tlen"] == 32)]["Ticket_Number"].unique()
    ) if refund_tix else set()
    _iscc_excluded = status_8_tix | _online_refund_tix
    _non_gc_tix = store_tix - _iscc_excluded
    _cross_date_mode = cross_date_pay is not None and not cross_date_pay.empty
    if _cross_date_mode:
        _cdp = cross_date_pay[cross_date_pay["Ticket_Number"].isin(_non_gc_tix)]
    else:
        _cdp = pay_store[~pay_store["Ticket_Number"].isin(_iscc_excluded)]

    def p(
        type_ids: list | None = None,
        name_ids: list | None = None,
        tlen=None,
        tip_paid: bool | None = None,
        ticket_set: set | None = None,
    ) -> pd.DataFrame:
        df = pay_store.copy()
        if ticket_set is not None:
            df = df[df["Ticket_Number"].isin(ticket_set)]
        if type_ids:
            df = df[df["Payment_Type_ID"].isin([str(x) for x in type_ids])]
        if name_ids:
            df = df[df["Payment_Name_ID"].isin([str(x) for x in name_ids])]
        if tlen is not None:
            if isinstance(tlen, list):
                df = df[df["_tlen"].isin(tlen)]
            else:
                df = df[df["_tlen"] == tlen]
        if tip_paid is not None:
            df = df[df["Tip_Paid"].str.strip() == ("True" if tip_paid else "False")]
        return df

    # Use cross-date slice when available so payouts recorded in later folders
    # but dated to this day are captured. Falls back to same-folder txn filtered by date.
    if cross_date_txn is not None and not cross_date_txn.empty:
        store_txn = cross_date_txn[cross_date_txn["Store_ID"] == str(store_id)]
    else:
        store_txn = txn[
            (txn["Store_ID"] == str(store_id))
            & (txn["Transaction_Date"].str.startswith(date_str))
        ]

    # ── Sales ──────────────────────────────────────────────────────────────
    paid_non_exempt = store_paid & non_exempt_tix
    subj_tax = sts_sum(paid_non_exempt, [1], "Taxable_Amount") - sts_sum(paid_non_exempt, [2], "Taxable_Amount")

    paid_no_status8 = store_paid - (store_paid & status_8_tix)
    non_tax = (
        sts_sum(paid_no_status8, [1], "Non_Taxable_Amount")
        - sts_sum(paid_no_status8, [2], "Non_Taxable_Amount")
        - sts_sum(paid_no_status8, [7], "Total")
    )

    paid_exempt_tt8 = store_paid & exempt_tix & tt_8_tix
    exempt_3p = sts_sum(paid_exempt_tt8, [1], "Taxable_Amount") - sts_sum(paid_exempt_tt8, [2], "Taxable_Amount")

    paid_exempt_tt17 = store_paid & exempt_tix & tt_1_7_tix
    tax_exempt = sts_sum(paid_exempt_tt17, [1], "Taxable_Amount") - sts_sum(paid_exempt_tt17, [2], "Taxable_Amount")

    donation = sts_sum(store_paid, [7], "Total")
    sales_tax = sts_sum(store_paid & non_exempt_tix, [5], "Total")

    # ── Cash Over/Short ────────────────────────────────────────────────────
    dj_store = dj[dj["Store_Number"].str.strip() == str(store_number)]
    ra_dj    = dj_store[dj_store["Action"].str.strip() == "Register Audit"]
    cash_over_short = 0.0
    _ra_dj_cancelled = False
    if len(ra_dj):
        row = ra_dj.iloc[-1]
        comment = row["Comments"]
        m = re.search(r"Over/Short:\s*([-\d.]+)", str(comment))
        if m:
            cos_val = float(m.group(1))
            dj_amount = pd.to_numeric(row.get("Amount", None), errors="coerce")
            if pd.notna(dj_amount) and dj_amount == cos_val:
                _ra_dj_cancelled = True
            else:
                cash_over_short = cos_val

    # ── Store_Transactions ─────────────────────────────────────────────────
    payin_rows = store_txn[
        (store_txn["Transaction_Type_Name"].str.strip() == "Payins")
        & (store_txn["Status"].str.strip() == "Inserted")
    ]
    payin = float(payin_rows["Amount"].sum())

    ra_rows      = store_txn[store_txn["Transaction_Type_Name"].str.strip() == "Register Audit"]
    register_audit = float(ra_rows["Amount"].iloc[-1]) if len(ra_rows) else 0.0

    if _ra_dj_cancelled:
        register_audit = 0.0

    # Exclude payouts that were subsequently voided — both the Inserted and Void rows share
    # the same Transaction_Date so they both land in store_txn; voided IDs net to zero.
    _voided_payout_ids = set(
        store_txn[
            (store_txn["Transaction_Type_Name"].str.strip() == "Store Payout")
            & (store_txn["Status"].str.strip() == "Void")
        ]["Transaction_ID"].unique()
    )
    payout_rows = store_txn[
        (store_txn["Transaction_Type_Name"].str.strip() == "Store Payout")
        & (store_txn["Status"].str.strip() == "Inserted")
        & (~store_txn["Transaction_ID"].isin(_voided_payout_ids))
    ]
    payout = float(payout_rows["Amount"].abs().sum())

    # ── Tips ───────────────────────────────────────────────────────────────
    online_cc_tips  = float(p(type_ids=[14, 3], tlen=32, tip_paid=True)["Tip_Amount"].sum())

    # ISCCT / ISCC / Discarded CC use cross-date payments attributed by Payment_Date
    _cdp_14 = _cdp[_cdp["Payment_Type_ID"] == "14"] if not _cdp.empty else pd.DataFrame(columns=_cdp.columns)
    _iscct_shape = (
        _cdp_14["_tlen"].isin([4, 6])
        | ((_cdp_14["_tlen"] == 32) & (_cdp_14["Tip_Paid"].str.strip() == "False"))
    )
    instore_tip_all = _cdp_14[_iscct_shape & (_cdp_14["Processing_Status_ID"].str.strip() == "4")]
    instore_cc_tips = float(instore_tip_all[instore_tip_all["Tip_Amount"] != 0]["Tip_Amount"].sum())
    online_gc_tips  = float(p(type_ids=[5], name_ids=[8], ticket_set=store_paid & tt_5_tix)["Tip_Amount"].sum())

    # ── Gift Card Sold ─────────────────────────────────────────────────────
    # No type filter — gift cards can be purchased with any tender (cash, CC, etc.)
    _gc_tix = store_paid & status_8_tix
    _gc_pay = p(ticket_set=_gc_tix)
    gc_sold_pay = float((_gc_pay["Tendered_Amount"] - _gc_pay["Change"]).sum())
    gc_sold_sts = 0.0
    if not (store_paid & status_8_tix):
        gc_mask = (
            sts["Ticket_Number"].isin(store_paid & status_8_tix)
            & (sts["Category_ID"] == "1")
            & (sts["Taxable_Amount"] == 0)
            & (sts["Non_Taxable_Amount"] > 0)
        )
        gc_sold_sts = float(sts.loc[gc_mask, "Non_Taxable_Amount"].sum())
    gift_card_sold = gc_sold_pay + gc_sold_sts
    # Only the CC-paid portion of gift card sales belongs in ISCC; cash-paid GC purchases
    # go through their own tender type and must not inflate the CC total.
    _gc_cc_pay = p(type_ids=[14], ticket_set=_gc_tix)
    gc_sold_cc = float((_gc_cc_pay["Tendered_Amount"] - _gc_cc_pay["Change"]).sum())

    # ── Credit Card ────────────────────────────────────────────────────────
    # Online refund tickets (tlen=32, Refund=True) stay in online CC — their negative
    # rows net against the original charge, matching client OLO deposit behaviour.
    # (_online_refund_tix exclusion applies to ISCC only, via _iscc_excluded.)
    online_cc_rows = pay_store[
        (pay_store["Payment_Type_ID"] == "14")
        & (pay_store["_tlen"] == 32)
        & (
            (pay_store["Tip_Paid"].str.strip() == "True")
            | (pay_store["Ticket_Number"].isin(_online_refund_tix))
        )
    ]
    online_cc      = float((online_cc_rows["Tendered_Amount"] + online_cc_rows["Tip_Amount"]).sum())

    p14 = _cdp_14
    _iscc_shape = (
        ((p14["_tlen"] == 6) & (p14["Tip_Paid"].str.strip() == "True"))
        | ((p14["_tlen"] == 32) & (p14["Tip_Paid"].str.strip() == "False"))
        | (p14["_tlen"] == 4)
    )
    instore_cc_rows   = p14[_iscc_shape & (p14["Processing_Status_ID"].str.strip() == "4")]
    discarded_cc_rows = p14[_iscc_shape & (p14["Processing_Status_ID"].str.strip() == "9")]

    instore_cc = float(
        (instore_cc_rows["Tendered_Amount"] - instore_cc_rows["Change"] + instore_cc_rows["Tip_Amount"]).sum()
    ) + gc_sold_cc

    discarded_cc = float(
        (discarded_cc_rows["Tendered_Amount"] - discarded_cc_rows["Change"] + discarded_cc_rows["Tip_Amount"]).sum()
    )

    gift_card = float(p(type_ids=[5], tlen=6)["Tendered_Amount"].sum())

    online_gc_rows = p(type_ids=[5], tlen=32)
    online_gc      = float((online_gc_rows["Tendered_Amount"] + online_gc_rows["Tip_Amount"]).sum())

    house_account = float(p(type_ids=[7])["Tendered_Amount"].sum())

    # ── 3rd Party ─────────────────────────────────────────────────────────
    p13      = pay_store[pay_store["Payment_Type_ID"] == "13"]
    uber_eats = float(p13[p13["Name"].str.strip() == "4001"]["Tendered_Amount"].sum())
    doordash  = float(p13[p13["Name"].str.strip() == "4004"]["Tendered_Amount"].sum())
    grubhub   = float(p13[p13["Name"].str.strip() == "4003"]["Tendered_Amount"].sum())
    ez_cater  = float(p13[p13["Name"].str.strip().isin(["74", "4022"])]["Tendered_Amount"].sum())

    cos_dr = abs(cash_over_short) if cash_over_short < 0 else 0.0
    cos_cr = cash_over_short      if cash_over_short >= 0 else 0.0

    C = _CATEGORIES
    return [
        (C["subj_tax"],        0.0,           subj_tax),
        (C["non_tax"],         0.0,           non_tax),
        (C["exempt_3p"],       0.0,           exempt_3p),
        (C["tax_exempt"],      0.0,           tax_exempt),
        (C["register_audit"],  register_audit, 0.0),
        (C["sales_tax"],       0.0,           sales_tax),
        (C["instore_cc"],      instore_cc,    0.0),
        (C["payout"],          payout,        0.0),
        (C["online_cc"],       online_cc,     0.0),
        (C["online_gc"],       online_gc,     0.0),
        (C["online_cc_tips"],  0.0,           online_cc_tips),
        (C["instore_cc_tips"], 0.0,           instore_cc_tips),
        (C["online_gc_tips"],  0.0,           online_gc_tips),
        (C["gift_card"],       gift_card,     0.0),
        (C["gift_card_sold"],  0.0,           gift_card_sold),
        (C["uber_eats"],       uber_eats,     0.0),
        (C["doordash"],        doordash,      0.0),
        (C["grubhub"],         grubhub,       0.0),
        (C["ez_cater"],        ez_cater,      0.0),
        (C["house_account"],   house_account, 0.0),
        (C["donation"],        0.0,           donation),
        (C["payin"],           0.0,           payin),
        (C["cos_adj"],         cos_dr,        cos_cr),
        (C["discarded_cc"],    discarded_cc,  0.0),
    ]


def _run_task(args: tuple) -> tuple[str, str, list[tuple[str, float, float]] | None]:
    store_num, store_str, date_str, pos_data_dir, cdp_slice, cdt_slice, cds_slice = args
    result = compute_store_day(
        store_num,
        date_str,
        pos_data_dir,
        cross_date_pay=cdp_slice,
        cross_date_txn=cdt_slice,
        cross_date_sales=cds_slice,
    )
    return store_str, date_str, result


def run(config: VerifierConfig) -> int:
    """Generate pos_computed CSV for all stores × dates in range.

    CSV columns match centech/client export format:
      Date (MM/DD/YYYY), Class, Transaction Category, Debit, Credit

    Returns total row count written.
    """
    import os
    from concurrent.futures import ProcessPoolExecutor, as_completed

    all_dates: list[date] = []
    current = config.start_date
    while current <= config.end_date:
        all_dates.append(current)
        current += timedelta(days=1)

    # Extend scan window by 14 days past end_date so payments/transactions that settled
    # in later folders but are dated within the range are captured.
    _scan_end = config.end_date + timedelta(days=14)
    _scan_dates = list(all_dates)
    _extra = config.end_date + timedelta(days=1)
    while _extra <= _scan_end:
        _scan_dates.append(_extra)
        _extra += timedelta(days=1)

    tqdm.write("[verifier] Pre-loading cross-date payments for ISCC attribution...")
    cross_date_by_date = _build_cross_date_payments(config.pos_data_dir, _scan_dates)
    tqdm.write("[verifier] Pre-loading cross-date transactions for payout attribution...")
    cross_date_txn_by_date = _build_cross_date_txns(config.pos_data_dir, _scan_dates)
    tqdm.write("[verifier] Pre-loading cross-date sales tickets for payment-date attribution...")
    cross_date_sales_by_date = _build_cross_date_sales_context(config.pos_data_dir, _scan_dates)

    # Build task list — each task is one store × date
    tasks: list[tuple] = []
    for current in all_dates:
        date_str = current.isoformat()
        cdp_slice = cross_date_by_date.get(date_str)
        cdt_slice = cross_date_txn_by_date.get(date_str)
        cds_slice = cross_date_sales_by_date.get(date_str)
        for store in config.stores:
            try:
                store_num = int(store)
            except ValueError:
                tqdm.write(f"[verifier] Skipping non-numeric store: {store!r}")
                continue
            tasks.append((store_num, store, date_str, config.pos_data_dir, cdp_slice, cdt_slice, cds_slice))

    rows: list[dict] = []
    workers = min(os.cpu_count() or 1, len(tasks))
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_run_task, t): t for t in tasks}
        with tqdm(total=len(tasks), unit="store-day", desc="[verifier] Computing") as pbar:
            for future in as_completed(futures):
                store_str, date_str, result = future.result()
                date_fmt = date.fromisoformat(date_str).strftime("%m/%d/%Y")
                pbar.set_postfix_str(f"Store {store_str} | {date_str}")
                pbar.update(1)
                if result is None:
                    continue
                for category, debit, credit in result:
                    if debit == 0.0 and credit == 0.0:
                        continue
                    rows.append({
                        "Date":                 date_fmt,
                        "Class":                store_str,
                        "Transaction Category": category,
                        "Debit":                debit  if debit  else None,
                        "Credit":               credit if credit else None,
                    })

    config.output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=["Date", "Class", "Transaction Category", "Debit", "Credit"])
    df.to_csv(config.output_csv_path, index=False)
    return len(rows)
