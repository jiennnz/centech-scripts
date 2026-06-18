from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "audit_scripts"))

import third_party_surcharge  # type: ignore


if __name__ == "__main__":
    third_party_surcharge.run()
