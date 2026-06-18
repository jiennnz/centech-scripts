from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "audit_scripts"))

import royalty_fee_century  # type: ignore


if __name__ == "__main__":
    royalty_fee_century.run()
