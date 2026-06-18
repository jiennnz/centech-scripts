from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "audit_scripts"))

import iscc_iscct  # type: ignore


if __name__ == "__main__":
    iscc_iscct.main()
