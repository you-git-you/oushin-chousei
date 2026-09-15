# -*- coding: utf-8 -*-
"""raw/ の CSV を SQLite 正本へ取り込む。

取込順:
  1. schema 適用
  2. staff（往診ルール）
  3. patients（台帳）
  4. events（予約履歴 → 往診履歴 → クリニック）
  5. status_changes（休止）＋ patients.status 同期
  6. notes（訪問診療）
  7. 未突合イベント用の仮患者作成
"""

from __future__ import annotations

import csv
import hashlib
import sqlite3
import sys
from datetime import date
from pathlib import Path

# scripts/ を import path に追加
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DB_PATH,
    RAW_DIR,
    SCHEMA_PATH,
    classify_insurance,
    display_name,
    extract_notion_id,
    find_raw,
    map_ledger_status,
    norm_name,
    normalize_chart_id,
    parse_date,
    patient_id_from_visit_code,
    to_iso,
    visit_code_from_chart,
)


def load_csv(path: Path) -> list[dict[str, str]]:
    """UTF-8 BOM 付き CSV を Dict のリストで読む。"""
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def make_event_id(source: str, *parts: str) -> str:
    """ソースとキー部品から安定した event_id を生成する。"""
    raw = "|".join([source, *[p or "" for p in parts]])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def connect() -> sqlite3.Connection:
    """DB接続を開き外部キーを有効化する。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    """schema.sql を適用する。"""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)


def import_staff(conn: sqlite3.Connection) -> int:
    """往診ルールから医師・ドライバーを投入する。"""
    rows = [
        ("doc_hanawa", "doctor", "花輪 滋", "はなわ しげる", "院長"),
        ("doc_katayama", "doctor", "片山 容一", "かたやま よういち", ""),
        ("doc_torigoe", "doctor", "鳥越 和憲", "とりごえ かずのり", ""),
        ("drv_uesugi", "driver", "上杉", "", ""),
        ("drv_arai", "driver", "荒井", "", ""),
        ("drv_ishibashi", "driver", "石橋", "", ""),
        ("drv_miyajima", "driver", "宮嶋", "", ""),
    ]
    conn.executemany(
        "INSERT INTO staff(staff_id, role, name, name_kana, note) VALUES (?,?,?,?,?)",
        rows,
    )
    return len(rows)


def import_patients(conn: sqlite3.Connection) -> dict[str, str]:
    """台帳を patients に取り込む。戻り値: norm_name → patient_id。"""
    rows = load_csv(find_raw("台帳"))
    name_index: dict[str, str] = {}
    for r in rows:
        chart_raw = (r.get("ID") or "").strip()
        patient_id, chart_id = normalize_chart_id(chart_raw)
        if not patient_id:
            continue
        insurance_type, care_level = classify_insurance(r.get("介護度"))
        status = map_ledger_status(r.get("状態"))
        name = display_name(r.get("氏名"))
        notion_id = extract_notion_id(r.get("元データ")) or extract_notion_id(
            r.get("休止・再開履歴")
        )
        visit_code = visit_code_from_chart(chart_id)
        birth = to_iso(parse_date(r.get("生年月日")))
        start = to_iso(parse_date(r.get("開始日")))
        end = to_iso(parse_date(r.get("終了日")))
        updated = to_iso(parse_date(r.get("更新日時"))) or (r.get("更新日時") or "").strip()

        conn.execute(
            """
            INSERT INTO patients (
                patient_id, chart_id, visit_code, notion_page_id,
                name, name_kana, birth_date, sex,
                insurance_type, care_level, status,
                address, postal_code, tel, main_staff, primary_doctor,
                care_manager, care_office, hospital_name,
                start_date, end_date, end_reason,
                public_expense, copay_rate, self_pay_type,
                limit_amount, limit_note, limit_expire, tags, note, updated_at, matched
            ) VALUES (
               ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1
            )
            """,
            (
                patient_id,
                chart_id,
                visit_code,
                notion_id,
                name,
                display_name(r.get("ふりがな")),
                birth,
                (r.get("性別") or "").strip() or None,
                insurance_type,
                care_level,
                status,
                (r.get("利用者住所") or "").strip() or None,
                (r.get("利用者郵便") or "").strip() or None,
                (r.get("利用者TEL") or "").strip() or None,
                (r.get("メイン担当") or "").strip() or None,
                display_name(r.get("主治医")) or None,
                display_name(r.get("ケアマネ")) or None,
                (r.get("居宅名") or "").strip() or None,
                (r.get("病院名") or "").strip() or None,
                start,
                end,
                (r.get("理由") or "").strip() or None,
                (r.get("公費") or "").strip() or None,
                (r.get("負担割合") or "").strip() or None,
                (r.get("自費区分") or "").strip() or None,
                (r.get("限度額") or "").strip() or None,
                (r.get("限度額備考") or "").strip() or None,
                (r.get("限度額期限") or "").strip() or None,
                (r.get("タグ") or "").strip() or None,
                (r.get("備考") or "").strip() or None,
                updated or None,
            ),
        )
        nn = norm_name(name)
        if nn:
            name_index[nn] = patient_id
    return name_index


def ensure_placeholder_patient(
    conn: sqlite3.Connection,
    patient_id: str,
    name: str,
    visit_code: str | None = None,
) -> None:
    """台帳に無い患者を仮登録する（matched=0）。"""
    existing = conn.execute(
        "SELECT 1 FROM patients WHERE patient_id = ?", (patient_id,)
    ).fetchone()
    if existing:
        # visit_code が空なら補完
        if visit_code:
            conn.execute(
                """
                UPDATE patients SET visit_code = COALESCE(visit_code, ?)
                WHERE patient_id = ?
                """,
                (visit_code, patient_id),
            )
        return
    chart_id = None
    if patient_id.startswith("b") and patient_id[1:].isdigit():
        chart_id = f"b{int(patient_id[1:])}"
    conn.execute(
        """
        INSERT INTO patients (
            patient_id, chart_id, visit_code, name, insurance_type, status, matched
        ) VALUES (?, ?, ?, ?, 'unknown', 'active', 0)
        """,
        (
            patient_id,
            chart_id,
            visit_code,
            display_name(name) or patient_id,
        ),
    )


def resolve_patient_id(
    conn: sqlite3.Connection,
    name_index: dict[str, str],
    *,
    visit_code: str | None = None,
    chart_id: str | None = None,
    notion_id: str | None = None,
    name: str | None = None,
) -> str | None:
    """各種キーから patient_id を解決する。"""
    if visit_code and visit_code.strip().isdigit():
        pid = patient_id_from_visit_code(visit_code)
        if pid:
            row = conn.execute(
                "SELECT patient_id FROM patients WHERE patient_id = ? OR visit_code = ?",
                (pid, f"{int(visit_code):06d}"),
            ).fetchone()
            if row:
                return row["patient_id"]
            return pid  # 後で placeholder

    if chart_id:
        pid, _ = normalize_chart_id(chart_id)
        if pid:
            row = conn.execute(
                "SELECT patient_id FROM patients WHERE patient_id = ? OR chart_id = ?",
                (pid, chart_id.strip()),
            ).fetchone()
            if row:
                return row["patient_id"]
            return pid

    if notion_id:
        row = conn.execute(
            "SELECT patient_id FROM patients WHERE notion_page_id = ?",
            (notion_id.lower(),),
        ).fetchone()
        if row:
            return row["patient_id"]

    nn = norm_name(name)
    if nn and nn in name_index:
        return name_index[nn]

    return None


def insert_event(
    conn: sqlite3.Connection,
    seen: set[tuple],
    *,
    patient_id: str,
    event_type: str,
    status: str,
    performed_at: date | None,
    scheduled_at: date | None,
    doctor_name: str | None,
    driver_name: str | None,
    area: str | None,
    note: str | None,
    source: str,
    source_row_id: str | None,
) -> bool:
    """重複を避けて events に1件挿入する。True=挿入した。"""
    perf = to_iso(performed_at)
    sched = to_iso(scheduled_at)
    # 同一患者・同一実施日・同一種別・同一ソースは重複とみなす
    dedupe_key = (patient_id, perf or sched, event_type, source)
    if dedupe_key in seen:
        return False
    # DB上の既存も確認（再実行時）
    if perf:
        exists = conn.execute(
            """
            SELECT 1 FROM events
            WHERE patient_id = ? AND performed_at = ? AND event_type = ? AND source = ?
            """,
            (patient_id, perf, event_type, source),
        ).fetchone()
        if exists:
            return False

    event_id = make_event_id(
        source, patient_id, event_type, perf or sched or "", source_row_id or ""
    )
    # event_id 衝突時はサフィックス
    base = event_id
    n = 0
    while conn.execute(
        "SELECT 1 FROM events WHERE event_id = ?", (event_id,)
    ).fetchone():
        n += 1
        event_id = f"{base}{n}"

    # 実施済みのみ performed_at を持つ。予定・キャンセルは scheduled_at のみ。
    if status in ("completed", "needs_review"):
        performed_iso = perf or sched
        scheduled_iso = sched or perf
    else:
        performed_iso = None
        scheduled_iso = sched or perf

    conn.execute(
        """
        INSERT INTO events (
            event_id, patient_id, event_type, scheduled_at, performed_at,
            status, doctor_name, driver_name, area, note, source, source_row_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            event_id,
            patient_id,
            event_type,
            scheduled_iso,
            performed_iso,
            status,
            doctor_name,
            driver_name,
            area,
            note,
            source,
            source_row_id,
        ),
    )
    seen.add(dedupe_key)
    return True


def import_events_yoyaku(
    conn: sqlite3.Connection, name_index: dict[str, str], seen: set[tuple]
) -> int:
    """往診予約履歴を events へ。"""
    rows = load_csv(find_raw("往診予約"))
    count = 0
    today = date.today()
    type_map = {"往診": "home_visit", "通院": "clinic_visit", "電話": "phone"}
    for r in rows:
        s_type = (r.get("s_type") or "").strip()
        event_type = type_map.get(s_type)
        if not event_type:
            continue
        dt = parse_date(r.get("s_date"))
        if not dt:
            continue
        chart_id = (r.get("台帳ID") or "").strip()
        name = r.get("台帳氏名") or r.get("s_name")
        pid = resolve_patient_id(
            conn, name_index, chart_id=chart_id, name=name
        )
        if not pid:
            pid = f"unmatched_{norm_name(name) or (r.get('ID') or 'x')}"
            ensure_placeholder_patient(conn, pid, display_name(name) or pid)
        else:
            # 台帳に無い正規化IDの場合
            ensure_placeholder_patient(
                conn, pid, display_name(name) or pid, visit_code_from_chart(chart_id)
            )

        # 本日以前は実績(completed)、未来日は予定(scheduled)
        if dt <= today:
            status = "completed"
            performed = dt
        else:
            status = "scheduled"
            performed = None
        if insert_event(
            conn,
            seen,
            patient_id=pid,
            event_type=event_type,
            status=status,
            performed_at=performed,
            scheduled_at=dt,
            doctor_name=(r.get("s_dr") or "").strip() or None,
            driver_name=None,
            area=None,
            note=None,
            source="yoyaku",
            source_row_id=(r.get("ID") or "").strip() or None,
        ):
            count += 1
    return count


def import_events_oushin(
    conn: sqlite3.Connection, name_index: dict[str, str], seen: set[tuple]
) -> int:
    """往診履歴を events へ。"""
    rows = load_csv(find_raw("往診履歴"))
    count = 0
    status_map = {
        "完了": "completed",
        "要確認": "needs_review",
        "予定": "scheduled",
        "キャンセル": "cancelled",
    }
    for r in rows:
        raw_st = (r.get("ステータス") or "").strip()
        status = status_map.get(raw_st)
        if not status:
            continue
        dt = parse_date(r.get("往診日時"))
        if not dt:
            continue
        visit_code = (r.get("患者ID") or "").strip()
        name = r.get("利用者氏名")
        notion_id = extract_notion_id(r.get("患者台帳"))
        pid = resolve_patient_id(
            conn,
            name_index,
            visit_code=visit_code,
            notion_id=notion_id,
            name=name,
        )
        if not pid:
            if visit_code and visit_code.isdigit():
                pid = patient_id_from_visit_code(visit_code)
            else:
                pid = f"unmatched_{norm_name(name) or 'unknown'}"
            ensure_placeholder_patient(
                conn,
                pid,
                display_name(name) or pid,
                f"{int(visit_code):06d}" if visit_code and visit_code.isdigit() else None,
            )
        else:
            ensure_placeholder_patient(
                conn,
                pid,
                display_name(name) or pid,
                f"{int(visit_code):06d}" if visit_code and visit_code.isdigit() else None,
            )

        performed = dt if status in ("completed", "needs_review") else None
        scheduled = dt
        if insert_event(
            conn,
            seen,
            patient_id=pid,
            event_type="home_visit",
            status=status,
            performed_at=performed,
            scheduled_at=scheduled,
            doctor_name=(r.get("医師") or "").strip() or None,
            driver_name=(r.get("担当・送迎") or "").strip() or None,
            area=(r.get("住所・エリア") or "").strip() or None,
            note=(r.get("備考") or "").strip() or None,
            source="oushin_rireki",
            source_row_id=f"{visit_code}:{to_iso(dt)}:{raw_st}",
        ):
            count += 1
    return count


def import_events_clinic(
    conn: sqlite3.Connection, name_index: dict[str, str], seen: set[tuple]
) -> int:
    """クリニック受診を events へ。"""
    rows = load_csv(find_raw("クリニック"))
    count = 0
    today = date.today()
    for r in rows:
        if (r.get("患者") or "").strip() == "全体":
            continue
        post = parse_date(r.get("投稿日時"))
        dt = parse_date(r.get("受診予定"), hint_date=post)
        if not dt:
            continue
        name = r.get("患者")
        notion_id = extract_notion_id(r.get("台帳")) or extract_notion_id(r.get("台帳ID"))
        pid = resolve_patient_id(conn, name_index, notion_id=notion_id, name=name)
        if not pid:
            pid = f"unmatched_{norm_name(name) or 'clinic'}"
            ensure_placeholder_patient(conn, pid, display_name(name) or pid)

        # 本日以前 → completed、未来 → scheduled
        if dt <= today:
            status = "completed"
            performed = dt
        else:
            status = "scheduled"
            performed = None

        note_parts = [
            (r.get("目的") or "").strip(),
            (r.get("原文要約") or "").strip(),
        ]
        note = " / ".join(p for p in note_parts if p) or None

        if insert_event(
            conn,
            seen,
            patient_id=pid,
            event_type="clinic_visit",
            status=status,
            performed_at=performed,
            scheduled_at=dt,
            doctor_name=(r.get("医師希望") or "").strip() or None,
            driver_name=None,
            area=None,
            note=note,
            source="clinic",
            source_row_id=(r.get("台帳ID") or r.get("件名") or "").strip() or None,
        ):
            count += 1
    return count


def import_status_changes(
    conn: sqlite3.Connection, name_index: dict[str, str]
) -> int:
    """休止・再開管理を status_changes へ。休止中は patients.status を paused に。"""
    rows = load_csv(find_raw("休止"))
    count = 0
    for i, r in enumerate(rows):
        # 列名が '1利用者名' の場合あり
        name = r.get("1利用者名") or r.get("利用者名") or ""
        nn = norm_name(name)
        pid = name_index.get(nn)
        notion_id = extract_notion_id(r.get("訪問リハビリ台帳"))
        if not pid and notion_id:
            row = conn.execute(
                "SELECT patient_id FROM patients WHERE notion_page_id = ?",
                (notion_id,),
            ).fetchone()
            if row:
                pid = row["patient_id"]
        if not pid:
            pid = resolve_patient_id(conn, name_index, name=name)
        if not pid:
            pid = f"unmatched_{nn or f'pause{i}'}"
            ensure_placeholder_patient(conn, pid, display_name(name) or pid)

        change_id = make_event_id("pause", pid, r.get("休止日") or "", str(i))
        effective = to_iso(parse_date(r.get("休止日")))
        planned = to_iso(parse_date(r.get("再開予定日")))
        resumed = to_iso(parse_date(r.get("再開日")))
        reason = (r.get("休止理由・経過") or "").strip()
        # 枠解除の言及を簡易検出
        slot = None
        if "枠解除" in reason or "枠を一旦解除" in reason or "枠は一旦解除" in reason:
            slot = 1

        change_type = "pause"
        st = (r.get("状態") or "").strip()
        if st == "再開" or resumed:
            change_type = "resume" if resumed else "pause"

        conn.execute(
            """
            INSERT INTO status_changes (
                change_id, patient_id, change_type, effective_date,
                planned_resume_date, resume_date, reason, staff, slot_released, source_row
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                change_id,
                pid,
                change_type,
                effective,
                planned,
                resumed,
                reason or None,
                display_name(r.get("担当スタッフ")) or None,
                slot,
                (r.get("元データ行") or "").strip() or None,
            ),
        )
        # 休止中なら患者状態を更新（終了は上書きしない）
        if st == "休止中":
            conn.execute(
                """
                UPDATE patients SET status = 'paused'
                WHERE patient_id = ? AND status NOT IN ('ended')
                """,
                (pid,),
            )
        count += 1
    return count


def import_notes(conn: sqlite3.Connection, name_index: dict[str, str]) -> int:
    """訪問診療メモを notes へ。"""
    rows = load_csv(find_raw("訪問診療"))
    count = 0
    for i, r in enumerate(rows):
        visit_code = (r.get("利用者ID") or "").strip()
        name = r.get("患者")
        notion_id = extract_notion_id(r.get("台帳"))
        pid = None
        if name and name.strip() != "全体":
            pid = resolve_patient_id(
                conn,
                name_index,
                visit_code=visit_code if visit_code.isdigit() else None,
                notion_id=notion_id,
                name=name,
            )
        note_id = make_event_id("note", str(i), r.get("件名") or "", r.get("投稿日時") or "")
        edited = 1 if (r.get("編集済み") or "").strip().lower() in ("yes", "true", "1") else 0
        conn.execute(
            """
            INSERT INTO notes (
                note_id, patient_id, title, category, staff, doctor_name,
                planned_at, body, posted_at, edited, source
            ) VALUES (?,?,?,?,?,?,?,?,?,?, 'homecare_ops')
            """,
            (
                note_id,
                pid,
                (r.get("件名") or "").strip() or None,
                (r.get("区分") or "").strip() or None,
                (r.get("スタッフ") or "").strip() or None,
                (r.get("医師") or "").strip() or None,
                (r.get("予定日時") or "").strip() or None,
                (r.get("内容") or "").strip() or None,
                (r.get("投稿日時") or "").strip() or None,
                edited,
            ),
        )
        count += 1
    return count


def enrich_notion_ids(conn: sqlite3.Connection) -> int:
    """往診履歴・予約の Notion URL から notion_page_id を補完する。"""
    updated = 0
    # 往診履歴
    for r in load_csv(find_raw("往診履歴")):
        nid = extract_notion_id(r.get("患者台帳"))
        vc = (r.get("患者ID") or "").strip()
        if not nid or not vc.isdigit():
            continue
        pid = patient_id_from_visit_code(vc)
        cur = conn.execute(
            "SELECT notion_page_id FROM patients WHERE patient_id = ?", (pid,)
        ).fetchone()
        if cur and not cur["notion_page_id"]:
            conn.execute(
                "UPDATE patients SET notion_page_id = ? WHERE patient_id = ?",
                (nid, pid),
            )
            updated += 1
    # 予約履歴のリンク
    for r in load_csv(find_raw("往診予約")):
        nid = extract_notion_id(r.get("訪問リハ台帳"))
        chart = (r.get("台帳ID") or "").strip()
        if not nid or not chart:
            continue
        pid, _ = normalize_chart_id(chart)
        if not pid:
            continue
        cur = conn.execute(
            "SELECT notion_page_id FROM patients WHERE patient_id = ?", (pid,)
        ).fetchone()
        if cur and not cur["notion_page_id"]:
            conn.execute(
                "UPDATE patients SET notion_page_id = ? WHERE patient_id = ?",
                (nid, pid),
            )
            updated += 1
    return updated


def write_unmatched_export(conn: sqlite3.Connection) -> Path:
    """未突合・要確認患者を Markdown 出力する。"""
    from common import EXPORTS_DIR

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORTS_DIR / "unmatched_patients.md"
    rows = conn.execute(
        """
        SELECT patient_id, name, visit_code, chart_id, insurance_type, status, matched
        FROM patients
        WHERE matched = 0 OR insurance_type = 'unknown'
        ORDER BY matched, name
        """
    ).fetchall()

    lines = [
        "# 要確認・未突合患者",
        "",
        f"件数: {len(rows)}",
        "",
        "| patient_id | 氏名 | visit_code | chart_id | 区分 | 状態 | matched |",
        "|---|---|---|---|---|---|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['patient_id']} | {r['name']} | {r['visit_code'] or ''} | "
            f"{r['chart_id'] or ''} | {r['insurance_type']} | {r['status']} | {r['matched']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    """エントリポイント。"""
    if not RAW_DIR.exists():
        raise SystemExit(f"raw/ がありません: {RAW_DIR}")

    print(f"DB: {DB_PATH}")
    conn = connect()
    try:
        apply_schema(conn)
        n_staff = import_staff(conn)
        print(f"staff: {n_staff}")

        name_index = import_patients(conn)
        n_patients = conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
        print(f"patients: {n_patients}")

        seen: set[tuple] = set()
        n_y = import_events_yoyaku(conn, name_index, seen)
        print(f"events from yoyaku: {n_y}")
        n_o = import_events_oushin(conn, name_index, seen)
        print(f"events from oushin_rireki: {n_o}")
        n_c = import_events_clinic(conn, name_index, seen)
        print(f"events from clinic: {n_c}")

        n_sc = import_status_changes(conn, name_index)
        print(f"status_changes: {n_sc}")

        n_notes = import_notes(conn, name_index)
        print(f"notes: {n_notes}")

        n_notion = enrich_notion_ids(conn)
        print(f"notion_page_id enriched: {n_notion}")

        unmatched_path = write_unmatched_export(conn)
        print(f"unmatched export: {unmatched_path}")

        conn.commit()

        # サマリ
        summary = {
            "patients": conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0],
            "patients_matched": conn.execute(
                "SELECT COUNT(*) FROM patients WHERE matched = 1"
            ).fetchone()[0],
            "patients_unmatched": conn.execute(
                "SELECT COUNT(*) FROM patients WHERE matched = 0"
            ).fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "events_completed": conn.execute(
                "SELECT COUNT(*) FROM events WHERE status IN ('completed','needs_review')"
            ).fetchone()[0],
            "paused": conn.execute(
                "SELECT COUNT(*) FROM patients WHERE status = 'paused'"
            ).fetchone()[0],
            "iryo": conn.execute(
                "SELECT COUNT(*) FROM patients WHERE insurance_type = 'iryo' AND status != 'ended'"
            ).fetchone()[0],
            "jihi": conn.execute(
                "SELECT COUNT(*) FROM patients WHERE insurance_type = 'jihi' AND status != 'ended'"
            ).fetchone()[0],
        }
        print("--- summary ---")
        for k, v in summary.items():
            print(f"  {k}: {v}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
