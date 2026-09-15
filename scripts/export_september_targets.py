# -*- coding: utf-8 -*-
"""9月往診対象一覧を records/9月往診対象一覧_2026.md に出力する。"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, VISIT_RECORDS_DB_PATH, deadline_for, insurance_label_ja
from august_schedule_data import load_august_schedule_from_md
from clinic_visits import load_clinic_managed_patient_ids, load_last_clinic_visit_dates
from ledger_csv import load_ledger_index, sync_patients_from_ledger
from last_visit import LastVisitIndex, load_confirmed_dates_from_visit_db

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "records" / "9月往診対象一覧_2026.md"
PAUSE_JSON = ROOT / "records" / "data" / "pause_resume_status.json"
CONFIRMED_JSON = ROOT / "records" / "data" / "confirmed_visits.json"
CLINIC_PRIMARY_JSON = ROOT / "records" / "data" / "clinic_primary_visits.json"
AUG_MED_JSON = ROOT / "records" / "data" / "august_2026_medical.json"
AUG_SCHED_JSON = ROOT / "records" / "data" / "august_2026_schedule.json"

# 8月リストに残すがキャンセル扱いで、9月往診対象へ移す
SEPTEMBER_MOVED_FROM_AUGUST_CANCEL = {
    "b492": {
        "name": "大和紀代子",
        "ins": "kaigo",
        "priority": "9月1回必要",
        "category": "8月キャンセル→9月",
        "note": "8/15(土)往診キャンセルのため9月へ移動。",
        "august_planned": "8/15キャンセル",
    },
}

_AUG_PID_RE = re.compile(r"^b\d{3}$")

INS_JA_TO_CODE = {"医療": "iryo", "介護": "kaigo", "自費": "jihi", "不明": "unknown"}
INS_CODE_ORDER = {"iryo": 0, "kaigo": 1, "jihi": 2, "unknown": 3}
TAIL_CATEGORIES = frozenset({"要確認", "7月未実施", "休止（参照）", "終了（参照）"})


def is_valid_august_patient_id(pid: str | None) -> bool:
    return bool(pid and _AUG_PID_RE.fullmatch(pid))


def load_august_schedule_map() -> dict[str, dict]:
    """8月往診リスト掲載者（patient_id -> 予定）。"""
    from_md = load_august_schedule_from_md()
    if AUG_SCHED_JSON.is_file():
        raw = json.loads(AUG_SCHED_JSON.read_text(encoding="utf-8"))
        from_json = {
            p["patient_id"]: p
            for p in raw.get("patients", [])
            if is_valid_august_patient_id(p.get("patient_id"))
        }
        if len(from_json) >= len(from_md) * 0.9 and len(from_json) >= 50:
            return from_json
    return from_md


def kana_sort_key(kana: str, name: str) -> str:
    base = (kana or "").replace(" ", "").replace("　", "")
    if base:
        return base
    return name or ""


def list_section_for(ins_code: str, category: str) -> str:
    if ins_code == "iryo":
        return "医療"
    if category in TAIL_CATEGORIES or "休止" in category or "終了" in category:
        return "その他"
    if ins_code == "kaigo":
        return "介護"
    if ins_code == "jihi":
        return "自費"
    return "その他"


def home_sort_key(r: dict) -> tuple:
    section = r.get("list_section", "その他")
    section_order = {"医療": 0, "介護": 1, "自費": 2, "その他": 9}[section]
    tail = 1 if r.get("category") in TAIL_CATEGORIES else 0
    if section == "医療":
        tail = 0
    return (section_order, tail, r.get("sort_kana", ""), r.get("name", ""))


def main() -> None:
    ledger_path = sync_patients_from_ledger()
    ledger_index = load_ledger_index()
    if ledger_path:
        print(f"Ledger synced: {ledger_path.name} ({len(ledger_index)} rows)")

    pause = {
        r["patient_id"]: r
        for r in json.loads(PAUSE_JSON.read_text(encoding="utf-8"))["records"]
    }
    aug_med = {
        p["patient_id"]: p
        for p in json.loads(AUG_MED_JSON.read_text(encoding="utf-8"))["patients"]
    }
    aug_schedule = load_august_schedule_map()
    august_list_pids = set(aug_schedule)

    clinic_primary = {
        p["patient_id"]: p
        for p in json.loads(CLINIC_PRIMARY_JSON.read_text(encoding="utf-8"))["patients"]
    }
    clinic_managed = load_clinic_managed_patient_ids()
    clinic_last = load_last_clinic_visit_dates()

    conn_v = sqlite3.connect(VISIT_RECORDS_DB_PATH)
    conn_v.row_factory = sqlite3.Row
    confirmed = {}
    for row in conn_v.execute(
        """
        SELECT cv.patient_id, cv.patient_name, cs.performed_date,
               cv.insurance_type, cs.doctor
        FROM confirmed_visits cv
        JOIN confirmed_sessions cs ON cs.session_id = cv.session_id
        WHERE cv.status = 'completed' AND cv.patient_id IS NOT NULL
        """
    ):
        pid = row["patient_id"]
        if pid not in confirmed or row["performed_date"] > confirmed[pid]["performed_date"]:
            confirmed[pid] = dict(row)
    deferred = [dict(r) for r in conn_v.execute("SELECT * FROM confirmed_deferred")]

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    def pinfo(pid: str):
        return conn.execute(
            """
            SELECT name, name_kana, insurance_type, main_staff, status
            FROM patients WHERE patient_id = ?
            """,
            (pid,),
        ).fetchone()

    def operational_status(pid: str) -> str:
        pr = pause.get(pid)
        if pr and pr["current_status"] == "paused":
            return "休止"
        if pr and pr["current_status"] == "ended":
            return "終了"
        p = pinfo(pid)
        if p:
            if p["status"] == "paused":
                return "休止"
            if p["status"] == "ended":
                return "終了"
        led = ledger_index.get(pid)
        if led:
            if led["ledger_status"] == "paused":
                return "休止"
            if led["ledger_status"] == "ended":
                return "終了"
        return ""

    def append_status_reason_to_note(pid: str, row: dict) -> None:
        st = row.get("operational_status")
        if st not in ("休止", "終了"):
            return
        note = (row.get("note") or "").strip()
        if f"【{st}理由】" in note:
            return
        to_add: list[str] = []
        pr = pause.get(pid)
        if pr and pr.get("current_status") in ("paused", "ended"):
            r = (pr.get("reason") or "").strip()
            if r and r not in note:
                to_add.append(r)
        led = ledger_index.get(pid)
        if led:
            lr = (led.get("ledger_reason") or "").strip()
            if lr and lr not in note and lr not in to_add:
                to_add.append(lr)
        if not to_add:
            return
        label = f"【{st}理由】{'／'.join(to_add)}"
        row["note"] = f"{note}／{label}" if note else label

    def enrich_row(pid: str, row: dict) -> None:
        p = pinfo(pid)
        led = ledger_index.get(pid)
        kana = ""
        if p and p["name_kana"]:
            kana = p["name_kana"]
        elif led:
            kana = led.get("name_kana", "")
        row["sort_kana"] = kana_sort_key(kana, row["name"])
        row["name_kana"] = (kana or "").strip()
        row["operational_status"] = operational_status(pid)
        ins_code = INS_JA_TO_CODE.get(row["insurance"], "unknown")
        row["ins_code"] = ins_code
        row["list_section"] = list_section_for(ins_code, row["category"])
        append_status_reason_to_note(pid, row)

    last_visit_index = LastVisitIndex.build(
        confirmed_dates={
            **load_confirmed_dates_from_visit_db(),
            **{pid: d["performed_date"] for pid, d in confirmed.items()},
        }
    )

    def home_last(pid: str) -> str | None:
        """最終往診日（往診のみ。7月は確定実施ルート）。"""
        base = last_visit_index.last_performed_date(pid)
        if not base and pid in confirmed:
            base = confirmed[pid]["performed_date"]
        return base

    def clinic_last_display(pid: str) -> str | None:
        return clinic_last.get(pid) or home_last(pid)

    def deadline_basis_date(pid: str, insurance: str, *, for_clinic: bool = False) -> str | None:
        """期限計算用。医療6名は8月最終予定日ベース、他は実施済み最終日。"""
        if for_clinic:
            el = clinic_last_display(pid)
            if el:
                return el
        if insurance == "iryo" and pid in aug_med and not for_clinic:
            return aug_med[pid]["last_planned"]
        last = home_last(pid)
        if last:
            return last
        if pid in aug_schedule and not for_clinic:
            return aug_schedule[pid].get("last_planned")
        return None

    rows: dict[str, dict] = {}
    clinic_rows: dict[str, dict] = {}

    def keep_despite_august_list(pid: str, insurance: str | None = None) -> bool:
        """8月往診リスト掲載でも9月一覧に残す（医療、および8月キャンセル→9月）。"""
        if pid in SEPTEMBER_MOVED_FROM_AUGUST_CANCEL:
            return True
        if pid in aug_med:
            return True
        if insurance == "iryo":
            return True
        p = pinfo(pid)
        return bool(p and p["insurance_type"] == "iryo")

    def on_august_home_list(pid: str) -> bool:
        return pid in august_list_pids

    def set_row(pid: str, **kw: object) -> None:
        if not pid:
            return
        if pid in clinic_managed:
            set_clinic_row(pid, **kw)
            return
        p = pinfo(pid)
        ins = str(kw.get("ins") or (p["insurance_type"] if p else "unknown"))
        if on_august_home_list(pid) and not keep_despite_august_list(pid, ins):
            return
        last = str(kw.get("last") or home_last(pid) or "—")
        aug_plan = str(kw.get("august_planned") or "")
        dl = str(kw.get("deadline") or "")
        if not dl:
            basis = deadline_basis_date(pid, ins)
            if basis:
                dl = deadline_for(date.fromisoformat(basis), ins).isoformat()
            elif last != "—":
                dl = deadline_for(date.fromisoformat(last), ins).isoformat()
            else:
                dl = "要確認"
        name = str(kw.get("name") or (p["name"] if p else pid)).replace(" ", "")
        row = {
            "patient_id": pid,
            "name": name,
            "insurance": insurance_label_ja(ins),
            "last_performed": last,
            "august_planned": aug_plan,
            "deadline": dl,
            "priority": str(kw["priority"]),
            "category": str(kw["category"]),
            "main_staff": (p["main_staff"] if p else "") or "",
            "note": str(kw.get("note", "")),
        }
        enrich_row(pid, row)
        rows[pid] = row

    def set_clinic_row(pid: str, **kw: object) -> None:
        p = pinfo(pid)
        ins = str(kw.get("ins") or (p["insurance_type"] if p else "unknown"))
        last = clinic_last_display(pid) or "—"
        last = str(last)
        dl = str(kw.get("deadline") or "")
        if not dl:
            basis = deadline_basis_date(pid, ins, for_clinic=True)
            if basis:
                dl = deadline_for(date.fromisoformat(basis), ins).isoformat()
            elif last != "—":
                dl = deadline_for(date.fromisoformat(last), ins).isoformat()
            else:
                dl = "要確認"
        cp = clinic_primary.get(pid, {})
        name = str(kw.get("name") or cp.get("name") or (p["name"] if p else pid)).replace(" ", "")
        note = cp.get("remark") or "クリニック受診（通院・実施扱い）"
        extra = str(kw.get("note", ""))
        if extra and extra not in note:
            note = f"{note}／{extra}"
        clinic_rows[pid] = {
            "patient_id": pid,
            "name": name,
            "insurance": insurance_label_ja(ins),
            "last_performed": last,
            "deadline": dl,
            "priority": str(kw.get("priority") or "通院管理"),
            "category": "通院（クリニック受診）",
            "main_staff": (p["main_staff"] if p else "") or "",
            "note": note,
        }
        enrich_row(pid, clinic_rows[pid])

    # 8月リスト・医療（優先）
    for pid, am in aug_med.items():
        set_row(
            pid,
            name=am["name"],
            ins="iryo",
            last=home_last(pid),
            august_planned=am["last_planned"],
            deadline=am["deadline_after_august"],
            priority=am["september_need"],
            category="8月予定（医療）",
            note=f"8月: {', '.join(am['august_visits'])}。{am['schedule_note']}",
        )

    # 7月確定・介護など（医療は8月側で上書き済み）
    for pid, d in confirmed.items():
        if pid in rows:
            continue
        p = pinfo(pid)
        ins = d["insurance_type"] or (p["insurance_type"] if p else "kaigo")
        if ins == "iryo":
            continue
        ld = d["performed_date"]
        dl = deadline_for(date.fromisoformat(ld), ins)
        if dl.month == 9 and dl.year == 2026:
            set_row(
                pid,
                name=d["patient_name"],
                ins=ins,
                last=ld,
                priority="9月1回必要",
                category="7月実施済",
                note=f"7月実施({d['doctor']})",
            )

    # 7月未実施（医療で8月配置済みはスキップ・7月確定済みはスキップ）
    for d in deferred:
        pid = d.get("patient_id")
        if not pid or pid in rows or pid in confirmed:
            continue
        pri = "8-9月で要1回"
        last = home_last(pid)
        if last:
            ins = pinfo(pid)["insurance_type"]
            dl = deadline_for(date.fromisoformat(last), ins)
            if dl < date(2026, 8, 1):
                pri = "最優先（期限7月末超過）"
        set_row(
            pid,
            name=d["patient_name"],
            priority=pri,
            category="7月未実施",
            note=d.get("reason") or "",
            last=last,
        )

    with CONFIRMED_JSON.open(encoding="utf-8") as f:
        for nc in json.load(f).get("needs_confirmation", []):
            pid = nc.get("patient_id")
            if not pid or pid in rows:
                continue
            last = home_last(pid)
            pri = "要ヒアリング"
            if last:
                ins = pinfo(pid)["insurance_type"]
                if ins == "iryo" and pid in aug_med:
                    continue
                dl = deadline_for(date.fromisoformat(last), ins)
                if dl < date(2026, 8, 7):
                    pri = "期限超過の可能性"
            set_row(
                pid,
                name=nc["name"],
                priority=pri,
                category="要確認",
                note=nc.get("note", ""),
                last=last,
            )

    for pid, spec in SEPTEMBER_MOVED_FROM_AUGUST_CANCEL.items():
        set_row(
            pid,
            name=spec["name"],
            ins=spec["ins"],
            priority=spec["priority"],
            category=spec["category"],
            note=spec["note"],
            august_planned=spec["august_planned"],
            last=home_last(pid),
        )

    for pr in pause.values():
        if pr["current_status"] not in ("paused", "ended"):
            continue
        pid = pr["patient_id"]
        if pid in rows or pid in clinic_rows:
            if pid in rows:
                enrich_row(pid, rows[pid])
            continue
        cat = "休止（参照）" if pr["current_status"] == "paused" else "終了（参照）"
        set_row(
            pid,
            name=pr.get("patient_name", pid),
            priority="—",
            category=cat,
            note=(pr.get("reason") or "")[:120],
            last=home_last(pid),
        )

    for pid in sorted(clinic_managed):
        if pid not in clinic_rows:
            set_clinic_row(pid, priority="通院管理", note="")

    for r in rows.values():
        enrich_row(r["patient_id"], r)
    for r in clinic_rows.values():
        enrich_row(r["patient_id"], r)

    for pid, spec in SEPTEMBER_MOVED_FROM_AUGUST_CANCEL.items():
        row = rows.get(pid)
        if not row:
            continue
        row["operational_status"] = ""
        row["category"] = spec["category"]
        row["note"] = spec["note"]
        row["august_planned"] = spec["august_planned"]
        row["priority"] = spec["priority"]
        row["list_section"] = "介護"

    home_unique = sorted(rows.values(), key=home_sort_key)
    clinic_unique = sorted(
        clinic_rows.values(),
        key=lambda r: (INS_CODE_ORDER.get(r.get("ins_code", "unknown"), 9), r.get("sort_kana", ""), r["name"]),
    )
    n_confirmed_july = len(confirmed)

    med_section = [
        "## 8月往診リストの医療（6名）",
        "",
        "9月一覧では **8月の最終予定日＋30日** を期限目安に反映済み。",
        "",
        "| patient_id | 氏名 | フリガナ | 8月予定 | 期限（9月調整） |",
        "|------------|------|--------|---------|-----------------|",
    ]
    for am in sorted(aug_med.values(), key=lambda a: kana_sort_key(
        ledger_index.get(a["patient_id"], {}).get("name_kana", ""), a["name"]
    )):
        pid = am["patient_id"]
        mk = ledger_index.get(pid, {}).get("name_kana", "")
        if not mk:
            pr = pinfo(pid)
            mk = (pr["name_kana"] if pr and pr["name_kana"] else "") or ""
        med_section.append(
            f"| {pid} | {am['name']} | {mk} | "
            f"{', '.join(am['august_visits'])} | **{am['deadline_after_august']}** |"
        )
    med_section.append("")

    lines = [
        "# 2026年9月 往診対象一覧",
        "",
        f"基準日: **2026-08-07**（**7月確定{n_confirmed_july}名**）",
        "",
        "**並び**: 医療 → 介護・自費（各あいうえお順）→ 要確認・未実施・休止/終了参照。",
        "**8月往診リスト掲載の方（介護・自費など）は9月一覧から除外**（8月で調整済みのため）。",
        "**例外:** 8月キャンセルで9月へ移した方（大和紀代子）は掲載。",
        "**医療6名**のみ8月予定を踏まえて9月調整対象として掲載。",
        "**休止・終了**は削除せず「状態」列に表示（`records/data/pause_resume_status.json` 参照）。",
        "",
        "**最終往診日**は往診実施日（7月は確定実施ルート）。**通院**の方は下の別一覧。",
        "8月予定は往診一覧のみ別列。",
        "",
        f"**往診 {len(home_unique)}名** ／ **通院 {len(clinic_unique)}名**",
        "",
        *med_section,
        "## 使い方",
        "",
        "「スプレッドシート用」ブロック内をコピーし、シートの A1 に貼り付け。",
        "",
        "## 一覧（往診）",
        "",
        "| patient_id | 氏名 | フリガナ | 区分 | 状態 | 最終往診日 | 8月予定 | 期限 | 優先度 | カテゴリ | メイン担当 | 備考 |",
        "|------------|------|--------|------|------|------------|---------|------|--------|----------|------------|------|",
    ]
    for r in home_unique:
        lines.append(
            f"| {r['patient_id']} | {r['name']} | {r.get('name_kana', '')} | {r['insurance']} | "
            f"{r.get('operational_status', '')} | "
            f"{r['last_performed']} | "
            f"{r.get('august_planned', '')} | {r['deadline']} | {r['priority']} | {r['category']} | "
            f"{r['main_staff']} | {r['note']} |"
        )

    lines += [
        "",
        "## 一覧（通院・クリニック受診）",
        "",
        "往診調整の主一覧には含めず、通院ベースで期限・最終受診日を管理。",
        "",
        "| patient_id | 氏名 | フリガナ | 区分 | 状態 | 最終受診日 | 期限 | 優先度 | カテゴリ | メイン担当 | 備考 |",
        "|------------|------|--------|------|------|------------|------|--------|----------|------------|------|",
    ]
    for r in clinic_unique:
        lines.append(
            f"| {r['patient_id']} | {r['name']} | {r.get('name_kana', '')} | {r['insurance']} | "
            f"{r.get('operational_status', '')} | "
            f"{r['last_performed']} | "
            f"{r['deadline']} | {r['priority']} | {r['category']} | "
            f"{r['main_staff']} | {r['note']} |"
        )

    lines += ["", "## スプレッドシート用（タブ区切り）", "", "### 往診", "", "```text"]
    lines.append(
        "patient_id\t氏名\tフリガナ\t区分\t状態\t最終往診日\t8月予定\t期限\tメイン担当\t備考"
    )
    for r in home_unique:
        lines.append(
            "\t".join(
                [
                    r["patient_id"],
                    r["name"],
                    r.get("name_kana", ""),
                    r["insurance"],
                    r.get("operational_status", ""),
                    r["last_performed"],
                    r.get("august_planned", ""),
                    r["deadline"],
                    r["main_staff"],
                    r["note"],
                ]
            )
        )
    lines.append("```")
    lines += ["", "### 通院", "", "```text"]
    lines.append(
        "patient_id\t氏名\tフリガナ\t区分\t状態\t最終受診日\t期限\tメイン担当\t備考"
    )
    for r in clinic_unique:
        lines.append(
            "\t".join(
                [
                    r["patient_id"],
                    r["name"],
                    r.get("name_kana", ""),
                    r["insurance"],
                    r.get("operational_status", ""),
                    r["last_performed"],
                    r["deadline"],
                    r["main_staff"],
                    r["note"],
                ]
            )
        )
    lines.append("```")

    lines += [
        "",
        "## 休止・終了データ",
        "",
        "正本: [休止再開_現状一覧.md](./休止再開_現状一覧.md) ／ `records/data/pause_resume_status.json`（**アップロード済み**）",
        "",
    ]

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} (home={len(home_unique)} clinic={len(clinic_unique)})")
    print("Medical in home list:", sum(1 for r in home_unique if r["insurance"] == "医療"))

    from build_september_targets_html import main as build_html

    build_html()


if __name__ == "__main__":
    main()
