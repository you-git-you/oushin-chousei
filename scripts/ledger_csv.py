# -*- coding: utf-8 -*-
"""最新の編集用台帳 CSV を読み、患者マスタを更新する。"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from common import (
    DB_PATH,
    ROOT,
    classify_insurance,
    display_name,
    map_ledger_status,
    normalize_chart_id,
    parse_date,
    to_iso,
)

LEDGER_GLOB = [
    ROOT / "★台帳（訪問）★ 編集用 - 編集用（介護） (6).csv",
    ROOT / "★台帳（訪問）★ 編集用 - 編集用（介護） (4).csv",
    ROOT / "20260808台帳（訪問）★ 編集用 - 編集用（介護） (3).csv",
    ROOT,
    ROOT / "raw",
]


def find_latest_ledger_csv() -> Path | None:
    candidates: list[Path] = []
    seen: set[Path] = set()
    for p in LEDGER_GLOB:
        if p.is_file() and "台帳" in p.name and p.suffix.lower() == ".csv":
            if p not in seen:
                candidates.append(p)
                seen.add(p)
        if p.is_dir():
            for f in p.iterdir():
                if f.suffix.lower() == ".csv" and "台帳" in f.name and f not in seen:
                    candidates.append(f)
                    seen.add(f)
    if not candidates:
        return None
    return max(candidates, key=lambda x: x.stat().st_mtime)


def _normalize_ledger_row(raw: dict[str, str]) -> dict[str, str] | None:
    """Notion エクスポートの列名ゆれを吸収する。"""
    if raw.get("ID"):
        return raw
    keys = list(raw.keys())
    if len(keys) < 4:
        return None
    return {
        "更新日時": (raw.get(keys[0]) or "").strip(),
        "状態": (raw.get(keys[1]) or "").strip(),
        "ID": (raw.get("ID") or raw.get(keys[2]) or "").strip(),
        "氏名": (raw.get("氏名") or raw.get(keys[3]) or "").strip(),
        "ふりがな": (raw.get("ふりがな") or raw.get(keys[4]) or "").strip(),
        "性別": raw.get("性別", ""),
        "生年月日": raw.get("生年月日", ""),
        "介護度": raw.get("介護度", ""),
        "開始日": raw.get("開始日", ""),
        "終了日": raw.get("終了日", ""),
        "理由": raw.get("理由", ""),
        "利用者TEL": raw.get("利用者TEL", ""),
        "利用者住所": raw.get("利用者住所", ""),
        "利用者郵便": raw.get("利用者郵便", ""),
        "メイン担当": raw.get("メイン担当", ""),
        "主治医": raw.get("主治医", ""),
        "ケアマネ": raw.get("ケアマネ", ""),
        "居宅名": raw.get("居宅名", ""),
        "病院名": raw.get("病院名", ""),
    }


def load_ledger_index() -> dict[str, dict[str, str]]:
    """patient_id -> {name_kana, status, name, insurance_type}"""
    path = find_latest_ledger_csv()
    if not path:
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        out: dict[str, dict[str, str]] = {}
        for raw in reader:
            r = _normalize_ledger_row(raw)
            if not r:
                continue
            pid, _ = normalize_chart_id((r.get("ID") or "").strip())
            if not pid:
                continue
            ins, _ = classify_insurance(r.get("介護度"))
            out[pid] = {
                "patient_id": pid,
                "name": display_name(r.get("氏名")),
                "name_kana": display_name(r.get("ふりがな")) or "",
                "ledger_status": map_ledger_status(r.get("状態")),
                "insurance_type": ins,
                "ledger_reason": (r.get("理由") or "").strip(),
            }
        return out


def sync_patients_from_ledger(conn: sqlite3.Connection | None = None) -> Path | None:
    """台帳 CSV のふりがな・状態を patients に反映（UPSERT）。"""
    path = find_latest_ledger_csv()
    if not path:
        return None
    own = conn is None
    if own:
        conn = sqlite3.connect(DB_PATH)
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                r = _normalize_ledger_row(raw)
                if not r:
                    continue
                pid, chart_id = normalize_chart_id((r.get("ID") or "").strip())
                if not pid:
                    continue
                insurance_type, care_level = classify_insurance(r.get("介護度"))
                status = map_ledger_status(r.get("状態"))
                name = display_name(r.get("氏名"))
                kana = display_name(r.get("ふりがな"))
                exists = conn.execute(
                    "SELECT 1 FROM patients WHERE patient_id = ?", (pid,)
                ).fetchone()
                if exists:
                    conn.execute(
                        """
                        UPDATE patients SET
                            name = COALESCE(?, name),
                            name_kana = COALESCE(NULLIF(?, ''), name_kana),
                            status = ?,
                            insurance_type = ?,
                            care_level = ?,
                            main_staff = COALESCE(NULLIF(?, ''), main_staff),
                            updated_at = COALESCE(?, updated_at)
                        WHERE patient_id = ?
                        """,
                        (
                            name,
                            kana,
                            status,
                            insurance_type,
                            care_level,
                            (r.get("メイン担当") or "").strip(),
                            to_iso(parse_date(r.get("更新日時"))),
                            pid,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO patients (
                            patient_id, chart_id, name, name_kana,
                            insurance_type, care_level, status, main_staff, matched
                        ) VALUES (?,?,?,?,?,?,?,?,1)
                        """,
                        (pid, chart_id, name, kana, insurance_type, care_level, status,
                         (r.get("メイン担当") or "").strip()),
                    )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()
    return path
