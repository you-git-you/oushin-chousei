# -*- coding: utf-8 -*-
"""実施済み往診の最終日を複数ソースから統合する。"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from common import VISIT_RECORDS_DB_PATH, find_raw, normalize_chart_id, parse_date

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class LastVisit:
    date: str  # ISO YYYY-MM-DD
    source: str


def _iso_from_ja(s: str | None) -> str | None:
    d = parse_date(s)
    return d.isoformat() if d else None


def _ledger_to_pid(visit_code: str | None) -> str | None:
    code = (visit_code or "").strip()
    if not code.isdigit():
        return None
    return f"b{int(code):03d}"


def _max_date(dates: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for pid, d in dates.items():
        if pid not in out or d > out[pid]:
            out[pid] = d
    return out


class LastVisitIndex:
    """患者ごとの最終実施往診日。
    2026年7月の実施日は **confirmed_visits（下表47名）のみ** 7月実施として採用。
    それ以外の7月行（履歴の「予定」等）は最終往診日に使わない。
    """

    def __init__(self) -> None:
        self._by_pid: dict[str, LastVisit] = {}

    @classmethod
    def build(
        cls,
        confirmed_dates: dict[str, str] | None = None,
    ) -> LastVisitIndex:
        idx = cls()
        confirmed = dict(confirmed_dates or {})
        july_confirmed = {
            pid for pid, d in confirmed.items() if d.startswith("2026-07")
        }
        rireki_by_pid, rireki_by_day = idx._load_rireki_performed(july_confirmed)
        rireki = _max_date(rireki_by_pid)
        yoyaku = _max_date(
            idx._load_yoyaku_completed_home_visits(rireki_by_day, july_confirmed)
        )

        all_pids = set(confirmed) | set(rireki) | set(yoyaku)
        for pid in all_pids:
            if pid in confirmed:
                idx._by_pid[pid] = LastVisit(confirmed[pid], "7月確定実施")
                continue
            parts: list[tuple[str, str]] = []
            if pid in rireki:
                parts.append((rireki[pid], "往診履歴(キャンセル以外)"))
            if pid in yoyaku:
                parts.append((yoyaku[pid], "予約CSV(往診)"))
            if not parts:
                continue
            best_date = max(p[0] for p in parts)
            source_order = (
                "往診履歴(キャンセル以外)",
                "予約CSV(往診)",
            )
            best_source = next(
                s for s in source_order if any(d == best_date and src == s for d, src in parts)
            )
            idx._by_pid[pid] = LastVisit(best_date, best_source)
        return idx

    def get(self, patient_id: str) -> LastVisit | None:
        return self._by_pid.get(patient_id)

    def last_performed_date(self, patient_id: str) -> str | None:
        lv = self.get(patient_id)
        return lv.date if lv else None

    def _load_rireki_performed(
        self, july_confirmed: set[str]
    ) -> tuple[dict[str, str], set[tuple[str, str]]]:
        """患者ごと最新日付と、(patient_id, 日付) の実施扱いセット。"""
        path = find_raw("往診履歴")
        by_pid: dict[str, str] = {}
        by_day: set[tuple[str, str]] = set()
        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                status = (r.get("ステータス") or "").strip()
                if status == "キャンセル" or not status:
                    continue
                iso = _iso_from_ja(r.get("往診日時"))
                pid = _ledger_to_pid(r.get("患者ID"))
                if not pid or not iso:
                    continue
                if iso.startswith("2026-07") and pid not in july_confirmed:
                    continue
                by_day.add((pid, iso))
                if pid not in by_pid or iso > by_pid[pid]:
                    by_pid[pid] = iso
        return by_pid, by_day

    def _load_yoyaku_completed_home_visits(
        self,
        rireki_by_day: set[tuple[str, str]],
        july_confirmed: set[str],
    ) -> dict[str, str]:
        path = find_raw("往診予約")
        out: dict[str, str] = {}
        with path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("s_type") or "").strip() != "往診":
                    continue
                pid, _ = normalize_chart_id((r.get("台帳ID") or "").strip())
                iso = _iso_from_ja(r.get("s_date"))
                if not pid or not iso:
                    continue
                done = (r.get("s_done") or "").strip()
                if done and done != "0":
                    counted = True
                else:
                    counted = (pid, iso) in rireki_by_day
                if not counted:
                    continue
                if iso.startswith("2026-07") and pid not in july_confirmed:
                    continue
                if pid not in out or iso > out[pid]:
                    out[pid] = iso
        return out


def load_confirmed_dates_from_visit_db() -> dict[str, str]:
    """visit_records の確定実施日（患者ごと最新）。"""
    if not VISIT_RECORDS_DB_PATH.is_file():
        return {}
    conn = sqlite3.connect(VISIT_RECORDS_DB_PATH)
    try:
        out: dict[str, str] = {}
        for pid, d in conn.execute(
            """
            SELECT cv.patient_id, cs.performed_date
            FROM confirmed_visits cv
            JOIN confirmed_sessions cs ON cs.session_id = cv.session_id
            WHERE cv.status = 'completed' AND cv.patient_id IS NOT NULL
            """
        ):
            if pid and (pid not in out or d > out[pid]):
                out[pid] = d
        return out
    finally:
        conn.close()
