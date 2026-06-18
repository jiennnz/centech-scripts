"""
Check all Payment.txt files for tlen=32, Payment_Type_ID=14 rows. Two outputs:
  tlen32_online_cc.csv  — Tip_Paid=True  (Online CC pattern)
  tlen32_iscc.csv       — Tip_Paid=False (ISCC pattern)
"""
import pandas as pd
from pathlib import Path

POS_DATA_DIR = Path(__file__).parent.parent / "pos_data"
OUT_DIR = Path(__file__).parent / "data"
OUT_DIR.mkdir(exist_ok=True)

frames = []

for date_folder in sorted(POS_DATA_DIR.iterdir()):
    pay_path = date_folder / "Payment.txt"
    if not pay_path.exists():
        continue
    try:
        df = pd.read_csv(pay_path, sep="|", dtype=str)
    except Exception as e:
        print(f"[skip] {date_folder.name}: {e}")
        continue
    df["_source_folder"] = date_folder.name
    frames.append(df)

if not frames:
    print("No Payment.txt files found.")
    raise SystemExit(1)

combined = pd.concat(frames, ignore_index=True)
combined["_tlen"] = combined["Transaction_ID"].str.strip().str.len()
combined["Payment_Type_ID"] = combined["Payment_Type_ID"].astype(str).str.strip()
combined["Tip_Paid"] = combined["Tip_Paid"].astype(str).str.strip()

tlen32_type14 = combined[
    (combined["Payment_Type_ID"] == "14") & (combined["_tlen"] == 32)
]

online_cc = tlen32_type14[tlen32_type14["Tip_Paid"] == "True"]
iscc      = tlen32_type14[tlen32_type14["Tip_Paid"] == "False"]

online_cc.to_csv(OUT_DIR / "tlen32_online_cc.csv", index=False)
iscc.to_csv(OUT_DIR / "tlen32_iscc.csv", index=False)

print(f"tlen32_online_cc.csv : {len(online_cc):,} rows")
print(f"tlen32_iscc.csv      : {len(iscc):,} rows")
print(f"Output: {OUT_DIR}")
