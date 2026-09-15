#!/usr/bin/env python3
"""schedule.sqlite の割当を schedule_overrides.json 形式で出力する。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from common import DEFAULT_SCHEDULE_PERIOD, EXPORTS_DIR
from schedule.sqlite_store import SqliteScheduleRepository


def main() -> None:
    period = DEFAULT_SCHEDULE_PERIOD
    if len(sys.argv) > 1:
        period = sys.argv[1]
    store = SqliteScheduleRepository()
    if not store.has_routes(period):
        raise SystemExit(f"No routes in schedule DB for period {period}")
    doc = store.export_overrides_document(period)
    out = EXPORTS_DIR / "schedule_overrides.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
