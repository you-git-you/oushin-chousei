# -*- coding: utf-8 -*-
"""records/data/confirmed_visits.json を visit_records.sqlite へ取込む。

任意で db/oushin.sqlite の events に source=confirmed_record として同期する。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DB_PATH,
    VISIT_RECORDS_DB_PATH,
    VISIT_RECORDS_JSON_PATH,
)
from import_from_csv import ensure_placeholder_patient, insert_event  # noqa: E402


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_insurance(
    conn: sqlite3.Connection, patient_id: str | None, override: str | None
) -> str:
    if override:
        return override
    if not patient_id:
        return "unknown"
    row = conn.execute(
        "SELECT insurance_type FROM patients WHERE patient_id = ?", (patient_id,)
    ).fetchone()
    return row[0] if row else "unknown"


def import_to_visit_records(payload: dict, source_file: str) -> tuple[int, int, int]:
    if not VISIT_RECORDS_DB_PATH.exists():
        raise SystemExit(
            f"visit_records DB がありません。先に init_visit_records_db.py を実行: "
            f"{VISIT_RECORDS_DB_PATH}"
        )

    imported_at = utc_now_iso()
    conn = sqlite3.connect(VISIT_RECORDS_DB_PATH)
    oconn = sqlite3.connect(DB_PATH)
    try:
        n_sessions = 0
        n_visits = 0
        for session in payload.get("sessions", []):
            sid = session["session_id"]
            conn.execute(
                """
                INSERT OR REPLACE INTO confirmed_sessions (
                    session_id, performed_date, doctor, driver, departure,
                    visit_minutes, note, source_file, imported_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    sid,
                    session["performed_date"],
                    session["doctor"],
                    session.get("driver"),
                    session.get("departure"),
                    session.get("visit_minutes"),
                    session.get("note"),
                    source_file,
                    imported_at,
                ),
            )
            n_sessions += 1
            conn.execute(
                "DELETE FROM confirmed_visits WHERE session_id = ?", (sid,)
            )
            for v in session.get("visits", []):
                vid = f"{sid}-{v['order']}"
                ins = resolve_insurance(
                    oconn, v.get("patient_id"), v.get("insurance_override")
                )
                conn.execute(
                    """
                    INSERT INTO confirmed_visits (
                        visit_id, session_id, route_order, patient_id, patient_name,
                        time_window, address, eta, insurance_type, status, note
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        vid,
                        sid,
                        v["order"],
                        v.get("patient_id"),
                        v["name"],
                        v.get("window"),
                        v.get("address"),
                        v.get("eta"),
                        ins,
                        v.get("status", "completed"),
                        v.get("note"),
                    ),
                )
                n_visits += 1

        conn.execute("DELETE FROM confirmed_deferred")
        n_deferred = 0
        for item in payload.get("deferred", []):
            if "patients" in item:
                for p in item["patients"]:
                    defer_id = f"{item['planned_date']}-{p.get('patient_id') or p['name']}"
                    conn.execute(
                        """
                        INSERT INTO confirmed_deferred (
                            defer_id, planned_date, patient_id, patient_name,
                            doctor, status, reason, follow_up, note
                        ) VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            defer_id,
                            item.get("planned_date"),
                            p.get("patient_id"),
                            p["name"],
                            item.get("doctor"),
                            item.get("status", "rescheduled"),
                            item.get("reason"),
                            item.get("follow_up"),
                            p.get("note"),
                        ),
                    )
                    n_deferred += 1
            else:
                defer_id = f"{item.get('planned_date')}-{item.get('patient_id') or item['name']}"
                conn.execute(
                    """
                    INSERT INTO confirmed_deferred (
                        defer_id, planned_date, patient_id, patient_name,
                        doctor, status, reason, follow_up, note
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        defer_id,
                        item.get("planned_date"),
                        item.get("patient_id"),
                        item["name"],
                        item.get("doctor"),
                        item.get("status"),
                        item.get("reason"),
                        item.get("follow_up"),
                        item.get("note"),
                    ),
                )
                n_deferred += 1

        conn.execute(
            """
            INSERT INTO import_log (source_file, imported_at, sessions, visits, deferred)
            VALUES (?,?,?,?,?)
            """,
            (source_file, imported_at, n_sessions, n_visits, n_deferred),
        )
        conn.commit()
        return n_sessions, n_visits, n_deferred
    finally:
        conn.close()
        oconn.close()


def sync_to_oushin(payload: dict) -> int:
    if not DB_PATH.exists():
        raise SystemExit(f"oushin DB がありません: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    seen: set[tuple] = set()
    added = 0
    try:
        for session in payload.get("sessions", []):
            perf = date.fromisoformat(session["performed_date"])
            doctor = session["doctor"]
            driver = session.get("driver") or ""
            for v in session.get("visits", []):
                pid = v.get("patient_id")
                if not pid:
                    continue
                ensure_placeholder_patient(conn, pid, v["name"])
                note_parts = [session.get("departure") or "", v.get("note") or ""]
                note = " / ".join(x for x in note_parts if x)
                row_id = f"{session['session_id']}:{v['order']}"
                if insert_event(
                    conn,
                    seen,
                    patient_id=pid,
                    event_type="home_visit",
                    status="completed",
                    performed_at=perf,
                    scheduled_at=perf,
                    doctor_name=doctor,
                    driver_name=driver,
                    area=v.get("address"),
                    note=note or None,
                    source="confirmed_record",
                    source_row_id=row_id,
                ):
                    added += 1
        conn.commit()
    finally:
        conn.close()
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description="確定往診JSONをDBへ取込")
    parser.add_argument(
        "--json",
        type=Path,
        default=VISIT_RECORDS_JSON_PATH,
        help="取込元JSON（既定: records/data/confirmed_visits.json）",
    )
    parser.add_argument(
        "--sync-oushin",
        action="store_true",
        help="oushin.sqlite の events にも同期する",
    )
    args = parser.parse_args()

    if not args.json.exists():
        raise SystemExit(f"JSON がありません: {args.json}")

    payload = load_json(args.json)
    n_s, n_v, n_d = import_to_visit_records(payload, str(args.json))
    print(f"visit_records: sessions={n_s} visits={n_v} deferred={n_d}")

    if args.sync_oushin:
        n = sync_to_oushin(payload)
        print(f"oushin events added (confirmed_record): {n}")


if __name__ == "__main__":
    main()
