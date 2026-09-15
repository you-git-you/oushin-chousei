from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from schedule.config import DEFAULT_PERIOD_TITLE, SCHEDULE_DB_PATH, SCHEDULE_SCHEMA_PATH
from schedule.repository import RoutesMap, routes_snapshot_json, routes_to_overrides_document


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or SCHEDULE_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | None = None, schema_path: Path | None = None) -> None:
    path = db_path or SCHEDULE_DB_PATH
    schema = schema_path or SCHEDULE_SCHEMA_PATH
    conn = connect(path)
    try:
        conn.executescript(schema.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


class SqliteScheduleRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or SCHEDULE_DB_PATH

    def _conn(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def has_routes(self, period_key: str) -> bool:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM schedule_assignment WHERE period_key = ? LIMIT 1",
                (period_key,),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def get_routes(self, period_key: str) -> RoutesMap:
        conn = self._conn()
        try:
            rows = conn.execute(
                """
                SELECT day_key, doctor, patient_chart_id, sort_index
                FROM schedule_assignment
                WHERE period_key = ?
                ORDER BY day_key, doctor, sort_index
                """,
                (period_key,),
            ).fetchall()
        finally:
            conn.close()

        routes: RoutesMap = {}
        for row in rows:
            dk = row["day_key"]
            doc = row["doctor"]
            routes.setdefault(dk, {}).setdefault(doc, []).append(row["patient_chart_id"])
        return routes

    def replace_routes(
        self,
        period_key: str,
        routes: RoutesMap,
        *,
        source: str,
        note: str | None = None,
        title: str | None = None,
    ) -> None:
        now = utc_now_iso()
        conn = self._conn()
        try:
            conn.execute("BEGIN")
            existing = conn.execute(
                "SELECT title FROM schedule_period WHERE period_key = ?",
                (period_key,),
            ).fetchone()
            period_title = title or (existing["title"] if existing else DEFAULT_PERIOD_TITLE)
            if existing:
                conn.execute(
                    """
                    UPDATE schedule_period
                    SET title = ?, updated_at = ?
                    WHERE period_key = ?
                    """,
                    (period_title, now, period_key),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO schedule_period (period_key, title, status, created_at, updated_at)
                    VALUES (?, ?, 'draft', ?, ?)
                    """,
                    (period_key, period_title, now, now),
                )

            conn.execute(
                "DELETE FROM schedule_assignment WHERE period_key = ?",
                (period_key,),
            )

            for day_key, day_routes in routes.items():
                if not isinstance(day_routes, dict):
                    continue
                for doctor, ids in day_routes.items():
                    if not isinstance(ids, list):
                        continue
                    for sort_index, chart_id in enumerate(ids):
                        conn.execute(
                            """
                            INSERT INTO schedule_assignment (
                                assignment_id, period_key, day_key, doctor,
                                patient_chart_id, sort_index, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                str(uuid.uuid4()),
                                period_key,
                                day_key,
                                doctor,
                                str(chart_id),
                                sort_index,
                                now,
                            ),
                        )

            conn.execute(
                """
                INSERT INTO schedule_revision (
                    revision_id, period_key, created_at, source, note, routes_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    period_key,
                    now,
                    source,
                    note,
                    routes_snapshot_json(routes),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def export_overrides_document(self, period_key: str) -> dict:
        return routes_to_overrides_document(period_key, self.get_routes(period_key))
