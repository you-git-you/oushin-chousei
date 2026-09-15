from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEDULE_DB_PATH = ROOT / "db" / "schedule.sqlite"
SCHEDULE_SCHEMA_PATH = ROOT / "scripts" / "schema_schedule.sql"
DEFAULT_PERIOD_KEY = "2026-08"
DEFAULT_PERIOD_TITLE = "8月往診リスト（2026年）"
