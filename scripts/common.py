# -*- coding: utf-8 -*-
"""往診DB共通ユーティリティ。

日付パース・氏名正規化・保険区分判定・パス解決を提供する。
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

# プロジェクトルート（scripts/ の親）
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
DB_PATH = ROOT / "db" / "oushin.sqlite"
SCHEDULE_DB_PATH = ROOT / "db" / "schedule.sqlite"
VISIT_RECORDS_DB_PATH = ROOT / "db" / "visit_records.sqlite"
VISIT_RECORDS_JSON_PATH = ROOT / "records" / "data" / "confirmed_visits.json"
VISIT_RECORDS_SCHEMA_PATH = ROOT / "scripts" / "schema_visit_records.sql"
EXPORTS_DIR = ROOT / "exports"
SCHEMA_PATH = ROOT / "scripts" / "schema.sql"
SCHEDULE_SCHEMA_PATH = ROOT / "scripts" / "schema_schedule.sql"
DEFAULT_SCHEDULE_PERIOD = "2026-08"

# 医療期限（日数）— docs/decisions.md 判断3-A
IRYO_DEADLINE_DAYS = 30


def find_raw(substr: str) -> Path:
    """raw/ 内でファイル名に substr を含む CSV/テキストを返す。"""
    for p in RAW_DIR.iterdir():
        if substr in p.name:
            return p
    raise FileNotFoundError(f"raw/ に '{substr}' を含むファイルがありません")


def norm_name(s: str | None) -> str:
    """氏名の突合用正規化（空白除去）。"""
    if not s:
        return ""
    s = s.replace("\u3000", " ").replace("　", " ")
    s = re.sub(r"[②③④⑤2]$", "", s.strip())
    return re.sub(r"\s+", "", s)


def display_name(s: str | None) -> str:
    """表示用に全角スペースを半角へ。"""
    if not s:
        return ""
    return s.replace("\u3000", " ").replace("　", " ").strip()


DUAL_ADDRESS_HOME_MARKER = "【自宅】"


def _facility_name_from_prefix(facility_part: str) -> str:
    """【往診：やはら翔裕園】や【ミモザ】などの施設名を抽出。"""
    m = re.search(r"【([^】]+)】", facility_part)
    if not m:
        return ""
    inner = m.group(1).strip()
    if "：" in inner or ":" in inner:
        inner = re.split(r"[：:]", inner, 1)[-1].strip()
    return inner


def parse_dual_ledger_address(address: str) -> tuple[str, str] | None:
    """台帳の施設＋【自宅】併記を (月曜側, 土曜側) に分解。"""
    text = (address or "").replace("\n", " ").strip()
    if DUAL_ADDRESS_HOME_MARKER not in text:
        return None
    facility_part, home_part = text.split(DUAL_ADDRESS_HOME_MARKER, 1)
    facility_part = facility_part.strip()
    home_part = home_part.strip()
    m = re.search(r"】\s*(.+)$", facility_part)
    mon_addr = m.group(1).strip() if m else facility_part
    facility_name = _facility_name_from_prefix(facility_part)
    if facility_name and facility_name not in mon_addr:
        mon_addr = f"{facility_name} {mon_addr}"
    return mon_addr, home_part


def format_dual_visit_address(address: str) -> str:
    """併記住所を【月】【土】見出し付きで両方表示。単一住所はそのまま。"""
    parsed = parse_dual_ledger_address(address)
    if not parsed:
        return (address or "").replace("\n", " ").strip()
    mon_addr, sat_addr = parsed
    return f"【月】{mon_addr} 【土】{sat_addr}"


def _short_location_label(addr: str) -> str:
    text = re.sub(r"\s+", "", addr)
    m = re.search(
        r"(?:東京都|埼玉県)?(?:練馬区|杉並区|西東京市|和光市|三鷹市|武蔵野市)?"
        r"([一-龥ぁ-んァ-ン々\-ー・]+?(?:町|台|原|雀)?)"
        r"(\d+)",
        text,
    )
    if not m:
        return ""
    town = re.sub(
        r"^(?:練馬区|杉並区|西東京市|和光市|三鷹市|武蔵野市)",
        "",
        m.group(1),
    )
    return f"{town}{m.group(2)}"


def dual_visit_location_hint(address: str) -> str:
    """特記用: 月曜なら○○、土曜日なら△△（施設名は含めず町丁目のみ）。"""
    text = (address or "").replace("\n", " ").strip()
    if DUAL_ADDRESS_HOME_MARKER not in text:
        return ""
    facility_part, home_part = text.split(DUAL_ADDRESS_HOME_MARKER, 1)
    facility_part = facility_part.strip()
    home_part = home_part.strip()
    m = re.search(r"】\s*(.+)$", facility_part)
    mon_street = m.group(1).strip() if m else facility_part
    mon_short = _short_location_label(mon_street)
    sat_short = _short_location_label(home_part)
    if not mon_short or not sat_short:
        return ""
    return f"月曜なら{mon_short}、土曜日なら{sat_short}"


def address_for_visit_day(address: str, dow: str) -> str:
    """表示用併記 or 台帳生データから、その日の往診先住所を1件に絞る（メール・短縮用）。"""
    text = (address or "").replace("\n", " ").strip()
    if "【月】" in text and "【土】" in text:
        if dow == "月":
            m = re.search(r"【月】([^【]+)", text)
            return m.group(1).strip() if m else text
        if dow == "土":
            m = re.search(r"【土】(.+)$", text)
            return m.group(1).strip() if m else text
        return text
    parsed = parse_dual_ledger_address(text)
    if not parsed:
        return text
    if dow == "月":
        return parsed[0]
    if dow == "土":
        return parsed[1]
    return text


def resolve_visit_address(address: str, dow: str) -> str:
    """後方互換: その日の往診先1件のみ。"""
    return address_for_visit_day(address, dow)


def classify_insurance(kaigodo: str | None) -> tuple[str, str | None]:
    """介護度から (insurance_type, care_level) を返す。"""
    k = (kaigodo or "").strip()
    if k == "医療":
        return "iryo", None
    if k == "自費":
        return "jihi", None
    if not k:
        return "unknown", None
    return "kaigo", k


def normalize_chart_id(chart_id: str | None) -> tuple[str | None, str | None]:
    """台帳ID b75 → (patient_id=b075, chart_id=b75)。"""
    if not chart_id:
        return None, None
    cid = chart_id.strip()
    if not cid:
        return None, None
    if cid.startswith("b") and cid[1:].isdigit():
        num = int(cid[1:])
        return f"b{num:03d}", cid
    if cid.isdigit():
        num = int(cid)
        return f"b{num:03d}", f"b{num}"
    return cid, cid


def visit_code_from_chart(chart_id: str | None) -> str | None:
    """b75 → 000075。"""
    if not chart_id:
        return None
    cid = chart_id.strip()
    if cid.startswith("b") and cid[1:].isdigit():
        return f"{int(cid[1:]):06d}"
    if cid.isdigit():
        return f"{int(cid):06d}"
    return None


def patient_id_from_visit_code(visit_code: str | None) -> str | None:
    """000075 → b075。"""
    if not visit_code:
        return None
    vc = visit_code.strip()
    if not vc.isdigit():
        return None
    return f"b{int(vc):03d}"


def extract_notion_id(text: str | None) -> str | None:
    """Notion URL または UUID からページIDを抽出。"""
    if not text:
        return None
    m = re.search(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        text,
        re.I,
    )
    if m:
        return m.group(1).lower()
    m = re.search(r"/p/([0-9a-f]{32})", text, re.I)
    if m:
        raw = m.group(1).lower()
        return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return None


def parse_date(s: str | None, hint_date: date | None = None) -> date | None:
    """多様な日付表記を date に変換する。"""
    if not s:
        return None
    s0 = str(s).split("→")[0].strip()
    for pat in (
        r"(\d{4})年(\d{1,2})月(\d{1,2})日",
        r"(\d{4})/(\d{1,2})/(\d{1,2})",
        r"(\d{4})-(\d{1,2})-(\d{1,2})",
    ):
        m = re.search(pat, s0)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    m = re.search(r"(\d{1,2})/(\d{1,2})", s0)
    if not m:
        return None
    mo, day = int(m.group(1)), int(m.group(2))
    year = hint_date.year if hint_date else date.today().year
    try:
        cand = date(year, mo, day)
    except ValueError:
        return None
    if hint_date and cand < hint_date - timedelta(days=200):
        try:
            cand = date(year + 1, mo, day)
        except ValueError:
            return None
    return cand


def to_iso(d: date | None) -> str | None:
    """date を YYYY-MM-DD 文字列へ。"""
    return d.isoformat() if d else None


def add_months(d: date, months: int) -> date:
    """カレンダー月を加算する。"""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def month_end(d: date) -> date:
    """その月の末日。"""
    return date(d.year, d.month, monthrange(d.year, d.month)[1])


def deadline_for(last_date: date, insurance_type: str) -> date:
    """区分別の期限日を算出する。"""
    if insurance_type == "iryo":
        return last_date + timedelta(days=IRYO_DEADLINE_DAYS)
    # kaigo / jihi / unknown → 2ヶ月後月末
    return month_end(add_months(last_date, 2))


def insurance_label_ja(insurance_type: str) -> str:
    """表示用日本語ラベル。"""
    return {
        "kaigo": "介護",
        "iryo": "医療",
        "jihi": "自費",
        "unknown": "不明",
    }.get(insurance_type, insurance_type)


def map_ledger_status(raw: str | None) -> str:
    """台帳の状態 → patients.status。"""
    s = (raw or "").strip()
    if s == "終了":
        return "ended"
    if s == "予定":
        return "scheduled"
    return "active"
