"""Verify financial categories for store 4078 on 2026-04-01."""
from pathlib import Path

import pandas as pd

DATE = "2026-04-01"
STORE_NUMBER = 4078
STORE_ID = 3054  # from Store.txt


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pos_data").is_dir():
            return parent
    return Path(__file__).resolve().parents[3]


DATA_DIR = _repo_root() / "pos_data" / DATE

# --- Load files ---
st = pd.read_csv(DATA_DIR / "Sales_Ticket.txt", sep="|", dtype=str)
sts = pd.read_csv(DATA_DIR / "Sales_Ticket_Summary.txt", sep="|", dtype=str)
pay = pd.read_csv(DATA_DIR / "Payment.txt", sep="|", dtype=str)
txn = pd.read_csv(DATA_DIR / "Store_Transactions.txt", sep="|", dtype=str)

# Numeric conversions
for col in ["Taxable_Amount", "Non_Taxable_Amount", "Total"]:
    sts[col] = pd.to_numeric(sts[col], errors="coerce").fillna(0)
for col in ["Tendered_Amount", "Change", "Tip_Amount"]:
    pay[col] = pd.to_numeric(pay[col], errors="coerce").fillna(0)
txn["Amount"] = pd.to_numeric(txn["Amount"], errors="coerce").fillna(0)

# --- Step 1: Store 4078 tickets (paid) ---
store_tickets = st[st["Store_ID"] == str(STORE_ID)]["Ticket_Number"].unique()
paid_tickets = pay["Ticket_Number"].unique()  # any ticket with a payment row
store_paid = set(store_tickets) & set(paid_tickets)

# Filter helpers
def store_sts(cat_id=None):
    df = sts[sts["Ticket_Number"].isin(store_paid)]
    if cat_id is not None:
        df = df[df["Category_ID"] == str(cat_id)]
    return df

def store_pay(extra_mask=None):
    df = pay[pay["Ticket_Number"].isin(store_paid)]
    if extra_mask is not None:
        df = df[extra_mask(df)]
    return df

# --- 1. Register Audit ---
# Store_Transactions.txt, Transaction_Type_Name = Register Audit, latest one
ra = txn[
    (txn["Store_ID"] == str(STORE_ID)) &
    (txn["Transaction_Type_Name"].str.strip() == "Register Audit") &
    (txn["Transaction_Date"].str.startswith(DATE))
]
register_audit = ra["Amount"].iloc[-1] if len(ra) > 0 else 0.0
print(f"Register Audit rows: {len(ra)}")
if len(ra) > 0:
    print(ra[["Transaction_Date","Transaction_Type_Name","Amount"]].to_string())

# --- 2. Sales Tax ---
# Category_ID=5, paid tickets, Tax_Exempt=False in Sales_Ticket
non_exempt = st[(st["Store_ID"] == str(STORE_ID)) & (st["Tax_Exempt"].str.strip() == "False")]["Ticket_Number"].unique()
non_exempt_paid = set(non_exempt) & set(paid_tickets)
sales_tax = sts[sts["Ticket_Number"].isin(non_exempt_paid) & (sts["Category_ID"] == "5")]["Total"].sum()

# --- 3. Donation ---
# Category_ID=7, paid tickets
donation = store_sts(cat_id=7)["Total"].sum()

# --- 4. Payment type helpers ---
def tid_len(df):
    return df["Transaction_ID"].str.strip().str.len()

def is_32(df):
    return tid_len(df) == 32

def is_6(df):
    return tid_len(df) == 6

def is_4(df):
    return tid_len(df) == 4

store_pay_all = store_pay()
pay14 = store_pay_all[store_pay_all["Payment_Type_ID"] == "14"]
pay5 = store_pay_all[store_pay_all["Payment_Type_ID"] == "5"]
pay13 = store_pay_all[store_pay_all["Payment_Type_ID"] == "13"]

# --- 5. Online Credit Card ---
# Payment_Type_ID=14, Transaction_ID=32 digits, Tips=True (Tip_Paid column)
online_cc_rows = pay14[is_32(pay14) & (pay14["Tip_Paid"].str.strip() == "True")]
online_cc = (online_cc_rows["Tendered_Amount"] + online_cc_rows["Tip_Amount"]).sum()

# --- 6. Online Credit Card Tips ---
# Payment_Type_ID=14 or 3, Transaction_ID=32 digits, Tips=True
pay14_or_3 = store_pay_all[store_pay_all["Payment_Type_ID"].isin(["14","3"])]
online_cc_tip_rows = pay14_or_3[is_32(pay14_or_3) & (pay14_or_3["Tip_Paid"].str.strip() == "True")]
online_cc_tips = online_cc_tip_rows["Tip_Amount"].sum()

# --- 7. In-Store Credit Card ---
# Payment_Type_ID=14 with:
#   Transaction_ID=6 digits & Tip_Paid=True  OR
#   Transaction_ID=32 digits & Tip_Paid=False OR
#   Transaction_ID=4 digits
instore_cc_rows = pay14[
    (is_6(pay14) & (pay14["Tip_Paid"].str.strip() == "True")) |
    (is_32(pay14) & (pay14["Tip_Paid"].str.strip() == "False")) |
    is_4(pay14)
]
# Tendered_Amount - Change + Tip_Amount
# Note: gift card sold component skipped for now (complex)
instore_cc = (instore_cc_rows["Tendered_Amount"] - instore_cc_rows["Change"] + instore_cc_rows["Tip_Amount"]).sum()

# --- 8. In-Store Credit Card Tips ---
# Complement: pay14, in-store (not 32-digit online), Tip_Amount > 0
instore_tip_rows = pay14[
    ~is_32(pay14) & (pay14["Tip_Amount"] > 0)
]
instore_cc_tips = instore_tip_rows["Tip_Amount"].sum()

# --- 9. Gift Card ---
# Payment_Type_ID=5, Transaction_ID=6 digits
gift_card_rows = pay5[is_6(pay5)]
gift_card = gift_card_rows["Tendered_Amount"].sum()

# --- 10. 3rd Party - UberEats (Name=4001) ---
uber = pay13[pay13["Name"].str.strip() == "4001"]["Tendered_Amount"].sum()

# --- 11. 3rd Party - DoorDash (Name=4004) ---
doordash = pay13[pay13["Name"].str.strip() == "4004"]["Tendered_Amount"].sum()

# --- Results ---
expected = {
    "Register Audit":         228.00,
    "Sales Tax":              338.92,
    "In-Store Credit Card":  1829.01,
    "Online Credit Card":    1071.67,
    "Online CC Tips":          48.00,
    "In-Store CC Tips":       112.97,
    "Gift Card":               16.82,
    "3rd Party - UberEats":   197.79,
    "3rd Party - DoorDash":   834.55,
    "Donation":                15.13,
}

computed = {
    "Register Audit":        round(float(register_audit), 2),
    "Sales Tax":             round(sales_tax, 2),
    "In-Store Credit Card":  round(instore_cc, 2),
    "Online Credit Card":    round(online_cc, 2),
    "Online CC Tips":        round(online_cc_tips, 2),
    "In-Store CC Tips":      round(instore_cc_tips, 2),
    "Gift Card":             round(gift_card, 2),
    "3rd Party - UberEats":  round(uber, 2),
    "3rd Party - DoorDash":  round(doordash, 2),
    "Donation":              round(donation, 2),
}

print(f"\n{'Category':<25} {'Expected':>10} {'Computed':>10} {'Diff':>10} {'Match'}")
print("-" * 65)
for k in expected:
    exp = expected[k]
    comp = computed[k]
    diff = round(comp - exp, 2)
    match = "OK" if abs(diff) < 0.01 else "DIFF"
    print(f"{k:<25} {exp:>10.2f} {comp:>10.2f} {diff:>10.2f} {match}")
