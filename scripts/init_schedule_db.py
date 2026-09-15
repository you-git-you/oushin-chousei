#!/usr/bin/env python3
"""db/schedule.sqlite を初期化する。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from schedule.config import SCHEDULE_DB_PATH
from schedule.sqlite_store import init_db


def main() -> None:
    init_db()
    print(f"Initialized {SCHEDULE_DB_PATH}")


if __name__ == "__main__":
    main()
