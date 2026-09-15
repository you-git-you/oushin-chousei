# -*- coding: utf-8 -*-
"""休止・再開スナップショットを DB へ取込む。

- visit_records.sqlite: pause_resume_records
- 任意 --sync-oushin: patients.status と status_changes を更新
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, ROOT, VISIT_RECORDS_DB_PATH  # noqa: E402
from import_from_csv import ensure_placeholder_patient, make_event_id  # noqa: E402

PAUSE_JSON = ROOT / "records" / "data" / "pause_resume_status.json"
OUT_MD = ROOT / "records" / "休止再開_現状一覧.md"
SOURCE_TAG = "records/data/pause_resume_status.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def import_visit_records_db(payload: dict, source_file: str) -> int:
    if not VISIT_RECORDS_DB_PATH.exists():
        raise SystemExit(
            f"visit_records DB がありません: {VISIT_RECORDS_DB_PATH} "
            "(init_visit_records_db.py を実行)"
        )
    conn = sqlite3.connect(VISIT_RECORDS_DB_PATH)
    imported_at = utc_now_iso()
    try:
        conn.execute("DELETE FROM pause_resume_records")
        n = 0
        for r in payload.get("records", []):
            conn.execute(
                """
                INSERT INTO pause_resume_records (
                    record_id, patient_id, patient_name, main_staff,
                    pause_date, resume_date, end_date, current_status,
                    reason, slot_released, note, source_file, imported_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    r["record_id"],
                    r.get("patient_id"),
                    r["patient_name"],
                    r.get("main_staff"),
                    r.get("pause_date"),
                    r.get("resume_date"),
                    r.get("end_date"),
                    r["current_status"],
                    r.get("reason"),
                    1 if r.get("slot_released") else 0,
                    r.get("note"),
                    source_file,
                    imported_at,
                ),
            )
            n += 1
        conn.execute(
            """
            INSERT INTO pause_import_log (source_file, imported_at, record_count)
            VALUES (?,?,?)
            """,
            (source_file, imported_at, n),
        )
        conn.commit()
        return n
    finally:
        conn.close()


def sync_oushin(payload: dict) -> tuple[int, int]:
    if not DB_PATH.exists():
        raise SystemExit(f"oushin DB がありません: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    updated = 0
    changes = 0
    try:
        conn.execute(
            "DELETE FROM status_changes WHERE source_row = ?", (SOURCE_TAG,)
        )
        for r in payload.get("records", []):
            pid = r.get("patient_id")
            if not pid:
                continue
            ensure_placeholder_patient(conn, pid, r["patient_name"])
            change_id = make_event_id("pause", pid, r.get("pause_date") or "", r["record_id"])
            conn.execute(
                """
                INSERT INTO status_changes (
                    change_id, patient_id, change_type, effective_date,
                    planned_resume_date, resume_date, reason, staff,
                    slot_released, source_row
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    change_id,
                    pid,
                    "pause",
                    r.get("pause_date"),
                    None,
                    r.get("resume_date"),
                    r.get("reason"),
                    r.get("main_staff"),
                    1 if r.get("slot_released") else None,
                    SOURCE_TAG,
                ),
            )
            changes += 1

            status = r["current_status"]
            if status == "ended":
                end_d = r.get("end_date") or r.get("pause_date")
                conn.execute(
                    """
                    UPDATE patients
                    SET status = 'ended', end_date = COALESCE(?, end_date),
                        end_reason = COALESCE(?, end_reason)
                    WHERE patient_id = ?
                    """,
                    (end_d, r.get("reason"), pid),
                )
            elif status == "paused":
                conn.execute(
                    """
                    UPDATE patients SET status = 'paused'
                    WHERE patient_id = ? AND status != 'ended'
                    """,
                    (pid,),
                )
            elif status == "active":
                conn.execute(
                    """
                    UPDATE patients SET status = 'active'
                    WHERE patient_id = ? AND status NOT IN ('ended')
                    """,
                    (pid,),
                )
            updated += 1
        conn.commit()
    finally:
        conn.close()
    return updated, changes


def export_markdown(payload: dict) -> None:
    labels = {
        "active": "再開済み（現役）",
        "paused": "休止中",
        "ended": "終了",
    }
    groups: dict[str, list] = {"paused": [], "ended": [], "active": []}
    for r in payload.get("records", []):
        groups[r["current_status"]].append(r)

    lines = [
        "# 休止・再開 現状一覧",
        "",
        f"更新: {payload.get('updated', '—')}（`records/data/pause_resume_status.json`）",
        "",
        "取込: `python3 scripts/import_pause_resume.py --sync-oushin`",
        "",
    ]
    for key in ("paused", "ended", "active"):
        lines.append(f"## {labels[key]}（{len(groups[key])}名）")
        lines.append("")
        lines.append("| 氏名 | ID | 担当 | 休止日 | 再開/終了 | 枠解除 | 理由（要約） |")
        lines.append("|------|-----|------|--------|-----------|--------|--------------|")
        for r in groups[key]:
            resume_end = r.get("end_date") or r.get("resume_date") or "—"
            slot = "○" if r.get("slot_released") else ""
            reason = (r.get("reason") or "").replace("|", "／")[:60]
            lines.append(
                f"| {r['patient_name']} | {r.get('patient_id') or '—'} | "
                f"{r.get('main_staff') or '—'} | {r.get('pause_date') or '—'} | "
                f"{resume_end} | {slot} | {reason} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 往診スケジュールとの関係",
            "",
            "- **休止中・終了**の方は9月往診の候補から外す（枠解除○はリハ枠の話。往診も原則なし）。",
            "- **本橋明子・大和八重子**は7月に往診実施済みだが、7/17・7/31以降は休止のため追加往診なし。",
            "- **今井鈴**は2月に再開済みのため、7/13往診実施と矛盾しません。",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=PAUSE_JSON)
    parser.add_argument("--sync-oushin", action="store_true")
    parser.add_argument("--no-md", action="store_true")
    args = parser.parse_args()

    payload = load_payload(args.json)
    n = import_visit_records_db(payload, str(args.json))
    print(f"pause_resume_records: {n}")

    if args.sync_oushin:
        u, c = sync_oushin(payload)
        print(f"oushin patients updated: {u}, status_changes: {c}")

    if not args.no_md:
        export_markdown(payload)
        print(f"Wrote: {OUT_MD}")


if __name__ == "__main__":
    main()
