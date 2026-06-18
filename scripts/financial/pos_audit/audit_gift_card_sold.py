from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "audit_scripts"))

import gift_card_sold  # type: ignore


if __name__ == "__main__":
    gift_card_sold.main()
