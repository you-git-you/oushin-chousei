#!/usr/bin/env python3
"""8月往診リスト MD から schedule.sqlite に 2026-08 をシードする。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from build_august_schedule_html import MD_PATH, parse_md
from schedule.config import DEFAULT_PERIOD_KEY, DEFAULT_PERIOD_TITLE
from schedule.sqlite_store import SqliteScheduleRepository, init_db


def routes_from_md(md_path: Path) -> dict:
    data = parse_md(md_path.read_text(encoding="utf-8"))
    routes: dict[str, dict[str, list[str]]] = {}
    for day in data["days"]:
        day_routes: dict[str, list[str]] = {}
        for doc in day["doctors"]:
            ids = [v["id"] for v in doc["visits"]]
            if ids:
                day_routes[doc["name"]] = ids
        if day_routes:
            routes[day["key"]] = day_routes
    return routes


def main() -> None:
    if not MD_PATH.exists():
        raise SystemExit(f"not found: {MD_PATH}")
    init_db()
    routes = routes_from_md(MD_PATH)
    store = SqliteScheduleRepository()
    store.replace_routes(
        DEFAULT_PERIOD_KEY,
        routes,
        source="seed_md",
        note=str(MD_PATH.name),
        title=DEFAULT_PERIOD_TITLE,
    )
    total = sum(len(ids) for dr in routes.values() for ids in dr.values())
    print(f"Seeded {DEFAULT_PERIOD_KEY}: {len(routes)} days, {total} visits -> schedule.sqlite")


if __name__ == "__main__":
    main()
