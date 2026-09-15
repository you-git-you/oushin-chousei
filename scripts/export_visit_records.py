# -*- coding: utf-8 -*-
"""visit_records.sqlite から records/直近往診実施一覧.md を生成する。"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    ROOT,
    VISIT_RECORDS_DB_PATH,
    deadline_for,
    insurance_label_ja,
)

OUT_PATH = ROOT / "records" / "直近往診実施一覧.md"


def main() -> None:
    if not VISIT_RECORDS_DB_PATH.exists():
        raise SystemExit(
            f"DB がありません。init_visit_records_db.py → import_visit_records.py を実行"
        )

    conn = sqlite3.connect(VISIT_RECORDS_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        sessions = conn.execute(
            """
            SELECT * FROM confirmed_sessions ORDER BY performed_date, session_id
            """
        ).fetchall()
        visits = conn.execute(
            """
            SELECT cv.*, cs.performed_date, cs.doctor, cs.driver
            FROM confirmed_visits cv
            JOIN confirmed_sessions cs ON cs.session_id = cv.session_id
            ORDER BY cs.performed_date, cv.session_id, cv.route_order
            """
        ).fetchall()
        deferred = conn.execute(
            "SELECT * FROM confirmed_deferred ORDER BY planned_date, patient_name"
        ).fetchall()
        last_import = conn.execute(
            "SELECT * FROM import_log ORDER BY log_id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    lines: list[str] = [
        "# 直近往診実施一覧（手動確定）",
        "",
        "自動生成: `python3 scripts/export_visit_records.py`",
        "",
    ]
    if last_import:
        lines.append(
            f"- 最終取込: {last_import['imported_at']}（{last_import['source_file']}）"
        )
        lines.append(
            f"- 件数: セッション {last_import['sessions']} / 訪問 {last_import['visits']} / 未実施・リスケ {last_import['deferred']}"
        )
    lines.append("")
    lines.append("## 確定実施サマリ（患者ごと・最終実施日）")
    lines.append("")
    lines.append("| 実施日 | 医師 | 氏名 | 区分 | 期限目安 | patient_id |")
    lines.append("|--------|------|------|------|----------|------------|")

    by_patient: dict[str, sqlite3.Row] = {}
    for v in visits:
        if v["status"] != "completed":
            continue
        key = v["patient_id"] or v["patient_name"]
        prev = by_patient.get(key)
        if not prev or v["performed_date"] > prev["performed_date"]:
            by_patient[key] = v

    for v in sorted(by_patient.values(), key=lambda r: (r["performed_date"], r["patient_name"])):
        ins = v["insurance_type"] or "unknown"
        dl = deadline_for(date.fromisoformat(v["performed_date"]), ins)
        lines.append(
            f"| {v['performed_date']} | {v['doctor']} | {v['patient_name']} | "
            f"{insurance_label_ja(ins)} | **{dl.isoformat()}** | {v['patient_id'] or '—'} |"
        )

    lines.extend(["", "## セッション別ルート", ""])
    for s in sessions:
        lines.append(f"### {s['performed_date']} {s['doctor']}（{s['driver'] or '—'}）")
        if s["departure"]:
            lines.append(f"- 出発: {s['departure']}")
        if s["note"]:
            lines.append(f"- 備考: {s['note']}")
        lines.append("")
        lines.append("| # | 氏名 | 予定 | 住所 |")
        lines.append("|---|------|------|------|")
        for v in visits:
            if v["session_id"] != s["session_id"]:
                continue
            lines.append(
                f"| {v['route_order']} | {v['patient_name']} | {v['time_window'] or '—'} | {v['address'] or '—'} |"
            )
        lines.append("")

    if deferred:
        lines.extend(["## 未実施・リスケ", ""])
        lines.append("| 予定日 | 氏名 | 状態 | 理由 |")
        lines.append("|--------|------|------|------|")
        for d in deferred:
            lines.append(
                f"| {d['planned_date'] or '—'} | {d['patient_name']} | {d['status']} | {d['reason'] or d['note'] or '—'} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 要確認（JSON needs_confirmation）",
            "",
            "`records/data/confirmed_visits.json` の `needs_confirmation` を参照。",
            "別日実施・休止・台帳のみの記録がある方は、次回ルート確定時に追記してください。",
            "",
        ]
    )

    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote: {OUT_PATH}")


if __name__ == "__main__":
    main()
