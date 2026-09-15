# -*- coding: utf-8 -*-
"""10月往診対象一覧を exports/ に TSV / CSV で出力する（スプレッドシート貼付用）。

方針:
  - 基本: 8月往診リストの非キャンセルを 8月実施とみなす
    （visit_records / Notion CSV 履歴は 2026-07 までで、8月確定は records に未取込）
  - 加えて: 期限が 2026-10 に入る人、履歴・明示の 10月移動
  - 確定実施は Notion CSV より records/visit_records を優先
  - 医療=最終実施の30日後 / 介護・自費=2ヶ月後月末
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from august_schedule_data import AUG_MD, load_august_schedule_from_md
from clinic_visits import load_clinic_managed_patient_ids
from common import (
    DB_PATH,
    EXPORTS_DIR,
    ROOT,
    deadline_for,
    format_dual_visit_address,
    insurance_label_ja,
    normalize_chart_id,
)
from last_visit import LastVisitIndex, load_confirmed_dates_from_visit_db
from ledger_csv import find_latest_ledger_csv, load_ledger_index, sync_patients_from_ledger
from visit_cautions import DAY_VISIT_CAUTIONS

PAUSE_JSON = ROOT / "records" / "data" / "pause_resume_status.json"
OUT_TSV = EXPORTS_DIR / "10月往診対象一覧.tsv"
OUT_CSV = EXPORTS_DIR / "10月往診対象一覧.csv"

TARGET_YEAR = 2026
TARGET_MONTH = 10
OCT_START = date(TARGET_YEAR, TARGET_MONTH, 1)
OCT_END = date(TARGET_YEAR, TARGET_MONTH, 31)

INS_JA_TO_CODE = {"医療": "iryo", "介護": "kaigo", "自費": "jihi", "不明": "unknown"}
INS_CODE_ORDER = {"iryo": 0, "kaigo": 1, "jihi": 2, "unknown": 3}

# 9月リストと同じ除外（ご逝去・終了・入院など）。正規化ID。
EXCLUDED_IDS = {
    "b428",
    "b297",
    "b450",
    "b467",
    "b418",
    "b478",
    "b264",
    "b242",
    "b442",
    "b011",
    "b447",
    "b496",
    "b439",
    "b267",
    "b339",
    "b476",
    "b460",
}

# 8月・9月ともキャンセルで 10 月初旬へ
HISTORY_ADDS = {
    "b492": "履歴から追加（9月キャンセル→10月初旬）",
}

DOCTOR_NG_NOTE = {
    "b484": "片山NG（花輪または鳥越）",
    "b357": "鳥越NG（花輪）",
    "b138": "花輪・片山NG（鳥越のみ。土曜14時以降）",
}

COLUMNS = [
    "patient_id",
    "氏名",
    "フリガナ",
    "区分",
    "状態",
    "最終往診日",
    "8月実施日",
    "期限",
    "含めた理由",
    "住所",
    "担当医師",
    "メイン担当",
    "注意",
    "備考",
]


def norm_pid(raw: str | None) -> str | None:
    pid, _ = normalize_chart_id((raw or "").strip())
    return pid


def kana_sort_key(kana: str, name: str) -> str:
    base = (kana or "").replace(" ", "").replace("　", "")
    if base:
        return base
    return name or ""


def load_caution_by_pid() -> dict[str, str]:
    out: dict[str, str] = {}
    for items in DAY_VISIT_CAUTIONS.values():
        for item in items:
            pid = norm_pid(item.get("id"))
            if not pid:
                continue
            body = (item.get("body") or item.get("title") or "").strip()
            if not body:
                continue
            if pid in out and body not in out[pid]:
                out[pid] = f"{out[pid]}／{body}"
            else:
                out[pid] = body
    return out


def load_ledger_details() -> dict[str, dict[str, str]]:
    """台帳から住所・主治医・担当を読む。"""
    path = find_latest_ledger_csv()
    if not path:
        return {}
    out: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            pid = norm_pid(raw.get("ID"))
            if not pid:
                continue
            addr = (raw.get("利用者住所") or "").replace("\n", " ").strip()
            out[pid] = {
                "address": addr,
                "primary_doctor": (raw.get("主治医") or "").strip(),
                "main_staff": (raw.get("メイン担当") or "").strip(),
                "name": (raw.get("氏名") or "").replace(" ", "").replace("　", ""),
                "name_kana": (raw.get("ふりがな") or "").strip(),
            }
    return out


def load_august_visits_from_md() -> dict[str, dict]:
    """8月リストのルート表から実施（非キャンセル）と最終医師・区分・住所を取る。"""
    text = AUG_MD.read_text(encoding="utf-8")
    current_iso: str | None = None
    current_doctor = ""
    by_pid: dict[str, dict] = {}
    in_schedule_day = False

    for line in text.splitlines():
        day_m = re.match(r"^## 8/(\d+)\(", line)
        if day_m:
            current_iso = f"2026-08-{int(day_m.group(1)):02d}"
            in_schedule_day = True
            current_doctor = ""
            continue
        if line.startswith("## ") and not day_m:
            in_schedule_day = False
            current_iso = None
            current_doctor = ""
            continue
        doc_m = re.match(r"^### (花輪|片山|鳥越)", line)
        if doc_m and in_schedule_day:
            current_doctor = doc_m.group(1)
            continue
        if not in_schedule_day or not current_iso or "|" not in line:
            continue
        if line.strip().startswith("|---"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if len(cells) < 8 or not cells[0].isdigit():
            continue
        pid_raw = None
        name = ""
        ins_ja = ""
        md_addr = ""
        for i, c in enumerate(cells):
            if not re.fullmatch(r"b\d+", c):
                continue
            pid_raw = c
            if i > 0:
                prev = cells[i - 1]
                if prev and not re.fullmatch(r"b\d+", prev) and not prev.isdigit():
                    name = prev.replace(" ", "").replace("　", "")
            if i + 1 < len(cells) and cells[i + 1] in INS_JA_TO_CODE:
                ins_ja = cells[i + 1]
            if i + 3 < len(cells):
                md_addr = cells[i + 3].replace("\n", " ").strip()
            break
        pid = norm_pid(pid_raw)
        if not pid:
            continue
        eta = cells[7] if len(cells) > 7 else ""
        if eta.strip() == "キャンセル":
            continue
        entry = by_pid.setdefault(
            pid,
            {
                "patient_id": pid,
                "name": name,
                "insurance_ja": ins_ja,
                "address": md_addr,
                "august_dates": [],
                "doctors_by_date": {},
            },
        )
        if name and not entry["name"]:
            entry["name"] = name
        if ins_ja and not entry["insurance_ja"]:
            entry["insurance_ja"] = ins_ja
        if md_addr and not entry["address"]:
            entry["address"] = md_addr
        if current_iso not in entry["august_dates"]:
            entry["august_dates"].append(current_iso)
        if current_doctor:
            entry["doctors_by_date"][current_iso] = current_doctor

    for entry in by_pid.values():
        entry["august_dates"].sort()
        last_d = entry["august_dates"][-1] if entry["august_dates"] else None
        entry["last_planned"] = last_d
        entry["last_doctor"] = (
            entry["doctors_by_date"].get(last_d, "") if last_d else ""
        )
    return by_pid


def operational_status(
    pid: str,
    pause: dict[str, dict],
    pinfo: sqlite3.Row | None,
    ledger_index: dict[str, dict],
) -> str:
    pr = pause.get(pid)
    if pr and pr.get("current_status") == "paused":
        return "休止"
    if pr and pr.get("current_status") == "ended":
        return "終了"
    if pinfo:
        if pinfo["status"] == "paused":
            return "休止"
        if pinfo["status"] == "ended":
            return "終了"
    led = ledger_index.get(pid)
    if led:
        if led.get("ledger_status") == "paused":
            return "休止"
        if led.get("ledger_status") == "ended":
            return "終了"
    return ""


def main() -> None:
    ledger_path = sync_patients_from_ledger()
    ledger_index = load_ledger_index()
    ledger_details = load_ledger_details()
    pause = {
        r["patient_id"]: r
        for r in json.loads(PAUSE_JSON.read_text(encoding="utf-8"))["records"]
        if r.get("patient_id")
    }
    clinic_managed = load_clinic_managed_patient_ids()
    cautions = load_caution_by_pid()
    aug_from_simple = {
        norm_pid(pid) or pid: p for pid, p in load_august_schedule_from_md().items()
    }
    aug_visits = load_august_visits_from_md()
    for pid, p in aug_from_simple.items():
        if pid not in aug_visits:
            aug_visits[pid] = {
                "patient_id": pid,
                "name": (p.get("name") or "").replace(" ", ""),
                "insurance_ja": "",
                "address": "",
                "august_dates": list(p.get("august_dates") or []),
                "last_planned": p.get("last_planned"),
                "last_doctor": "",
                "doctors_by_date": {},
            }

    last_visit_index = LastVisitIndex.build(
        confirmed_dates=load_confirmed_dates_from_visit_db()
    )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    def pinfo(pid: str) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT name, name_kana, insurance_type, main_staff, status, address
            FROM patients WHERE patient_id = ?
            """,
            (pid,),
        ).fetchone()

    def insurance_code(pid: str, aug: dict | None) -> str:
        p = pinfo(pid)
        if p and p["insurance_type"] and p["insurance_type"] != "unknown":
            return p["insurance_type"]
        if aug and aug.get("insurance_ja"):
            return INS_JA_TO_CODE.get(aug["insurance_ja"], "unknown")
        led = ledger_index.get(pid)
        if led and led.get("insurance_type"):
            return led["insurance_type"]
        return "unknown"

    def last_performed(pid: str, aug: dict | None) -> tuple[str | None, str]:
        """(ISO日付, ソース)。records/visit_records を CSV より優先し、8月リスト日付も採用。"""
        candidates: list[tuple[str, str]] = []
        lv = last_visit_index.get(pid)
        if lv:
            candidates.append((lv.date, lv.source))
        if aug and aug.get("last_planned"):
            candidates.append((aug["last_planned"], "8月往診リスト"))
        if not candidates:
            return None, ""
        best_date = max(c[0] for c in candidates)
        source_order = (
            "7月確定実施",
            "8月往診リスト",
            "往診履歴(キャンセル以外)",
            "予約CSV(往診)",
        )
        for src_name in source_order:
            if any(d == best_date and src == src_name for d, src in candidates):
                return best_date, src_name
        return best_date, candidates[0][1]

    candidates: set[str] = set()
    for pid in aug_visits:
        np = norm_pid(pid)
        if np:
            candidates.add(np)
    for pid in last_visit_index._by_pid:
        np = norm_pid(pid)
        if np:
            candidates.add(np)
    candidates.update(HISTORY_ADDS)

    rows: list[dict[str, str]] = []
    skipped = {"ended": 0, "paused": 0, "excluded": 0, "clinic": 0, "no_need": 0}

    for pid in candidates:
        if pid in EXCLUDED_IDS:
            skipped["excluded"] += 1
            continue
        aug = aug_visits.get(pid)
        on_august = bool(aug and aug.get("august_dates"))
        last, last_src = last_performed(pid, aug)
        ins = insurance_code(pid, aug)
        deadline = ""
        deadline_d: date | None = None
        if last:
            deadline_d = deadline_for(date.fromisoformat(last), ins)
            deadline = deadline_d.isoformat()
        in_october = bool(deadline_d and OCT_START <= deadline_d <= OCT_END)
        history_add = pid in HISTORY_ADDS
        include = on_august or in_october or history_add
        if not include:
            skipped["no_need"] += 1
            continue
        if pid in clinic_managed and not on_august and not history_add:
            skipped["clinic"] += 1
            continue

        p = pinfo(pid)
        st = operational_status(pid, pause, p, ledger_index)
        if st == "終了":
            skipped["ended"] += 1
            continue
        if st == "休止" and not history_add:
            skipped["paused"] += 1
            continue

        if on_august:
            reason = "8月実施"
            if in_october:
                reason = "8月実施（期限到来）"
        elif history_add:
            reason = HISTORY_ADDS[pid]
        elif in_october:
            reason = "期限到来"
        else:
            reason = "履歴から追加"

        led = ledger_details.get(pid, {})
        name = (
            (aug.get("name") if aug else "")
            or (p["name"] if p else "")
            or led.get("name")
            or pid
        ).replace(" ", "").replace("　", "")
        kana = ""
        if p and p["name_kana"]:
            kana = p["name_kana"]
        elif ledger_index.get(pid, {}).get("name_kana"):
            kana = ledger_index[pid]["name_kana"]
        elif led.get("name_kana"):
            kana = led["name_kana"]

        addr = (led.get("address") or "").strip()
        if not addr and aug:
            addr = (aug.get("address") or "").strip()
        if not addr and p and p["address"]:
            addr = p["address"]
        addr = format_dual_visit_address(addr) if addr else ""

        doctor = ""
        if aug and aug.get("last_doctor"):
            doctor = aug["last_doctor"]
        elif led.get("primary_doctor"):
            doctor = led["primary_doctor"]

        main_staff = ""
        if p and p["main_staff"]:
            main_staff = p["main_staff"]
        elif led.get("main_staff"):
            main_staff = led["main_staff"]

        notes: list[str] = []
        ng = DOCTOR_NG_NOTE.get(pid)
        if ng:
            notes.append(ng)
        if pid in cautions:
            notes.append(cautions[pid])
        caution = "／".join(notes)

        aug_dates = "、".join(aug["august_dates"]) if aug and aug.get("august_dates") else ""
        extra = []
        if last_src:
            extra.append(f"最終根拠:{last_src}")
        if st:
            extra.append(st)
        note = "／".join(extra)

        rows.append(
            {
                "patient_id": pid,
                "氏名": name,
                "フリガナ": (kana or "").strip(),
                "区分": insurance_label_ja(ins),
                "状態": st,
                "最終往診日": last or "",
                "8月実施日": aug_dates,
                "期限": deadline or "要確認",
                "含めた理由": reason,
                "住所": addr,
                "担当医師": doctor,
                "メイン担当": main_staff,
                "注意": caution,
                "備考": note,
            }
        )

    conn.close()

    def sort_key(r: dict[str, str]) -> tuple:
        ins_code = INS_JA_TO_CODE.get(r["区分"], "unknown")
        return (
            INS_CODE_ORDER.get(ins_code, 9),
            kana_sort_key(r["フリガナ"], r["氏名"]),
            r["氏名"],
        )

    rows.sort(key=sort_key)

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_TSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    n_aug = sum(1 for r in rows if r["含めた理由"].startswith("8月実施"))
    n_hist = len(rows) - n_aug
    n_deadline = sum(1 for r in rows if "期限到来" in r["含めた理由"])
    by_ins: dict[str, int] = {}
    for r in rows:
        by_ins[r["区分"]] = by_ins.get(r["区分"], 0) + 1

    print(f"Wrote {OUT_TSV}")
    print(f"Wrote {OUT_CSV}")
    print(f"total={len(rows)}")
    print(f"from_august={n_aug}")
    print(f"from_history={n_hist}")
    print(f"deadline_in_reason={n_deadline}")
    print("by_insurance:", by_ins)
    print("skipped:", skipped)
    if ledger_path:
        print(f"ledger: {ledger_path.name}")


if __name__ == "__main__":
    main()
