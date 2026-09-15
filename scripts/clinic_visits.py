# -*- coding: utf-8 -*-
"""通院（クリニック受診）の最終日を取得する。"""

from __future__ import annotations

import csv
import json
from datetime import date

from common import ROOT, find_raw, normalize_chart_id, parse_date

CLINIC_AS_PERFORMED_JSON = (
    ROOT / "records" / "data" / "clinic_visits_as_performed.json"
)


def _merge_last(out: dict[str, str], pid: str, iso: str) -> None:
    if pid not in out or iso > out[pid]:
        out[pid] = iso


def load_clinic_visits_as_performed() -> list[dict]:
    """スタッフチャット等で実施扱いにした通院一覧。"""
    if not CLINIC_AS_PERFORMED_JSON.is_file():
        return []
    data = json.loads(CLINIC_AS_PERFORMED_JSON.read_text(encoding="utf-8"))
    visits = data.get("visits")
    if not isinstance(visits, list):
        return []
    return [v for v in visits if isinstance(v, dict)]


CLINIC_PRIMARY_JSON = ROOT / "records" / "data" / "clinic_primary_visits.json"


def load_clinic_managed_patient_ids() -> set[str]:
    """9月通院一覧などに載せる patient_id（primary JSON ＋ 実施扱いJSON）。"""
    pids: set[str] = set()
    if CLINIC_PRIMARY_JSON.is_file():
        data = json.loads(CLINIC_PRIMARY_JSON.read_text(encoding="utf-8"))
        for p in data.get("patients", []):
            if isinstance(p, dict):
                pid = (p.get("patient_id") or "").strip()
                if pid:
                    pids.add(pid)
    for v in load_clinic_visits_as_performed():
        pid = (v.get("patient_id") or "").strip()
        if pid:
            pids.add(pid)
    return pids


def load_last_clinic_visit_dates() -> dict[str, str]:
    """patient_id -> ISO date（通院の最新実施扱い日）。"""
    path = find_raw("往診予約")
    out: dict[str, str] = {}
    today = date.today()
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("s_type") or "").strip() != "通院":
                continue
            pid, _ = normalize_chart_id((r.get("台帳ID") or "").strip())
            d = parse_date(r.get("s_date"))
            if not pid or not d:
                continue
            if d > today:
                continue
            _merge_last(out, pid, d.isoformat())

    for v in load_clinic_visits_as_performed():
        pid = (v.get("patient_id") or "").strip()
        raw = (v.get("visit_date") or "").strip()
        if not pid or not raw:
            continue
        d = parse_date(raw)
        if not d or d > today:
            continue
        _merge_last(out, pid, d.isoformat())

    return out
