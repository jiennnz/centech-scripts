"""Compute all Book1 financial categories for a given store and date.

Usage:
    python verify_4078_full.py <store_number> <date>
    python verify_4078_full.py 4078 2026-04-01
"""

import re
import sys
from pathlib import Path

import pandas as pd

if len(sys.argv) != 3:
    print("Usage: python verify_4078_full.py <store_number> <date YYYY-MM-DD>")
    sys.exit(1)

STORE_NUMBER = int(sys.argv[1])
DATE = sys.argv[2]


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pos_data").is_dir():
            return parent
    return Path(__file__).resolve().parents[3]


DATA_DIR = _repo_root() / "pos_data" / DATE

# ── Load files ─────────────────────────────────────────────────────────────
st = pd.read_csv(DATA_DIR / "Sales_Ticket.txt", sep="|", dtype=str)
sts = pd.read_csv(DATA_DIR / "Sales_Ticket_Summary.txt", sep="|", dtype=str)
pay = pd.read_csv(DATA_DIR / "Payment.txt", sep="|", dtype=str)
txn = pd.read_csv(DATA_DIR / "Store_Transactions.txt", sep="|", dtype=str)
dj = pd.read_csv(DATA_DIR / "DailyJournal.txt", sep="|", dtype=str)
store_ref = pd.read_csv(DATA_DIR / "Store.txt", sep="|", dtype=str)

# Resolve Store_ID from Store_Number
match = store_ref[store_ref["Store_Number"].str.strip() == str(STORE_NUMBER)]
if match.empty:
    print(f"Store {STORE_NUMBER} not found in {DATE} data.")
    sys.exit(1)
STORE_ID = int(match["Store_ID"].iloc[0])

# Numeric casts
for c in ["Taxable_Amount", "Non_Taxable_Amount", "Total"]:
    sts[c] = pd.to_numeric(sts[c], errors="coerce").fillna(0)
for c in ["Tendered_Amount", "Change", "Tip_Amount"]:
    pay[c] = pd.to_numeric(pay[c], errors="coerce").fillna(0)
txn["Amount"] = pd.to_numeric(txn["Amount"], errors="coerce").fillna(0)

# ── Base ticket sets ────────────────────────────────────────────────────────
store_st = st[st["Store_ID"] == str(STORE_ID)]
all_paid = set(pay["Ticket_Number"].unique())
store_tix = set(store_st["Ticket_Number"].unique())
store_paid = store_tix & all_paid  # paid tickets for this store


# Ticket metadata lookups
def ticket_attr(col, values):
    """Return ticket numbers where st[col] is in values."""
    return set(store_st[store_st[col].str.strip().isin(values)]["Ticket_Number"])


non_exempt_tix = ticket_attr("Tax_Exempt", ["False"])
exempt_tix = ticket_attr("Tax_Exempt", ["True"])
tt_8_tix = ticket_attr("Ticket_Type_ID", ["8"])  # 3rd-party delivery
tt_1_7_tix = ticket_attr("Ticket_Type_ID", ["1", "7"])
tt_5_tix = ticket_attr("Ticket_Type_ID", ["5"])  # online orders
status_8_tix = ticket_attr("Status_ID", ["8"])  # gift card tickets


# STS filter helper
def sts_sum(ticket_set, cat_ids, field):
    mask = sts["Ticket_Number"].isin(ticket_set) & sts["Category_ID"].isin(
        [str(c) for c in cat_ids]
    )
    return sts.loc[mask, field].sum()


# Payment filter helper
pay_store = pay[pay["Ticket_Number"].isin(store_paid)].copy()
pay_store["_tlen"] = pay_store["Transaction_ID"].str.strip().str.len()


def p(
    type_ids=None,
    name_ids=None,
    tlen=None,
    tip_paid=None,
    name_vals=None,
    ticket_set=None,
):
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
    if name_vals:
        df = df[df["Name"].str.strip().isin([str(v) for v in name_vals])]
    return df


# ── Store_Transactions for this store/date ─────────────────────────────────
store_txn = txn[
    (txn["Store_ID"] == str(STORE_ID)) & (txn["Transaction_Date"].str.startswith(DATE))
]

# ── SALES CATEGORIES ────────────────────────────────────────────────────────

# 1. Subject to Tax (401000) — Credit
# paid, Tax_Exempt=False, cat1 Taxable - cat2 Taxable
paid_non_exempt = store_paid & non_exempt_tix
subj_tax = sts_sum(paid_non_exempt, [1], "Taxable_Amount") - sts_sum(
    paid_non_exempt, [2], "Taxable_Amount"
)

# 2. Non-Taxable Sales (401500) — Credit
# paid, both Tax_Exempt (all), exclude Status_ID=8, cat1-2-7
paid_no_status8 = store_paid - (store_paid & status_8_tix)
non_tax = (
    sts_sum(paid_no_status8, [1], "Non_Taxable_Amount")
    - sts_sum(paid_no_status8, [2], "Non_Taxable_Amount")
    - sts_sum(paid_no_status8, [7], "Total")
)

# 3. 3rd Party Tax Exempt (401506) — Credit
# paid, Tax_Exempt=True, Ticket_Type_ID=8, cat1-cat2 Taxable
paid_exempt_tt8 = store_paid & exempt_tix & tt_8_tix
exempt_3p = sts_sum(paid_exempt_tt8, [1], "Taxable_Amount") - sts_sum(
    paid_exempt_tt8, [2], "Taxable_Amount"
)

# 4. Tax Exempt (401505) — Credit
# paid, Tax_Exempt=True, Ticket_Type_ID=1 or 7, cat1-cat2 Taxable
paid_exempt_tt17 = store_paid & exempt_tix & tt_1_7_tix
tax_exempt = sts_sum(paid_exempt_tt17, [1], "Taxable_Amount") - sts_sum(
    paid_exempt_tt17, [2], "Taxable_Amount"
)

# 5. Cash Over/Short (660001) — from DailyJournal comment
dj_store = dj[dj["Store_Number"].str.strip() == str(STORE_NUMBER)]
ra_dj = dj_store[dj_store["Action"].str.strip() == "Register Audit"]
cash_over_short = 0.0
if len(ra_dj):
    comment = ra_dj["Comments"].iloc[-1]
    m = re.search(r"Over/Short:\s*([-\d.]+)", str(comment))
    if m:
        cash_over_short = float(m.group(1))

# 6. Payin (108000) — Credit
# Store_Transactions, Transaction_Type_Name=Payins, Status=Inserted
payin_rows = store_txn[
    (store_txn["Transaction_Type_Name"].str.strip() == "Payins")
    & (store_txn["Status"].str.strip() == "Inserted")
]
payin = payin_rows["Amount"].sum()

# 7. Donation (200400) — Credit
# cat7, Total, paid tickets
donation = sts_sum(store_paid, [7], "Total")

# 8. Sales Tax (213500) — Credit
# paid, Tax_Exempt=False, cat5 Total
sales_tax = sts_sum(store_paid & non_exempt_tix, [5], "Total")

# 9. Online Credit Card Tips (108000) — Credit
# pay type 14 or 3, 32-digit TID, Tip_Paid=True, Tip_Amount
online_cc_tips = p(type_ids=[14, 3], tlen=32, tip_paid=True)["Tip_Amount"].sum()

# 10. In-Store Credit Card Tips (108000) — Credit
# pay14, not 32-digit, Tip_Amount > 0
instore_tip_rows = p(type_ids=[14], tlen=[4, 6])
instore_cc_tips = instore_tip_rows[instore_tip_rows["Tip_Amount"] > 0][
    "Tip_Amount"
].sum()

# 11. Online Gift Card Tips (108000) — Credit
# pay5 on Ticket_Type_ID=5 tickets, Payment_Name_ID=8, Tip_Amount
online_gc_tips = p(type_ids=[5], name_ids=[8], ticket_set=store_paid & tt_5_tix)[
    "Tip_Amount"
].sum()

# 12. Gift Card Sold (113000) — Credit
# Status_ID=8 tickets (gift card purchase tickets); 0 if none exist
gc_sold_pay = p(ticket_set=store_paid & status_8_tix, type_ids=[14])[
    "Tendered_Amount"
].sum()
# fallback: STS cat1, Taxable=0, Non_Taxable>0, Status_ID=8 tickets
gc_sold_sts = 0.0
if not (store_paid & status_8_tix):
    gc_sold_sts_mask = (
        sts["Ticket_Number"].isin(store_paid & status_8_tix)
        & (sts["Category_ID"] == "1")
        & (sts["Taxable_Amount"] == 0)
        & (sts["Non_Taxable_Amount"] > 0)
    )
    gc_sold_sts = sts.loc[gc_sold_sts_mask, "Non_Taxable_Amount"].sum()
gift_card_sold = gc_sold_pay + gc_sold_sts

# ── ROYALTIES ───────────────────────────────────────────────────────────────
royalty_base = subj_tax + non_tax + exempt_3p + tax_exempt
royalties_bank = round(royalty_base * 0.115 * 0.565216, 2)
corp_advertising = round(royalty_base * 0.115 * 0.086956, 2)
national_media = round(royalty_base * 0.115 * 0.347828, 2)

# ── REGISTER AUDIT (103109) — Debit ─────────────────────────────────────────
ra_rows = store_txn[store_txn["Transaction_Type_Name"].str.strip() == "Register Audit"]
register_audit = float(ra_rows["Amount"].iloc[-1]) if len(ra_rows) else 0.0

# ── BANK DEPOSIT ─────────────────────────────────────────────────────────────
bank_dep_rows = store_txn[
    store_txn["Transaction_Type_Name"].str.strip() == "Bank Deposit"
]
bank_deposit = bank_dep_rows["Amount"].sum()

# ── PAYOUT (570102) — Debit ───────────────────────────────────────────────
payout_rows = store_txn[
    store_txn["Transaction_Type_Name"].str.strip() == "Store Payout"
]
payout = payout_rows["Amount"].sum()

# ── PAYMENT-BASED DEBITS ──────────────────────────────────────────────────

# Online Credit Card (103109) — Debit
# pay14, 32-digit, Tip_Paid=True, Tendered + Tip
online_cc_rows = p(type_ids=[14], tlen=32, tip_paid=True)
online_cc = (online_cc_rows["Tendered_Amount"] + online_cc_rows["Tip_Amount"]).sum()

# In-Store Credit Card (103109) — Debit
# pay14: (6-digit, Tip_Paid=True) OR (32-digit, Tip_Paid=False) OR 4-digit
# amount = Tendered - Change + Tip + gift_card_sold (gc_sold already 0)
p14 = pay_store[pay_store["Payment_Type_ID"] == "14"]
instore_cc_rows = p14[
    ((p14["_tlen"] == 6) & (p14["Tip_Paid"].str.strip() == "True"))
    | ((p14["_tlen"] == 32) & (p14["Tip_Paid"].str.strip() == "False"))
    | (p14["_tlen"] == 4)
]
instore_cc = (
    instore_cc_rows["Tendered_Amount"]
    - instore_cc_rows["Change"]
    + instore_cc_rows["Tip_Amount"]
).sum()
instore_cc += gift_card_sold  # add gift card sold component

# Gift Card (113000) — Debit
# pay5, 6-digit TID, Tendered_Amount
gift_card = p(type_ids=[5], tlen=6)["Tendered_Amount"].sum()

# Online Gift Card (103109) — Debit
# pay5, 32-digit TID, Tendered_Amount + Tip_Amount (mirrors Online CC pattern;
# tip is also credited separately under Online Gift Card Tips 108000 Cr)
online_gc_rows = p(type_ids=[5], tlen=32)
online_gc = (online_gc_rows["Tendered_Amount"] + online_gc_rows["Tip_Amount"]).sum()

# House Account (119100) — Debit
house_account = p(type_ids=[7])["Tendered_Amount"].sum()

# 3rd Party — all from pay13, split by Name
p13 = pay_store[pay_store["Payment_Type_ID"] == "13"]
uber_eats = p13[p13["Name"].str.strip() == "4001"]["Tendered_Amount"].sum()
doordash = p13[p13["Name"].str.strip() == "4004"]["Tendered_Amount"].sum()
postmates = p13[p13["Name"].str.strip() == "4052"]["Tendered_Amount"].sum()
grubhub = p13[p13["Name"].str.strip() == "4003"]["Tendered_Amount"].sum()
ez_cater = p13[p13["Name"].str.strip() == "74"]["Tendered_Amount"].sum()

# ── TOTALS ───────────────────────────────────────────────────────────────
cos_dr = abs(cash_over_short) if cash_over_short < 0 else 0.0
cos_cr = cash_over_short if cash_over_short >= 0 else 0.0

total_credits = (
    subj_tax
    + non_tax
    + exempt_3p
    + tax_exempt
    + payin
    + donation
    + sales_tax
    + online_cc_tips
    + instore_cc_tips
    + online_gc_tips
    + gift_card_sold
    + cos_cr
)
total_debits = (
    register_audit
    + payout
    + online_cc
    + instore_cc
    + gift_card
    + online_gc
    + house_account
    + uber_eats
    + doordash
    + grubhub
    + ez_cater
    + cos_dr
)

# ── PRINT RESULTS ─────────────────────────────────────────────────────────
# (label, acct, debit, credit)  — blank col when value is 0

results = [
    ("Subject to Tax", "401000", 0, subj_tax),
    ("Non-Taxable Sales", "401500", 0, non_tax),
    ("3rd Party Tax Exempt", "401506", 0, exempt_3p),
    ("Tax Exempt", "401505", 0, tax_exempt),
    ("Register Audit", "103109", register_audit, 0),
    ("Sales Tax", "213500", 0, sales_tax),
    ("In-Store Credit Card", "103109", instore_cc, 0),
    ("Payout", "570102", payout, 0),
    ("Online Credit Card", "103109", online_cc + online_gc, 0),
    ("  Online Credit Card", "103109", online_cc, 0),
    ("  Online Gift Card", "103109", online_gc, 0),
    ("Online CC Tips", "108000", 0, online_cc_tips),
    ("In-Store CC Tips", "108000", 0, instore_cc_tips),
    ("Online Gift Card Tips", "108000", 0, online_gc_tips),
    ("Gift Card", "113000", gift_card, 0),
    ("Gift Card Sold", "113000", 0, gift_card_sold),
    ("3rd Party - UberEats", "119151", uber_eats, 0),
    ("3rd Party - DoorDash", "119157", doordash, 0),
    ("3rd Party - GrubHub", "119152", grubhub, 0),
    ("3rd Party - EZ Cater", "119164", ez_cater, 0),
    ("House Account", "119100", house_account, 0),
    ("Donation", "200400", 0, donation),
    ("Payin", "108000", 0, payin),
    ("Cash Over/Short Adj", "660001", cos_dr, cos_cr),
]

print(f"Store {STORE_NUMBER} — {DATE}\n")
print(f"{'Category':<28} {'Acct':>6}  {'Debit':>12}  {'Credit':>12}")
print("-" * 66)
for label, acct, dr, cr in results:
    dr_str = f"{dr:12.2f}" if dr != 0 else " " * 12
    cr_str = f"{cr:12.2f}" if cr != 0 else " " * 12
    print(f"{label:<28} {acct:>6}  {dr_str}  {cr_str}")

# print(f"\nRoyalty base (net sales): {royalty_base:.2f}")
print(f"\nTotal Debits:             {total_debits:.2f}")
print(f"Total Credits:            {total_credits:.2f}")
