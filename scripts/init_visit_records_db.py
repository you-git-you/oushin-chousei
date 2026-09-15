# -*- coding: utf-8 -*-
"""visit_records.sqlite を初期化する。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import VISIT_RECORDS_DB_PATH, VISIT_RECORDS_SCHEMA_PATH


def main() -> None:
    VISIT_RECORDS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    sql = VISIT_RECORDS_SCHEMA_PATH.read_text(encoding="utf-8")
    conn = sqlite3.connect(VISIT_RECORDS_DB_PATH)
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()
    print(f"Initialized: {VISIT_RECORDS_DB_PATH}")


if __name__ == "__main__":
    main()
