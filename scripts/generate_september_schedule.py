# -*- coding: utf-8 -*-
"""9月往診リストを均等配置・ルート最適化付きで生成する。"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common import display_name, dual_visit_location_hint, format_dual_visit_address
from ledger_csv import find_latest_ledger_csv

ROOT = SCRIPTS.parent
HOPE_CSV = ROOT / '🚙🚕🚗往診周り順👴🏻👴👴🏼suzuki - 9月往診日・希望.csv'
LEDGER_CSV = find_latest_ledger_csv() or (
    ROOT / "★台帳（訪問）★ 編集用 - 編集用（介護） (6).csv"
)
HISTORY_CSV = ROOT / "raw/3 往診履歴 7ab6c23709254f879aab52376aa63f2d_all.csv"
OUTPUT_MD = ROOT / "exports/9月往診リスト_2026.md"
OVERRIDES_PATH = ROOT / "exports/september_schedule_overrides.json"
CONSTRAINTS_PATH = ROOT / "exports/september_patient_constraints.json"
PERIOD_KEY = "2026-09"

EXCLUDED_IDS = {
    "b297", "b450", "b467", "b418", "b478", "b264", "b242", "b442",
    "b11",
    "b447",
    "b496",  # 岡村昭一：8/14ご逝去
    "b439",  # 三井正勝：終了
    "b267",  # 大和八重子：ご逝去
    "b339",  # 本橋明子：休止・枠解除
    "b476",  # 杉原博子：入院
    "b460",  # 土屋洸子：8/27入院
}

INCLUDE_DESPITE_STATUS = frozenset()

# 月土ルート外だが往診が必要な人（火金の院長休憩など）
OUT_OF_SCOPE_VISIT: dict[str, dict[str, str]] = {
    "b152": {
        "doctor": "花輪",
        "slot": "火・金（院長休憩）候補 9/8・11・15・18",
        "eta": "14:30〜15:00",
        "how": "徒歩",
    },
}

# 台帳に番地が無い／チャットで補った住所
ADDRESS_OVERRIDES: dict[str, str] = {
    "b511": "東京都練馬区高松6-21-24",
    "b381": "東京都練馬区西大泉4-6-12",
    "b271": "東京都練馬区大泉町2-55-1",
    "b514": "練馬区大泉学園町4-8-4",
    "b428": "東京都杉並区井草3-17-13そんぽの家S井荻　503",
}

# 台帳未掲載・表記修正（台帳より優先）
NAME_OVERRIDES: dict[str, str] = {
    "b514": "造酒 侚子",
}

# load_ledger() が氏名も入れる
LEDGER_NAMES: dict[str, str] = {}

DAY_META = {
    "9/5(土)": {"date": date(2026, 9, 5), "dow": "土", "doctors": ["鳥越"]},
    "9/7(月)": {"date": date(2026, 9, 7), "dow": "月", "doctors": ["花輪", "片山"]},
    "9/14(月)": {"date": date(2026, 9, 14), "dow": "月", "doctors": ["花輪"]},
    "9/19(土)": {"date": date(2026, 9, 19), "dow": "土", "doctors": ["鳥越"]},
    "9/26(土)": {"date": date(2026, 9, 26), "dow": "土", "doctors": ["鳥越"]},
    "9/28(月)": {"date": date(2026, 9, 28), "dow": "月", "doctors": ["花輪"]},
}

DAY_ORDER = list(DAY_META.keys())
KATAYAMA_DAYS = frozenset({"9/7(月)"})
HANAWA_DAYS = frozenset(dk for dk, m in DAY_META.items() if "花輪" in m["doctors"])

# 宮嶋は5・7・28確定。9/12は往診中止。9/19は午後のみ（上杉）。
DRIVER_BY_DAY: dict[str, str] = {
    "9/5(土)": "宮嶋",
    "9/7(月)": "宮嶋",
    "9/14(月)": "上杉",
    "9/19(土)": "上杉",
    "9/26(土)": "石橋",
    "9/28(月)": "宮嶋",
}


def driver_for_day(day_key: str) -> str:
    name = DRIVER_BY_DAY.get(day_key)
    if not name:
        return "未定"
    return f"{name}さん"


# 人数制限は今回無視（手動ルートを落とさないための上限）
CAPACITY = {
    ("花輪", "9/7(月)"): 20,
    ("花輪", "9/14(月)"): 20,
    ("花輪", "9/28(月)"): 20,
    ("片山", "9/7(月)"): 20,
    ("鳥越", "9/5(土)"): 20,
    ("鳥越", "9/19(土)"): 20,
    ("鳥越", "9/26(土)"): 20,
}

# クリニック（東大泉）からのエリア優先順（西→東・近→遠の目安）
AREA_CLUSTER_ORDER = {
    "L谷原": 20,
    "谷原": 20,
    "井草3": 30,
    "南田中": 52,
    "S井荻": 35,
    "アリア井草": 40,
    "CW下石": 45,
    "下石": 50,
    "下石神井3": 50,
    "石台1": 55,
    "石台2": 56,
    "石台3": 57,
    "石台7": 57,
    "石台8": 57,
    "石町": 59,
    "石町2": 58,
    "石町3": 59,
    "上石": 60,
    "FH上石神井": 62,
    "高野台": 65,
    "三原台": 68,
    "西1": 69,
    "西2": 71,
    "西3": 70,
    "西5": 72,
    "学1": 75,
    "学2": 76,
    "学3": 77,
    "学4": 78,
    "学5": 79,
    "学6": 80,
    "学8": 81,
    "FH": 82,
    "FH大泉": 82,
    "大町1": 85,
    "大町2": 86,
    "大町3": 87,
    "大町6": 88,
    "下保谷": 84,
    "保谷": 84,
    "大泉町3": 87,
    "S大泉町5": 88,
    "東1": 90,
    "東2": 91,
    "東3": 91,
    "東5": 92,
    "東6": 93,
    "東7": 89,
    "東大泉": 94,
    "土支田": 95,
    "土支田4": 96,
    "関町": 97,
    "和光": 100,
    "新座": 101,
    "西東京泉町": 98,
    "高松": 48,
    "西4": 71,
    "光が丘": 105,
    "吉祥寺": 110,  # 三鷹・吉祥寺（当院から約40分）
}

MITAKA_KEYWORDS = ("三鷹", "吉祥寺", "下連雀")
WAKO_KEYWORDS = ("和光", "埼玉")
CLINIC_TO_MITAKA_MIN = 40
TORIGOE_HOME_TO_MITAKA_MIN = 25  # 鳥越先生自宅（東大泉）出発時の一般的な三鷹見込み
# 患者別：出発地点からの所要（明示指定。鳥越でも25分にしない）
DEPARTURE_TRAVEL_MIN_BY_ID: dict[str, int] = {
    "b216": 40,  # 鴇田榮子（三鷹市下連雀）
    "b288": 40,  # 水上次義（三鷹市下連雀・同棟）
    "b511": 22,  # 小林誠（高松・榎本から）
    "b508": 25,  # 雨谷浩子（新座・鳥越自宅から）
}
CLINIC_TO_WAKO_MIN = 30
DEFAULT_TRAVEL_MIN = 12
VISIT_MIN = 10
FIRST_VISIT_OFFSET_MIN = 20

# ルート上に残し、表ではキャンセル表示（ETA・移動時間に含めない）
CANCELLED_VISIT_KEYS: frozenset[tuple[str, str, str]] = frozenset({
    ("9/5(土)", "鳥越", "b373"),  # 鴇田よし子
    ("9/26(土)", "鳥越", "b492"),  # 大和紀代子・10月初旬へ
})
CANCELLED_VISIT_REMARK: dict[tuple[str, str, str], str] = {
    ("9/5(土)", "鳥越", "b373"): "キャンセル",
    ("9/26(土)", "鳥越", "b492"): "キャンセル（10月初旬へ）",
}


@dataclass
class Patient:
    chart_id: str
    name: str
    insurance: str
    deadline: str
    comment: str
    status_note: str
    eligible_days: set[str] = field(default_factory=set)
    address: str = ""
    area: str = ""
    doctor_pref: str = "auto"  # hanawa / katayama / torikoe / auto
    pinned: dict[str, str] = field(default_factory=dict)  # day -> doctor
    notes: list[str] = field(default_factory=list)
    pair_with: str | None = None
    visit_count: int = 1
    myna: bool = False  # 希望CSV「マイナ利用」
    hope_biko: str = ""  # 希望CSV「備考」


@dataclass
class Assignment:
    patient: Patient
    day_key: str
    doctor: str
    order: int = 0
    eta: str = ""
    remark: str = ""
    cancelled: bool = False


def normalize_chart_id(cid: str) -> str:
    """希望CSVの b075 を台帳の b75 に揃える。台帳 b42 は希望CSVの b042 に揃える。"""
    cid = (cid or "").strip()
    if cid == "b075":
        return "b75"
    if cid == "b42":
        return "b042"
    return cid


def chart_id_aliases(cid: str) -> list[str]:
    """台帳 b65 と希望CSV b065 など、ゼロ埋めの差を吸収する。"""
    cid = normalize_chart_id(cid)
    if not cid:
        return []
    aliases = [cid]
    if cid.startswith("b") and cid[1:].isdigit():
        n = int(cid[1:])
        aliases.extend((f"b{n}", f"b{n:03d}"))
    return list(dict.fromkeys(aliases))


def apply_address_overrides(out: dict[str, str]) -> dict[str, str]:
    for cid, addr in ADDRESS_OVERRIDES.items():
        for key in chart_id_aliases(cid):
            if not out.get(key):
                out[key] = addr
    return out


def load_ledger() -> dict[str, str]:
    global LEDGER_NAMES
    out: dict[str, str] = {}
    LEDGER_NAMES = {}
    if not LEDGER_CSV.exists():
        return apply_address_overrides(out)

    def remember(cid: str, addr: str, name: str) -> None:
        for key in chart_id_aliases(cid):
            if addr:
                out[key] = addr
            if name:
                LEDGER_NAMES[key] = name

    with LEDGER_CSV.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        try:
            i_id = header.index("ID")
            i_addr = header.index("利用者住所")
            i_name = header.index("氏名") if "氏名" in header else None
        except ValueError:
            f.seek(0)
            for row in csv.DictReader(f):
                cid = (row.get("ID") or "").strip()
                addr = (row.get("利用者住所") or "").strip()
                name = display_name(row.get("氏名"))
                if cid:
                    remember(cid, addr, name)
            return apply_address_overrides(out)
        for row in reader:
            if len(row) <= max(i_id, i_addr):
                continue
            cid = (row[i_id] or "").strip()
            addr = (row[i_addr] or "").strip()
            name = display_name(row[i_name]) if i_name is not None and len(row) > i_name else ""
            if cid:
                remember(cid, addr, name)
    return apply_address_overrides(out)


def load_history_areas() -> dict[str, str]:
    out: dict[str, str] = {}
    with HISTORY_CSV.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            vc = (row.get("訪問コード") or "").strip()
            area = (row.get("エリア") or "").strip()
            if vc and area:
                out[vc] = area
    return out


def visit_code(chart_id: str) -> str:
    if chart_id.startswith("b") and chart_id[1:].isdigit():
        return f"{int(chart_id[1:]):06d}"
    return ""


def fmt_deadline(s: str) -> str:
    if not s:
        return "—"
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return f"{int(m.group(2))}/{int(m.group(3))}"
    return s


def parse_deadline(s: str) -> date | None:
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s or "")
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def is_mitaka_area(area: str, address: str = "") -> bool:
    return area == "吉祥寺" or any(k in (area + address) for k in MITAKA_KEYWORDS)


def infer_area(chart_id: str, address: str, hist_areas: dict[str, str]) -> str:
    vc = visit_code(chart_id)
    if vc and vc in hist_areas:
        return hist_areas[vc]
    if "三鷹" in address or "下連雀" in address:
        return "吉祥寺"
    if "新座" in address:
        return "新座"
    if "和光" in address or address.startswith("埼玉"):
        return "和光"
    if "光が丘" in address:
        return "光が丘"
    if "高松" in address:
        return "高松"
    if "谷原" in address and "ライブラリ" in address:
        return "L谷原"
    if "ファミリー・ホスピス大泉" in address or "FH" in address:
        return "FH大泉"
    if "ファミリー・ホスピス上石神井" in address:
        return "FH上石神井"
    if "そんぽの家S井荻" in address:
        return "S井荻"
    if "そんぽの家S大泉北" in address or "大泉町5-2-5" in address:
        return "S大泉町5"
    if "CLASWELL" in address or "ＣＬＡＳＷＥＬＬ" in address:
        return "CW下石"
    if "下保谷" in address:
        return "下保谷"
    if "西東京" in address and "泉町" in address:
        return "西東京泉町"
    if "西東京" in address and ("北町" in address or "東町" in address or "保谷" in address):
        return "保谷"
    if "石神井台" in address:
        m = re.search(r"石神井台(\d)", address)
        return f"石台{m.group(1)}" if m else "石台"
    if "石神井町" in address:
        return "石町"
    if "高野台" in address:
        return "高野台"
    if "関町" in address:
        return "関町"
    if "土支田" in address:
        return "土支田"
    if "南田中" in address:
        return "南田中"
    if "大泉学園町" in address:
        m = re.search(r"大泉学園町(\d)", address)
        return f"学{m.group(1)}" if m else "学園"
    if "東大泉" in address:
        m = re.search(r"東大泉(\d)", address)
        return f"東{m.group(1)}" if m else "東大泉"
    if "西大泉" in address:
        m = re.search(r"西大泉(\d)", address)
        return f"西{m.group(1)}" if m else "西大泉"
    if "大泉町" in address or "大泉町" in address:
        m = re.search(r"大泉町(\d)", address)
        return f"大町{m.group(1)}" if m else "大町"
    if "三原台" in address:
        return "三原台"
    if "上石神井" in address:
        return "上石"
    if "下石神井" in address:
        return "下石神井3" if "3-" in address else "下石"
    if "井草" in address:
        return "井草3"
    return "その他"


def classify_doctor_pref(comment: str, insurance: str, name: str) -> str:
    c = comment or ""
    if any(k in c for k in ("院長", "花輪", "処方箋")):
        return "hanawa"
    if "片山" in c and "NG" in c:
        return "torikoe"
    if "鳥越" in c and "NG" in c:
        return "hanawa"
    if "月曜NG" in c or "月曜ＮＧ" in c or "月曜日はデイ" in c or "月曜デイ" in c:
        return "torikoe"
    if "土曜NG" in c or "土曜ＮＧ" in c:
        if "午後NG" in c or "月・土とも午後NG" in c or "月土とも午後" in c:
            return "hanawa"
        if "月曜ＰＭ" in c or "月曜PM" in c:
            return "hanawa"
        return "katayama"
    return "auto"


def load_patients() -> list[Patient]:
    ledger = load_ledger()
    hist_areas = load_history_areas()
    patients: list[Patient] = []

    with HOPE_CSV.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            cid = normalize_chart_id(row.get("id") or row.get("ID") or "")
            if not cid or cid in EXCLUDED_IDS:
                continue
            name = (row.get("氏名") or row.get("名前") or "").strip()
            status_note = (row.get("状態") or row.get("休止・再開・終了") or "").strip()
            comment = (row.get("コメント") or "").strip()
            status = status_note + comment
            if cid not in INCLUDE_DESPITE_STATUS:
                if any(k in status_note for k in ("終了", "休止", "逝去", "入院中")):
                    continue
                # コメントの「ご逝去」は家族の話のことがある（例: 大和紀代子・姉）。状態列を優先。
                if "往診不要" in comment:
                    continue

            eligible = set()
            for dk in DAY_ORDER:
                val = (row.get(dk) or "").strip().upper()
                if val == "FALSE":
                    eligible.add(dk)

            myna_raw = (row.get("マイナ利用") or "").strip().upper()
            insurance = (row.get("区分") or "").strip()
            display = re.sub(r"\s+", " ", name.replace("　", " ")).strip()
            display = re.sub(r"\s*休止後の往診\s*", "", display).strip()
            display = re.sub(r"\s*追加\s*$", "", display).strip()
            p = Patient(
                chart_id=cid,
                name=display,
                insurance=insurance,
                deadline=(row.get("期限") or row.get("往診期限") or "").strip(),
                comment=comment,
                status_note=status_note,
                eligible_days=eligible,
                address=ledger.get(cid, ""),
                doctor_pref=classify_doctor_pref(comment, insurance, name),
                myna=myna_raw == "TRUE",
                hope_biko=(row.get("備考") or "").strip(),
            )
            if NAME_OVERRIDES.get(cid):
                p.name = NAME_OVERRIDES[cid]
            elif LEDGER_NAMES.get(cid):
                p.name = LEDGER_NAMES[cid]
            p.area = infer_area(cid, p.address, hist_areas)
            p.eligible_days.discard("9/12(土)")
            patients.append(p)

    append_manual_patients(patients, ledger, hist_areas)
    apply_pins(patients)
    return patients


def append_manual_patients(
    patients: list[Patient],
    ledger: dict[str, str],
    hist_areas: dict[str, str],
) -> None:
    """希望CSV未掲載／休止扱いだが手動配置する患者。"""
    by_id = {p.chart_id: p for p in patients}
    manuals: list[Patient] = [
        Patient(
            chart_id="b507",
            name="片野妙子",
            insurance="介護",
            deadline="",
            comment="",
            status_note="",
            eligible_days={"9/5(土)"},
            address=ledger.get("b507") or "東京都練馬区東大泉5丁目15-2-405",
            doctor_pref="torikoe",
        ),
        Patient(
            chart_id="b511",
            name="小林誠",
            insurance="介護",
            deadline="2026-09-30",
            comment="9/1退院・9/2スキップ開始。退院1ヶ月以内。月曜10:30-13:00／土曜12:30-15:30",
            status_note="",
            eligible_days={"9/26(土)", "9/7(月)", "9/28(月)"},
            address=ledger.get("b511") or ADDRESS_OVERRIDES["b511"],
            doctor_pref="torikoe",
        ),
        Patient(
            chart_id="b512",
            name=LEDGER_NAMES.get("b512") or "清水輝男",
            insurance="介護",
            deadline="2026-09-30",
            comment="新規初回。和光市白子1丁目4番3号",
            status_note="",
            eligible_days={"9/7(月)"},
            address=ledger.get("b512") or "埼玉県和光市白子1丁目4番3号",
            doctor_pref="katayama",
        ),
        Patient(
            chart_id="b508",
            name=LEDGER_NAMES.get("b508") or "雨谷浩子",
            insurance="介護",
            deadline="2026-09-30",
            comment="新規。新座市池田。9/19先頭（後藤夫妻のリハ前に回るため12:30出発）",
            status_note="",
            eligible_days={"9/19(土)"},
            address=ledger.get("b508") or "新座市池田3-3-3",
            doctor_pref="torikoe",
        ),
        Patient(
            chart_id="b506",
            name=LEDGER_NAMES.get("b506") or "菅谷清子",
            insurance="介護",
            deadline="2026-09-30",
            comment="新規。FH大泉学園ハウス108。9/19後藤夫妻の直後",
            status_note="",
            eligible_days={"9/19(土)"},
            address=ledger.get("b506")
            or "練馬区大泉学園町2-1-24　ファミリー・ホスピス大泉学園ハウス 108",
            doctor_pref="torikoe",
        ),
        Patient(
            chart_id="b513",
            name=LEDGER_NAMES.get("b513") or "大橋正美",
            insurance="介護",
            deadline="2026-09-29",
            comment="新規。高野台。9/28花輪・和田の直後",
            status_note="",
            eligible_days={"9/28(月)"},
            address=ledger.get("b513") or "練馬区高野台4-12-12",
            doctor_pref="hanawa",
        ),
        Patient(
            chart_id="b510",
            name=LEDGER_NAMES.get("b510") or "國峯浩",
            insurance="介護",
            deadline="2026-09-30",
            comment="新規。そんぽの家S西東京泉町211。9/26安田の直前（大和キャンセル枠）",
            status_note="",
            eligible_days={"9/26(土)"},
            address=ledger.get("b510")
            or "西東京市泉町2-14-13　そんぽの家S西東京泉町211号室",
            doctor_pref="torikoe",
        ),
        Patient(
            chart_id="b301",
            name=LEDGER_NAMES.get("b301") or "瓦林裕美",
            insurance="介護",
            deadline="2026-09-30",
            comment="8月入院キャンセル分。9/19鳥越・芳野の直後（高野台3）",
            status_note="",
            eligible_days={"9/19(土)"},
            address=ledger.get("b301") or "東京都練馬区高野台3-36-8",
            doctor_pref="torikoe",
        ),
        Patient(
            chart_id="b514",
            name=NAME_OVERRIDES.get("b514") or LEDGER_NAMES.get("b514") or "造酒 侚子",
            insurance="介護",
            deadline="2026-09-30",
            comment="新規。学園町4-8-4。9/14今井鈴の直後。AM～13:00在宅",
            status_note="",
            eligible_days={"9/14(月)"},
            address=ledger.get("b514") or ADDRESS_OVERRIDES["b514"],
            doctor_pref="hanawa",
        ),
        Patient(
            chart_id="b381",
            name="東村博",
            insurance="介護",
            deadline="2026-09-30",
            comment="9/1退院・9/2スキップ再開。退院1ヶ月以内。9/26 PM可",
            status_note="",
            eligible_days={"9/26(土)"},
            address=ledger.get("b381") or ADDRESS_OVERRIDES["b381"],
            doctor_pref="torikoe",
        ),
        Patient(
            chart_id="b271",
            name="越智博",
            insurance="介護",
            deadline="2026-09-30",
            comment="8/26退院・初回スキップ再開。月曜AM可・土曜可。香水（大泉町2）の前後希望",
            status_note="",
            eligible_days={"9/28(月)", "9/26(土)", "9/7(月)"},
            address=ledger.get("b271") or ADDRESS_OVERRIDES["b271"],
            doctor_pref="hanawa",
        ),
        Patient(
            chart_id="b428",
            name=LEDGER_NAMES.get("b428") or "仲 里路",
            insurance="介護",
            deadline="2026-08-31",
            comment="入院休止後の再開。9/26鳥越・小林誠の直後（S井荻）",
            status_note="",
            eligible_days={"9/26(土)"},
            address=ledger.get("b428") or ADDRESS_OVERRIDES["b428"],
            doctor_pref="torikoe",
        ),
    ]
    for p in manuals:
        if p.chart_id in by_id:
            existing = by_id[p.chart_id]
            if p.address:
                existing.address = p.address
                existing.area = infer_area(p.chart_id, p.address, hist_areas)
            if NAME_OVERRIDES.get(p.chart_id):
                existing.name = NAME_OVERRIDES[p.chart_id]
            elif LEDGER_NAMES.get(p.chart_id):
                existing.name = LEDGER_NAMES[p.chart_id]
            continue
        p.area = infer_area(p.chart_id, p.address, hist_areas)
        patients.append(p)
        by_id[p.chart_id] = p


def pin(p: Patient, day_key: str, doctor: str, note: str = "") -> None:
    if day_key not in DAY_META:
        return
    p.pinned[day_key] = doctor
    p.eligible_days = {day_key}
    if note:
        p.notes.append(note)


def first_eligible(p: Patient, days: list[str] | None = None) -> str | None:
    for dk in days or DAY_ORDER:
        if dk in p.eligible_days:
            return dk
    return None


def apply_pins(patients: list[Patient]) -> None:
    by_id = {p.chart_id: p for p in patients}

    def pin_pair(a: str, b: str, prefer_days: list[str] | None = None, doctor: str | None = None) -> None:
        if a not in by_id or b not in by_id:
            return
        pa, pb = by_id[a], by_id[b]
        overlap = [dk for dk in (prefer_days or DAY_ORDER) if dk in pa.eligible_days and dk in pb.eligible_days]
        if not overlap:
            overlap = [dk for dk in DAY_ORDER if dk in pa.eligible_days and dk in pb.eligible_days]
        if not overlap:
            return
        dk = overlap[0]
        doc = doctor or ("鳥越" if DAY_META[dk]["dow"] == "土" else "花輪")
        pa.pair_with = b
        pb.pair_with = a
        pin(pa, dk, doc, "ご夫婦・同日連続")
        pin(pb, dk, doc, "ご夫婦・同日連続")

    # ご夫婦・同日
    pin_pair("b464", "b475", ["9/5(土)", "9/19(土)", "9/26(土)"], "鳥越")  # 黒羽
    pin_pair("b410", "b246", ["9/7(月)"], "片山")  # 坂本幸子・和光（月曜AM NG）
    pin_pair("b042", "b401", ["9/19(土)", "9/5(土)", "9/26(土)"], "鳥越")  # 後藤（9/19午後前半でリハ回避）
    pin_pair("b473", "b449", ["9/26(土)", "9/5(土)", "9/19(土)"], "鳥越")  # 長谷川

    # 医療（9月は各1回。期限前配置）
    if "b253" in by_id:
        pin(by_id["b253"], "9/28(月)", "花輪", "医療・希望どおり9/28花輪")
        by_id["b253"].doctor_pref = "hanawa"
    if "b370" in by_id:
        pin(by_id["b370"], "9/7(月)", "片山", "医療・期限9/16前の9/7片山")
        by_id["b370"].doctor_pref = "katayama"
    if "b491" in by_id:
        pin(by_id["b491"], "9/14(月)", "花輪", "医療・期限9/16前。月曜13:00-13:40NGのため花輪AM")
        by_id["b491"].doctor_pref = "hanawa"
    if "b328" in by_id:
        pin(by_id["b328"], "9/14(月)", "花輪", "医療・期限9/16。9/7不在のため14花輪・三上の直後")
        by_id["b328"].doctor_pref = "hanawa"
    if "b75" in by_id:
        pin(by_id["b75"], "9/26(土)", "鳥越", "医療・期限9/28前の9/26鳥越")
        by_id["b75"].doctor_pref = "torikoe"
    if "b474" in by_id:
        pin(by_id["b474"], "9/14(月)", "花輪", "医療・マイナは月曜向き。期限9/30の9/14花輪")
        by_id["b474"].doctor_pref = "hanawa"

    # 院長希望・施設（ミモザ等）
    if "b324" in by_id:
        pin(by_id["b324"], "9/7(月)", "花輪", "皮膚科相談のため月曜AM院長")
        by_id["b324"].doctor_pref = "hanawa"
    if "b384" in by_id:
        pin(by_id["b384"], "9/28(月)", "花輪", "ミモザ・土曜NG（9/14花輪満枠のため28へ）")
        by_id["b384"].doctor_pref = "hanawa"
    if "b298" in by_id:
        pin(by_id["b298"], "9/28(月)", "花輪", "ミモザ・土曜NG")
        by_id["b298"].doctor_pref = "hanawa"
    if "b278" in by_id:
        pin(by_id["b278"], "9/7(月)", "花輪", "9/7第一希望・皮膚科を院長へ相談")
        by_id["b278"].doctor_pref = "hanawa"
    if "b152" in by_id:
        by_id["b152"].eligible_days = set()
        by_id["b152"].notes.append(
            "プラウドタワー・火金の院長休憩往診。月土リスト対象外。"
            "候補 9/8・11・15・18 の14:30–15:00。ヤナカ確認中"
        )
    if "b368" in by_id:
        pin(by_id["b368"], "9/7(月)", "片山", "7日希望。10:15-10:55リハNGのため片山")
        by_id["b368"].doctor_pref = "katayama"
    if "b131" in by_id:
        pin(by_id["b131"], "9/14(月)", "花輪", "月曜希望")
        by_id["b131"].doctor_pref = "hanawa"
    if "b487" in by_id:
        pin(by_id["b487"], "9/28(月)", "花輪", "月曜日希望")
        by_id["b487"].doctor_pref = "hanawa"
    if "b138" in by_id:
        pin(by_id["b138"], "9/5(土)", "鳥越", "土曜14時以降・鳥越希望")
        by_id["b138"].doctor_pref = "torikoe"
    if "b492" in by_id:
        pin(
            by_id["b492"],
            "9/26(土)",
            "鳥越",
            "8/15未実施分。2026-08-28キャンセル・10月初旬へ",
        )
    if "b507" in by_id:
        pin(
            by_id["b507"],
            "9/5(土)",
            "鳥越",
            "2026-08-28追加。8/29キャンセル分を9/5先頭へ（東大泉5）",
        )
        by_id["b507"].doctor_pref = "torikoe"
        by_id["b507"].address = "東京都練馬区東大泉5丁目15-2-405"
        by_id["b507"].area = infer_area("b507", by_id["b507"].address, {})
    if "b427" in by_id:
        dk = first_eligible(by_id["b427"], ["9/7(月)", "9/14(月)", "9/28(月)"])
        if dk:
            pin(by_id["b427"], dk, "花輪" if dk != "9/7(月)" else "片山", "追加・月曜")
    if "b285" in by_id:
        pin(by_id["b285"], "9/28(月)", "花輪", "月曜午前遅め希望")
        by_id["b285"].doctor_pref = "hanawa"
    if "b342" in by_id:
        pin(by_id["b342"], "9/14(月)", "花輪", "土曜NG。10:30-11:30リハNGのため11:30以降")
        by_id["b342"].doctor_pref = "hanawa"
    if "b343" in by_id:
        pin(by_id["b343"], "9/19(土)", "鳥越", "9/12中止のため土曜へ（9/5 NG）")
    if "b301" in by_id:
        pin(by_id["b301"], "9/19(土)", "鳥越", "8月入院キャンセル分。芳野の直後（高野台3）")
        by_id["b301"].doctor_pref = "torikoe"
    if "b162" in by_id:
        pin(by_id["b162"], "9/19(土)", "鳥越", "9/12中止・月曜NGのため9/19")
        by_id["b162"].doctor_pref = "torikoe"
    if "b199" in by_id:
        pin(by_id["b199"], "9/19(土)", "鳥越", "9/26別医療機関受診のため9/19・菅谷の直後")
    if "b421" in by_id:
        pin(by_id["b421"], "9/7(月)", "花輪", "月土とも14時以降NGのため花輪AM")
        by_id["b421"].doctor_pref = "hanawa"
    if "b356" in by_id:
        pin(by_id["b356"], "9/14(月)", "花輪", "土曜NG")
        by_id["b356"].doctor_pref = "hanawa"
    if "b116" in by_id:
        pin(by_id["b116"], "9/7(月)", "片山", "12:15-13:15リハNGのため片山後半")
        by_id["b116"].doctor_pref = "katayama"
    if "b353" in by_id:
        pin(by_id["b353"], "9/7(月)", "片山", "11:30-12:30訪看NG")
        by_id["b353"].doctor_pref = "katayama"
    if "b378" in by_id:
        pin(by_id["b378"], "9/7(月)", "花輪", "26・28は15時以降通院の可能性・AM希望")
        by_id["b378"].doctor_pref = "hanawa"
    if "b511" in by_id:
        pin(
            by_id["b511"],
            "9/26(土)",
            "鳥越",
            "新規・退院1ヶ月。土曜12:30-15:30のため9/26田代の直後",
        )
        by_id["b511"].doctor_pref = "torikoe"
        by_id["b511"].notes.append("土曜12:30-15:30")
    if "b512" in by_id:
        pin(by_id["b512"], "9/7(月)", "片山", "新規初回。和光白子1-4-3・大越の直後")
        by_id["b512"].doctor_pref = "katayama"
    if "b508" in by_id:
        pin(by_id["b508"], "9/19(土)", "鳥越", "新規。新座池田・9/19先頭。後藤リハ回避のため12:30出発")
        by_id["b508"].doctor_pref = "torikoe"
    if "b506" in by_id:
        pin(by_id["b506"], "9/19(土)", "鳥越", "新規。FH大泉学園・後藤夫妻の直後")
        by_id["b506"].doctor_pref = "torikoe"
    if "b513" in by_id:
        pin(by_id["b513"], "9/28(月)", "花輪", "新規。高野台・和田の直後。期限9/29")
        by_id["b513"].doctor_pref = "hanawa"
    if "b510" in by_id:
        pin(by_id["b510"], "9/26(土)", "鳥越", "新規。西東京泉町・安田の直前（大和キャンセル枠）")
        by_id["b510"].doctor_pref = "torikoe"
    if "b514" in by_id:
        pin(by_id["b514"], "9/14(月)", "花輪", "新規。学園町4・今井鈴の直後。AM～13:00在宅")
        by_id["b514"].doctor_pref = "hanawa"
    if "b381" in by_id:
        pin(by_id["b381"], "9/26(土)", "鳥越", "再開・退院1ヶ月。吉田と澤味の間")
        by_id["b381"].doctor_pref = "torikoe"
    if "b271" in by_id:
        pin(
            by_id["b271"],
            "9/28(月)",
            "花輪",
            "再開。9/28花輪末尾。8/26退院の1ヶ月は9/26のため2日超過",
        )
        by_id["b271"].doctor_pref = "hanawa"
    if "b428" in by_id:
        pin(
            by_id["b428"],
            "9/26(土)",
            "鳥越",
            "再開。9/26鳥越・小林誠の直後（S井荻）",
        )
        by_id["b428"].doctor_pref = "torikoe"

    # 花輪定員5のため、残りの月曜希望は片山（9/7のみ）へ寄せる準備
    for cid in ("b498", "b307", "b065", "b439"):
        if cid in by_id and "9/7(月)" in by_id[cid].eligible_days and not by_id[cid].pinned:
            by_id[cid].doctor_pref = "katayama"


def choose_doctor(p: Patient, day_key: str, counts: dict[tuple[str, str], int]) -> str | None:
    if day_key in p.pinned:
        doc = p.pinned[day_key]
        if counts.get((doc, day_key), 0) < CAPACITY.get((doc, day_key), 99):
            return doc
        return None
    dow = DAY_META[day_key]["dow"]
    if dow == "土":
        if counts.get(("鳥越", day_key), 0) < CAPACITY.get(("鳥越", day_key), 20):
            return "鳥越"
        return None
    if p.doctor_pref == "hanawa":
        if counts.get(("花輪", day_key), 0) < CAPACITY.get(("花輪", day_key), 20):
            return "花輪"
        return None
    if p.doctor_pref == "katayama":
        if day_key in KATAYAMA_DAYS and counts.get(("片山", day_key), 0) < CAPACITY.get(("片山", day_key), 20):
            return "片山"
        if counts.get(("花輪", day_key), 0) < CAPACITY.get(("花輪", day_key), 20):
            return "花輪"
        return None
    if p.doctor_pref == "torikoe":
        return None
    if day_key in KATAYAMA_DAYS:
        if counts.get(("花輪", day_key), 0) < CAPACITY.get(("花輪", day_key), 20):
            return "花輪"
        if counts.get(("片山", day_key), 0) < CAPACITY.get(("片山", day_key), 20):
            return "片山"
    if counts.get(("花輪", day_key), 0) < CAPACITY.get(("花輪", day_key), 20):
        return "花輪"
    return None


def day_load_score(counts: dict[tuple[str, str], int], day_key: str) -> int:
    return sum(counts.get((doc, day_key), 0) for doc in DAY_META[day_key]["doctors"])



def load_schedule_overrides() -> dict:
    """HTML手動編集の正本オーバーレイ。routes: {day: {doctor: [chart_id,...]}}"""
    if OVERRIDES_PATH.exists():
        try:
            data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARN: failed to load overrides: {e}")
            data = {}
        if isinstance(data, dict):
            routes = data.get("routes") or {}
            if isinstance(routes, dict) and routes:
                print(f"Loaded schedule overrides from {OVERRIDES_PATH.name}")
                return data

    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    try:
        # JSON に routes が無いときだけ。sqlite 未初期化でも生成を落とさない。
        from schedule.sqlite_store import SqliteScheduleRepository

        store = SqliteScheduleRepository()
        if store.has_routes(PERIOD_KEY):
            doc = store.export_overrides_document(PERIOD_KEY)
            routes = doc.get("routes") or {}
            if isinstance(routes, dict) and routes:
                print(
                    f"Loaded schedule overrides from db/schedule.sqlite "
                    f"({PERIOD_KEY}, {len(routes)} days)"
                )
                return doc
    except Exception as e:
        print(f"WARN: schedule DB unavailable: {e}")
    return {}


def apply_route_overrides(
    assignments: list[Assignment],
    patients: list[Patient],
    overrides: dict,
) -> list[Assignment]:
    """overrides.routes に載る患者は日・医師を上書き。未記載患者は自動割当を維持。

    routes に一度でも載った患者は、routes 内の出現回数ぶんだけ再配置する。
    visit_count（医療2回など）を満たさない場合は失敗させる。
    """
    routes = (overrides or {}).get("routes") or {}
    if not routes:
        return assignments

    by_id = {p.chart_id: p for p in patients}

    route_counts: Counter[str] = Counter()
    added: list[Assignment] = []
    errors: list[str] = []

    for day_key, day_routes in routes.items():
        if day_key not in DAY_META:
            errors.append(f"不明な日付: {day_key}")
            continue
        if not isinstance(day_routes, dict):
            errors.append(f"routes[{day_key}] がオブジェクトではありません")
            continue
        for doctor, ids in day_routes.items():
            if doctor not in DAY_META[day_key]["doctors"]:
                errors.append(f"{day_key} に医師「{doctor}」の枠はありません")
                continue
            if not isinstance(ids, list):
                errors.append(f"routes[{day_key}][{doctor}] が配列ではありません")
                continue
            for cid in ids:
                p = by_id.get(cid)
                if not p:
                    errors.append(f"不明な患者ID: {cid}")
                    continue
                route_counts[cid] += 1
                added.append(
                    Assignment(
                        patient=p,
                        day_key=day_key,
                        doctor=doctor,
                        remark="手動調整",
                    )
                )

    if errors:
        raise SystemExit("schedule_overrides.json が不正です:\n- " + "\n- ".join(errors))

    if not route_counts:
        return assignments

    for cid, n in route_counts.items():
        p = by_id[cid]
        need = max(1, p.visit_count)
        if n < need:
            errors.append(
                f"{cid} {p.name}: overrides に {n} 回しかなく、必要回数 {need} に足りません"
            )
    if errors:
        raise SystemExit("schedule_overrides.json の回数が不足しています:\n- " + "\n- ".join(errors))

    overridden_ids = set(route_counts)
    kept = [a for a in assignments if a.patient.chart_id not in overridden_ids]
    print(f"Applied schedule overrides: {len(overridden_ids)} patients (manual routes)")
    return kept + added



def order_group_with_overrides(
    group: list[Assignment],
    doctor: str,
    day_key: str,
    overrides: dict,
) -> list[Assignment]:
    """overrides に順があればそれを使い、なければルート最適化。"""
    routes = (overrides or {}).get("routes") or {}
    route_ids = None
    day_routes = routes.get(day_key)
    if isinstance(day_routes, dict):
        route_ids = day_routes.get(doctor)
    if route_ids and isinstance(route_ids, list):
        by_id = {a.patient.chart_id: a for a in group}
        ordered = [by_id[cid] for cid in route_ids if cid in by_id]
        seen = set(route_ids)
        for a in group:
            if a.patient.chart_id not in seen:
                ordered.append(a)
        compute_schedule_times(ordered, doctor)
        return ordered
    group = optimize_route(group, doctor)
    compute_schedule_times(group, doctor)
    return group


def assign_patients(patients: list[Patient]) -> list[Assignment]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    assignments: list[Assignment] = []
    assigned_keys: set[tuple[str, str, int]] = set()

    def add_assignment(p: Patient, day_key: str, doctor: str, remark: str = "") -> bool:
        if counts.get((doctor, day_key), 0) >= CAPACITY.get((doctor, day_key), 99):
            return False
        key = (p.chart_id, day_key, len([a for a in assignments if a.patient.chart_id == p.chart_id]))
        if key in assigned_keys:
            return False
        assignments.append(Assignment(patient=p, day_key=day_key, doctor=doctor, remark=remark))
        counts[(doctor, day_key)] += 1
        assigned_keys.add(key)
        return True

    # 1) 固定割当（期限・医療を優先してからその他）
    pin_priority = {
        "b253": 0, "b370": 0, "b491": 0, "b328": 0, "b75": 0, "b474": 0,
        "b464": 1, "b475": 1, "b410": 1, "b246": 1, "b042": 1, "b401": 1,
        "b473": 1, "b449": 1,
    }
    pinned_patients = sorted(
        [p for p in patients if p.pinned],
        key=lambda p: (pin_priority.get(p.chart_id, 9), p.chart_id),
    )
    for p in pinned_patients:
        for dk, doc in p.pinned.items():
            add_assignment(p, dk, doc, remark="固定割当")

    # 2) 残りを制約の厳しい順に均等配置
    remaining: list[Patient] = []
    for p in patients:
        existing = sum(1 for a in assignments if a.patient.chart_id == p.chart_id)
        need = p.visit_count - existing
        for _ in range(need):
            remaining.append(p)

    def tightness(p: Patient) -> tuple[int, int]:
        opts = [d for d in p.eligible_days if d not in p.pinned]
        return (len(opts), -len(p.comment))

    remaining.sort(key=tightness)

    target_per_day = {dk: 8 for dk in DAY_ORDER}
    target_per_day["9/7(月)"] = 14
    target_per_day["9/14(月)"] = 5
    target_per_day["9/28(月)"] = 6
    target_per_day["9/19(土)"] = 10
    target_per_day["9/26(土)"] = 10

    for p in remaining:
        options: list[tuple[tuple[int, int], str, str]] = []
        for dk in DAY_ORDER:
            if dk in p.pinned:
                continue
            if dk not in p.eligible_days:
                continue
            doc = choose_doctor(p, dk, counts)
            if not doc:
                continue
            load = day_load_score(counts, dk)
            score = (load - target_per_day[dk], DAY_ORDER.index(dk))
            options.append((score, dk, doc))
        options.sort(key=lambda x: x[0])
        placed = False
        for _, dk, doc in options:
            if add_assignment(p, dk, doc):
                placed = True
                break
        if not placed:
            p.notes.append("⚠️割当不可・要手動調整")

    return assignments


def travel_minutes(
    prev_area: str | None,
    next_area: str,
    next_address: str = "",
    from_clinic: bool = False,
    doctor: str = "花輪",
    chart_id: str | None = None,
) -> int:
    if from_clinic and chart_id and chart_id in DEPARTURE_TRAVEL_MIN_BY_ID:
        return DEPARTURE_TRAVEL_MIN_BY_ID[chart_id]
    if from_clinic:
        if is_mitaka_area(next_area, next_address):
            return TORIGOE_HOME_TO_MITAKA_MIN if doctor.startswith("鳥越") else CLINIC_TO_MITAKA_MIN
        if any(k in next_area for k in WAKO_KEYWORDS) or next_area == "和光":
            return CLINIC_TO_WAKO_MIN if not doctor.startswith("鳥越") else 20
        return FIRST_VISIT_OFFSET_MIN
    if is_mitaka_area(next_area, next_address):
        return TORIGOE_HOME_TO_MITAKA_MIN if doctor.startswith("鳥越") else CLINIC_TO_MITAKA_MIN
    if prev_area == next_area:
        return 5
    # 近隣エリアの短縮（16:30帰宅・NG余裕のため）
    near = {
        frozenset({"東1", "石台1"}): 12,
        frozenset({"東1", "石台2"}): 12,
        frozenset({"西1", "西2"}): 8,
        frozenset({"西2", "西3"}): 8,
        frozenset({"西2", "西5"}): 10,
        frozenset({"西3", "西5"}): 10,
        frozenset({"西5", "東1"}): 15,
        frozenset({"西3", "東1"}): 15,
        frozenset({"下保谷", "大町6"}): 10,
        frozenset({"保谷", "大町6"}): 10,
        frozenset({"関町", "和光"}): 15,
        frozenset({"石台3", "学5"}): 12,
        frozenset({"学4", "学5"}): 8,
        frozenset({"学4", "石台3"}): 12,
        frozenset({"大町2", "西4"}): 12,
        frozenset({"西4", "西2"}): 8,
        frozenset({"高松", "谷原"}): 15,
        frozenset({"高松", "L谷原"}): 15,
        frozenset({"高松", "石町"}): 15,
        frozenset({"関町", "西東京泉町"}): 12,
        frozenset({"新座", "下保谷"}): 18,
        frozenset({"高野台", "大町2"}): 12,
    }
    hop = near.get(frozenset({prev_area or "", next_area}))
    if hop is not None:
        return hop
    pa = AREA_CLUSTER_ORDER.get(prev_area or "", 50)
    na = AREA_CLUSTER_ORDER.get(next_area, 50)
    diff = abs(na - pa)
    if diff > 40:
        return 25
    if diff > 20:
        return 18
    return DEFAULT_TRAVEL_MIN


# 同建物・同施設はルート上も一塊（pair_withの1対1を超えるクラスタ）
BUILDING_CLUSTERS: list[frozenset[str]] = [
    frozenset({"b349", "b213", "b404"}),  # S大泉北
    frozenset({"b364", "b493", "b399", "b445"}),  # FH大泉（8/29寄せ）
    frozenset({"b500", "b483"}),  # FH大泉 徳山・木村チヱ
    frozenset({"b322", "b452"}),  # L谷原
    frozenset({"b149", "b148"}),  # 平峯
    frozenset({"b398", "b443"}),  # 寺野
    frozenset({"b236", "b451"}),  # 齊藤荘
    frozenset({"b376", "b502"}),  # そんぽの家S土支田（吉岡・飯澤）
    frozenset({"b320", "b380"}),  # S井荻
    frozenset({"b392", "b488"}),  # 上石神井（そんぽ上石神井・上石南町）
]


def building_mates(chart_id: str) -> frozenset[str]:
    for cluster in BUILDING_CLUSTERS:
        if chart_id in cluster:
            return cluster
    return frozenset({chart_id})


def build_visit_units(group: list[Assignment]) -> list[list[Assignment]]:
    """同建物クラスタ／pair_withを1ユニットにまとめる。"""
    by_id = {a.patient.chart_id: a for a in group}
    used: set[str] = set()
    units: list[list[Assignment]] = []
    for a in group:
        cid = a.patient.chart_id
        if cid in used:
            continue
        mates = set(building_mates(cid))
        pw = a.patient.pair_with
        if pw:
            mates |= set(building_mates(pw))
            mates.add(pw)
        unit = [by_id[m] for m in mates if m in by_id]
        # 安定順：元の出現順
        order = {x.patient.chart_id: i for i, x in enumerate(group)}
        unit.sort(key=lambda x: order[x.patient.chart_id])
        for u in unit:
            used.add(u.patient.chart_id)
        units.append(unit)
    return units


def optimize_route(group: list[Assignment], doctor: str) -> list[Assignment]:
    if len(group) <= 1:
        return group

    chains = build_visit_units(group)

    def cluster_order(area: str, address: str) -> int:
        order = AREA_CLUSTER_ORDER.get(area, 50)
        if is_mitaka_area(area, address):
            return 900
        if area == "和光" or "和光" in address:
            return 850
        if area == "光が丘":
            return 840
        return order

    chains.sort(key=lambda ch: (cluster_order(ch[0].patient.area, ch[0].patient.address), ch[0].patient.name))

    flat: list[Assignment] = []
    for ch in chains:
        flat.extend(ch)
    return apply_time_window_order(flat, doctor)


def time_window_priority(a: Assignment, doctor: str) -> tuple[int, int]:
    """小さいほど前半。時間帯制約をエリア順より優先する。"""
    cid = a.patient.chart_id
    day = a.day_key

    # -1: 明示的にルート先頭（三鷹でも末尾にしない）
    if cid == "b216":  # 鴇田：一番最初
        return (-1, 0)
    if cid == "b288":  # 水上：花輪の一番最初
        return (-1, 0)
    if cid == "b508":  # 雨谷：9/19先頭（新座）
        return (-1, 0)
    if cid == "b511":  # 小林誠：高松・9/26は田代（石町）の直後
        return (2, 59)
    if cid == "b428":  # 仲里路：S井荻・9/26は小林誠の直後
        return (2, 60)

    if cid == "b138":  # 渡部：土曜14時以降
        return (3, 0)
    if cid == "b421":  # 我妻：14時以降NG
        return (0, 0)
    if cid == "b514":  # 造酒侚子：学4・今井鈴の直後。AM～13:00在宅
        return (2, 81)
    if cid == "b342":  # 三上：10:30-11:30 NG → 11:30以降。和光より前（往復回避）
        return (2, 82)
    if cid == "b328":  # 猪熊：9/14は三上の直後
        return (2, 83)
    if cid == "b285":  # 和田：午前遅め＝ミモザのあと
        return (2, 75)
    if cid == "b513":  # 大橋：高野台・和田の直後
        return (2, 76)
    if cid == "b75":  # 安田：関町は和光の直前（東側）
        return (3, 45)
    if cid == "b510":  # 國峯：西東京泉町・安田の直前
        return (3, 44)
    if cid == "b415":  # 吉田悦子：15時まで
        return (0, 4)
    if cid in {"b042", "b401"}:  # 後藤：14:15-15:15 NG → 午後前半（山本の前）
        return (0, 5)
    if cid == "b506":  # 菅谷：後藤夫妻の直後（FH大泉学園）
        return (0, 6)
    if cid == "b199":  # 大井：9/19は菅谷（FH大泉）の直後
        return (0, 7)
    if cid == "b426":  # 山本雄二朗：土曜16:30以降NG・下保谷の直後
        return (2, 20)
    if cid == "b278":  # 松村：花輪なら10:30以降
        return (1, 5)

    # 0: 14時前必須 / 8/1内の締切優先 / 午後NG帯の手前
    if cid == "b455":  # 熊谷 土曜14:00以降NG
        return (0, 0)
    if cid == "b320" and day in {"8/8(土)", "8/22(土)"}:  # 上東 14:15以降NG
        return (0, 1)
    if cid == "b346":  # 嶋 14:30-15:10 NG → 13時台〜14:20前に終了
        return (0, 2)
    if cid == "b493":  # 宮本 土曜15:00-16:00 NG → 15時前必須
        return (0, 3)
    if cid == "b335":  # 吉岡典照：末尾回避
        return (1, 8)
    if cid == "b301":  # 瓦林：9/19は芳野の直後（高野台）
        return (2, 77)
    if cid == "b484":  # 三原：遠方末尾回避のため中盤
        return (2, 55)

    # 1: 14:00以降開始（13-14 NG）/ 14:00-15:30 窓
    if cid == "b495" and doctor == "鳥越":  # 大内 土曜13-14NG
        return (1, 0)
    if cid == "b482" and doctor == "鳥越":  # 相川 土曜14:00-15:30のみ
        return (1, 5)
    if cid == "b494":  # 杉町 土15-16NG → 前半
        return (1, 2)

    # 3: 15時以降必須（ただし遠方の前）
    if cid in {"b149", "b148"}:  # 平峯 土曜15:00までNG
        return (3, 0)

    # 4: 16:00希望帯（S大泉北は同施設一塊・新井は16時前終了、和泉を末尾）
    if cid == "b404":  # 新井武芳 土16時以降NG → 塊の先頭寄り
        return (2, 70)
    if cid == "b213":
        return (2, 71)
    if cid == "b349":
        return (2, 72)

    # 5: 遠方（三鷹・吉祥寺）は可能な限り末尾
    if is_mitaka_area(a.patient.area, a.patient.address):
        return (5, 0)

    # 2: 通常（エリア順）
    base = AREA_CLUSTER_ORDER.get(a.patient.area, 50)
    if a.patient.area == "和光" or "和光" in (a.patient.address or ""):
        # 和光は後半だが16:30超過しやすいので、16時希望帯の直前へ
        return (3, 50)
    if a.patient.area == "光が丘":
        return (3, 40)
    return (2, base)


def apply_time_window_order(group: list[Assignment], doctor: str) -> list[Assignment]:
    if doctor == "花輪" and len(group) > 1:
        first = [a for a in group if a.patient.chart_id == "b288"]
        kimura = [a for a in group if a.patient.chart_id == "b357"]
        rest = [a for a in group if a.patient.chart_id not in {"b288", "b357"}]
        rest_sorted = sorted(rest, key=lambda a: (time_window_priority(a, doctor), a.patient.name))
        if kimura:
            head = [a for a in rest_sorted if a.patient.area in {"—", ""}]
            tail = [a for a in rest_sorted if a.patient.area not in {"—", ""}]
            return first + head + kimura + tail
        if first:
            return first + rest_sorted
        return rest_sorted
    if doctor != "鳥越" and doctor != "鳥越午前":
        if doctor == "片山" and len(group) > 1:
            return sorted(group, key=lambda a: time_window_priority(a, doctor))
        return group
    if len(group) <= 1:
        return group

    # 同建物／ペアは一塊のままソートキーを共有
    units = build_visit_units(group)

    def unit_key(unit: list[Assignment]) -> tuple[int, int]:
        return min(time_window_priority(a, doctor) for a in unit)

    units.sort(key=unit_key)
    flat: list[Assignment] = []
    for u in units:
        # ユニット内も時間帯優先で並べる（同建物の前〜後）
        flat.extend(sorted(u, key=lambda a: time_window_priority(a, doctor)))
    return flat


def mark_cancelled_visits(assignments: list[Assignment]) -> None:
    for a in assignments:
        key = (a.day_key, a.doctor, a.patient.chart_id)
        if key in CANCELLED_VISIT_KEYS:
            a.cancelled = True
            remark = CANCELLED_VISIT_REMARK.get(key, "キャンセル")
            if remark not in a.remark:
                a.remark = (a.remark + " " + remark).strip()


def hanawa_depart_time(day_key: str) -> time:
    """花輪の出発時刻。9/14は特例10:00（三上NG回避のため前倒し）。通常は10:15。"""
    if day_key == "9/14(月)":
        return time(10, 0)
    return time(10, 15)


def torikoe_depart_time(day_key: str, group: list[Assignment]) -> time:
    """鳥越の出発時刻。9/5・9/19は特例12:30。先頭がキャンセルの日は実訪問に合わせて遅らせる。"""
    if day_key in {"9/5(土)", "9/19(土)"}:
        return time(12, 30)
    if day_key == "8/15(土)" and group and group[0].cancelled:
        return time(13, 30)
    return time(13, 0)


def compute_schedule_times(group: list[Assignment], doctor: str) -> None:
    """ETA計算。花輪で先頭が水上(b288)のときは自宅直行→11:15クリニック再出発。"""
    day_key = group[0].day_key if group else ""
    mitaka_first = (
        doctor == "花輪"
        and group
        and group[0].patient.chart_id == "b288"
        and not group[0].cancelled
    )
    if doctor == "花輪":
        # 水上直行時: 自宅9:20出発→約40分で10:00着想定
        if mitaka_first:
            start = datetime(2026, 8, 1, 9, 20)
        else:
            depart = hanawa_depart_time(day_key)
            start = datetime(2026, 8, 1, depart.hour, depart.minute)
    elif doctor == "片山":
        start = datetime(2026, 8, 1, 13, 15)
    elif doctor == "鳥越午前":
        start = datetime(2026, 8, 1, 10, 0)
    else:
        depart = torikoe_depart_time(day_key, group)
        start = datetime(2026, 8, 1, depart.hour, depart.minute)
    end_limit = datetime(2026, 8, 1, 16, 30) if doctor == "鳥越" else None
    clinic_restart = datetime(2026, 8, 1, 11, 15)

    current = start
    prev_area = None
    for i, a in enumerate(group):
        a.order = i + 1
        if a.cancelled:
            a.eta = "キャンセル"
            continue

        if mitaka_first and i == 1:
            # 2件目以降: フォンターナ琴坂から11:15再出発
            current = clinic_restart
            prev_area = None

        from_clinic = (i == 0 and not mitaka_first) or (mitaka_first and i == 1)
        from_home_mitaka = mitaka_first and i == 0
        mins = travel_minutes(
            prev_area,
            a.patient.area,
            a.patient.address,
            from_clinic=from_clinic or from_home_mitaka,
            doctor=doctor,
            chart_id=a.patient.chart_id,
        )
        current += timedelta(minutes=mins)
        # 平峯夫妻：土曜15:00までNG。8/15はキャンセルが増えると前倒しになるため下限を掛ける
        if a.patient.chart_id in {"b148", "b149"} and day_key.endswith("(土)"):
            ng_until = datetime(2026, 8, 1, 15, 0)
            if current < ng_until:
                current = ng_until
        a.eta = current.strftime("%H:%M頃")
        current += timedelta(minutes=VISIT_MIN)
        prev_area = a.patient.area
        if end_limit and current.time() > end_limit.time() and doctor == "鳥越":
            a.remark = (a.remark + " " if a.remark else "") + "（帰宅16:30目安・超過見込みはドライバーへ注意）"
        if from_home_mitaka:
            mins_note = DEPARTURE_TRAVEL_MIN_BY_ID.get(a.patient.chart_id, 40)
            a.remark = (
                (a.remark + " " if a.remark else "")
                + f"（院長自宅から三鷹直行・出発→約{mins_note}分）"
            )
        elif mitaka_first and i == 1:
            a.remark = (
                (a.remark + " " if a.remark else "")
                + "（11:15クリニック再出発）"
            )
        elif a.patient.chart_id in DEPARTURE_TRAVEL_MIN_BY_ID and i == 0:
            mins_note = DEPARTURE_TRAVEL_MIN_BY_ID[a.patient.chart_id]
            a.remark = (a.remark + " " if a.remark else "") + f"（出発→約{mins_note}分）"
        elif is_mitaka_area(a.patient.area, a.patient.address) and doctor in {"花輪", "片山"}:
            a.remark = (a.remark + " " if a.remark else "") + "（当院→三鷹約40分）"
        elif is_mitaka_area(a.patient.area, a.patient.address) and doctor.startswith("鳥越"):
            a.remark = (a.remark + " " if a.remark else "") + "（自宅→三鷹約25分）"


def assignment_deadline_label(a: Assignment, all_assignments: list[Assignment]) -> str:
    """日別表の期限列。医療2回目は旧期限ではなく新期限を表示する。"""
    p = a.patient
    base = fmt_deadline(p.deadline)
    if p.insurance != "医療":
        return f"**{base}**"
    visits = sorted(
        [x for x in all_assignments if x.patient.chart_id == p.chart_id],
        key=lambda x: DAY_META[x.day_key]["date"],
    )
    if len(visits) >= 2:
        idx = next((i for i, x in enumerate(visits) if x.day_key == a.day_key), 0)
        if idx >= 1:
            first_day = DAY_META[visits[0].day_key]["date"]
            new_dl = first_day + timedelta(days=30)
            return f"**{new_dl.month}/{new_dl.day}**（2回目・更新後）"
        return f"**{base}**（1回目・必達）"
    return f"**{base}**（必達）"


def medical_visit_label(a: Assignment, all_assignments: list[Assignment] | None = None) -> str:
    p = a.patient
    if p.insurance != "医療":
        return ""
    visits = []
    if all_assignments:
        visits = sorted(
            [x for x in all_assignments if x.patient.chart_id == p.chart_id],
            key=lambda x: DAY_META[x.day_key]["date"],
        )
    if p.visit_count >= 2 and visits:
        idx = next((i for i, x in enumerate(visits) if x.day_key == a.day_key), 0)
        if idx == 0:
            return f"医療1回目（期限{fmt_deadline(p.deadline)}前）"
        first = visits[0]
        new_dl = DAY_META[first.day_key]["date"] + timedelta(days=30)
        return f"医療2回目（1回目後の新期限{new_dl.month}/{new_dl.day}に向けた同月延長）"
    return f"医療（期限{fmt_deadline(p.deadline)}前）"


def visit_flags_label(p: Patient) -> str:
    """エリアの代わりに出す確認フラグ（新規・マイナ保険など）。"""
    flags: list[str] = []
    blob = " ".join(
        [
            p.comment or "",
            p.status_note or "",
            p.hope_biko or "",
            " ".join(p.notes),
        ]
    )
    # 8月リスト上の新規は徳山・髙橋朱美のみ（加賀谷は6月開始済みのため新規にしない）
    known_new = {
        "b500", "b499", "b502", "b504", "b505", "b507", "b511", "b512",
        "b508", "b506", "b513", "b510", "b514",
    }  # 徳山・髙橋朱美・飯澤・山﨑・宮脇・片野・小林誠・清水輝男・雨谷・菅谷・大橋・國峯・ミキ
    if p.chart_id in known_new:
        flags.append("新規")
    # マイナ保険（明示リスト＋希望CSV）
    known_myna = {"b474", "b457", "b148", "b370"}  # 高橋一應・今野・平峯順子・大越（壽夫b149は非対応）
    if p.chart_id in known_myna or p.myna:
        flags.append("マイナ保険")
    elif "マイナ" in blob and "未確認" in blob:
        flags.append("マイナ未確認")
    if "資格確認" in blob or "資格証明" in blob:
        flags.append("資格確認")
    if "同意" in (p.hope_biko or "") and "マイナ" in (p.hope_biko or ""):
        if "マイナ保険" not in flags:
            flags.append("マイナ保険")
        if "同意済" not in "".join(flags):
            flags.append("同意済")
    dual_hint = dual_visit_location_hint(p.address or "")
    if dual_hint:
        flags.insert(0, dual_hint)
    return " / ".join(dict.fromkeys(flags)) if flags else "—"


def day_time_ng_label(p: Patient, day_key: str) -> str:
    """その日の時間帯NG／訪問可能枠だけを短く明示（ドライバー向け）。

    形式: 「NG帯｜いつまでに／いつから」または「可能枠｜この枠内」。
    該当なしは「—」。
    """
    meta = DAY_META.get(day_key)
    if not meta:
        return "—"
    dow = meta["dow"]
    cid = p.chart_id

    # 患者×曜日で確定している時間制約（備考全文ではなくこれだけ見せる）
    by_id: dict[str, dict[str, str]] = {
        "b493": {"土": "15:00–16:00 NG｜14:50迄終了"},  # 宮本
        "b346": {"月": "12:00–13:00・14:30–15:10 NG｜14:20迄終了"},  # 嶋
        "b404": {
            "土": "16:00以降 NG｜15:50迄終了",  # 新井武芳（土）
            "月": "14:00以降 NG｜13:50迄終了",
        },
        "b148": {"土": "15:00まで NG｜15時以降可"},  # 平峯
        "b149": {"土": "15:00まで NG｜15時以降可"},
        "b455": {"土": "14:00以降 NG｜13:50迄終了"},  # 熊谷
        "b320": {"土": "14:15以降 NG｜14:05迄終了"},  # 上東（8/8・22）
        "b482": {"土": "14:00–15:30のみ可｜この枠内に訪問"},  # 相川
        "b495": {
            "土": "13:00–14:00 NG｜14時以降開始",  # 大内
            "月": "AM・13:00–15:00 NG｜15時以降",
        },
        "b494": {"土": "15:00–16:00 NG｜14:50迄終了"},  # 杉町
        "b408": {"月": "午後 NG｜午前中に訪問", "土": "午後 NG｜午前中に訪問"},  # 加藤弘子
        "b357": {"月": "11:00以降 NG｜11時前に終了"},  # 木村一久
        "b391": {"月": "10:30以前 NG｜10:30以降開始"},  # 松村
        "b466": {"月": "14:00–15:00 NG｜前後で回避", "土": "14:00–15:00 NG｜前後で回避"},  # 森泉
        "b441": {"月": "12:50–13:50 NG｜14時以降開始"},  # 河村
        "b447": {"月": "16:45–17:25 NG｜16:45前に終了"},  # 孝太郎
        "b414": {"土": "11:30–12:30 NG｜前後で回避"},  # 西野
        "b457": {"土": "11:00–12:00 NG｜前後で回避"},  # 今野
        "b364": {
            "月": "9:00–10:00・13:00–13:30・16:00–16:30 NG",
            "土": "13:00–13:30・16:00–16:30 NG｜枠外で訪問",
        },  # 釜田
        "b489": {"月": "9:30–10:00 NG｜前後で回避"},  # 繁田
        "b396": {"月": "15:30以降 NG｜15:20迄終了"},  # 中村（片山）
        "b184": {"月": "昼前後希望｜12–14時台目安"},  # 杉山
        "b236": {"土": "午後希望｜13時以降"},  # 中川
        "b451": {"土": "12:15以降可（リハ11:15–12:15）｜午後"},  # 高雄
        "b221": {"月": "なるべく早い時間希望｜午前前半"},  # 石橋光喜
        "b251": {"土": "午後早め希望｜13–14時台目安"},  # 池田
        "b349": {"土": "16:00前後希望｜15:40–16:00台"},  # 和泉
        "b213": {"土": "夕方希望｜15時台後半〜"},  # 岡部
        "b505": {"月": "12:10–12:50に往診厳守"},  # 宮脇恭子（8/24）
        "b138": {"土": "14:00以降可｜14時以降開始"},  # 渡部光子
        "b421": {"月": "14:00以降 NG｜13:50迄終了", "土": "14:00以降 NG｜13:50迄終了"},  # 我妻
        "b415": {"土": "15:00まで可｜14:50迄終了"},  # 吉田悦子
        "b042": {"土": "14:15–15:15 NG（リハ）｜前後で回避"},
        "b401": {"土": "14:15–15:15 NG（リハ）｜前後で回避"},
        "b368": {"月": "10:15–10:55 NG（リハ）｜前後で回避"},
        "b353": {"月": "11:30–12:30 NG（訪看）｜前後で回避"},
        "b116": {"月": "12:15–13:15 NG（リハ）｜前後で回避"},
        "b410": {"月": "AM NG・15:30–16:10 NG｜片山・16:10前終了"},
        "b246": {"月": "AM NG・15:30–16:10 NG｜片山・16:10前終了"},
        "b278": {"月": "9:30–10:30 NG（リハ）｜10:30以降", "土": "14:00–15:00 NG（リハ）｜前後で回避"},
        "b342": {"月": "10:30–11:30・14:15–15:15 NG｜11:30以降（入浴帯は午後）"},
        "b426": {"月": "14:30–15:30 NG（ヘルパー）", "土": "16:30以降 NG｜16:20迄終了"},
        "b497": {"土": "12:00–13:00 NG（昼食）｜13時以降"},
        "b498": {"月": "11:15–11:55 NG（リハ）｜前後で回避"},
        "b427": {"月": "9:00–10:00 NG（リハ）｜10時以降"},
        "b285": {"月": "午前遅め希望｜中盤"},
        "b491": {"月": "13:00–13:40 NG｜花輪AMで回避", "土": "12:30–13:30 NG（入浴）｜13:40以降"},
        "b511": {
            "月": "10:30–13:00可｜この枠内",
            "土": "12:30–15:30可｜この枠内",
        },
        "b514": {"月": "AM～13:00在宅｜13:00迄終了"},
    }
    if cid in by_id and dow in by_id[cid]:
        # 上東は8/8・8/22のみ14:15以降NG
        if cid == "b320" and day_key not in {"8/8(土)", "8/22(土)"}:
            return "—"
        return by_id[cid][dow]

    # 長田: 8/1,22,29はSSで16:30迄NG（実質その日は困難だが表示は明確に）
    if cid == "b153":
        if day_key in {"8/1(土)", "8/22(土)", "8/29(土)"}:
            return "16:30迄 NG（SS）｜要確認"
        if dow == "月":
            return "10:15–10:55 NG（リハ）｜前後で回避"
        return "—"

    # フォールバック: コメントから「時刻＋NG/のみ可」だけを短く拾う（曜日断片の雑抽出はしない）
    text = (p.comment or "").replace("\n", " ")
    if not text:
        return "—"
    norm = (
        text.replace("：", ":")
        .replace("～", "–")
        .replace("〜", "–")
        .replace("－", "–")
        .replace("ー", "–")
        .replace("ＮＧ", "NG")
    )
    for i, ch in enumerate("０１２３４５６７８９"):
        norm = norm.replace(ch, str(i))

    # 例: 1500-1600NG / 14:00以降NG / 1400-1530可能
    m = re.search(
        r"((?:\d{1,2}:\d{2}|\d{3,4})(?:\s*[–\-〜～〜~]\s*(?:\d{1,2}:\d{2}|\d{3,4}))?"
        r"[^。]{0,12}(?:NG|のみ可|以降NG|までNG))",
        norm,
    )
    if m:
        frag = re.sub(r"\s+", "", m.group(1))[:32]
        if dow == "土" and "月曜" in norm and "土曜" not in frag:
            return "—"
        return frag + "｜備考参照"
    return "—"


def build_remark(a: Assignment, all_assignments: list[Assignment] | None = None) -> str:
    p = a.patient
    parts: list[str] = []
    if p.area and p.area != "—":
        parts.append(f"{p.area}・{p.name}")
    if p.comment:
        short = p.comment.replace("\n", " ")[:60]
        parts.append(short)
    med = medical_visit_label(a, all_assignments)
    if med:
        parts.append(med)
    if p.notes:
        parts.extend(p.notes)
    if a.remark:
        parts.append(a.remark)
    return "。".join(dict.fromkeys(parts))  # dedupe preserve order


def collect_not_on_list(assigned_ids: set[str]) -> list[dict[str, str]]:
    """希望CSVにいるが日別ルートに載せていない人。"""
    known: dict[str, tuple[str, str]] = {
        "b496": ("終了", "8/14ご逝去のため終了"),
        "b439": ("終了", "7月で終了"),
        "b267": ("終了", "ご逝去"),
        "b339": ("休止", "肺炎入院・枠解除。予定を組まない"),
        "b476": ("入院", "入院のため"),
        "b460": ("入院", "8/27からしばらく入院"),
        "b297": ("終了", "施設入所のため7/22付終了"),
        "b418": ("終了", "施設退去決定・7/31付終了"),
        "b264": ("休止", "8/6入院。期間未定"),
        "b242": ("終了", "施設入所のため終了"),
        "b152": (
            "対象外",
            "プラウドタワー。候補 9/8・11・15・18 の14:30–15:00。"
            "ヤナカ確認中、決定は常勤全体チャット",
        ),
        "b11": ("終了", "終了見込み"),
        "b447": ("除外", "枠解除"),
        "b442": ("終了", "終了"),
        "b450": ("除外", "リスト除外"),
        "b467": ("終了", "往診不要・終了"),
        "b478": ("除外", "リスト除外"),
    }
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    with HOPE_CSV.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            cid = normalize_chart_id(row.get("id") or row.get("ID") or "")
            if not cid or cid in assigned_ids or cid in seen:
                continue
            seen.add(cid)
            name = re.sub(r"\s+", " ", (row.get("氏名") or "").replace("　", " ")).strip()
            name = re.sub(r"\s*休止後の往診\s*", "", name).strip()
            name = re.sub(r"\s*追加\s*$", "", name).strip()
            insurance = (row.get("区分") or "").strip() or "—"
            status = (row.get("状態") or row.get("休止・再開・終了") or "").strip()
            comment = re.sub(r"\s+", " ", (row.get("コメント") or "").replace("\n", " ")).strip()
            biko = re.sub(r"\s+", " ", (row.get("備考") or "").replace("\n", " ")).strip()
            preset = known.get(cid)
            if cid == "b152" or "プラウド" in comment:
                kind = "対象外"
                reason = comment or known["b152"][1]
            elif "終了" in status or "逝去" in status:
                kind = "終了"
                reason = comment or biko or status
            elif "入院" in status:
                kind = "入院"
                reason = comment or biko or status
            elif "休止" in status:
                kind = "休止"
                reason = comment or biko or status
            elif "入院" in comment:
                kind = "入院"
                reason = comment
            elif "往診不要" in comment:
                kind = "終了"
                reason = comment
            elif preset:
                kind, reason = preset
            else:
                kind = "除外"
                reason = comment or biko or "希望CSVにいるがリスト未掲載"
            if preset and (
                reason in {"終了", "休止", "入院", status}
                or len(preset[1]) > len(reason)
            ):
                kind = preset[0]
                reason = preset[1]
                if comment and comment not in reason and comment not in {
                    "終了",
                    "休止",
                    "入院",
                }:
                    reason = f"{reason}。{comment}"
            reason = reason.strip("。")
            extra = OUT_OF_SCOPE_VISIT.get(cid, {})
            rows.append(
                {
                    "id": cid,
                    "name": name or cid,
                    "insurance": insurance,
                    "kind": kind,
                    "reason": reason,
                    "doctor": extra.get("doctor", ""),
                    "slot": extra.get("slot", ""),
                    "eta": extra.get("eta", ""),
                    "how": extra.get("how", ""),
                    "biko": biko,
                }
            )
    order = {"終了": 0, "入院": 1, "休止": 2, "対象外": 3, "除外": 4}
    rows.sort(key=lambda r: (order.get(r["kind"], 9), r["name"]))
    return rows


def generate_markdown(
    assignments: list[Assignment],
    patients: list[Patient] | None = None,
    overrides: dict | None = None,
) -> str:
    overrides = overrides or {}
    by_day: dict[str, list[Assignment]] = defaultdict(list)
    for a in assignments:
        by_day[a.day_key].append(a)

    assigned_ids = {a.patient.chart_id for a in assignments}
    not_on_list = collect_not_on_list(assigned_ids)
    unassigned = []
    if patients:
        for p in patients:
            if p.chart_id not in assigned_ids:
                unassigned.append(p)

    lines: list[str] = []
    lines.append("# 9月往診リスト（2026年）")
    lines.append("")
    lines.append("> 作成日: 2026-08-21 ｜ 9月希望CSV＋最新台帳＋医師・ドライバー希望")
    lines.append("> **v0.19: 2026-09-17 仲里路を9/26鳥越・小林誠の直後へ（S井荻・再開）**")
    lines.append(">")
    lines.append("> **ドライバー:** 9/5・7・28＝宮嶋、9/14・19＝上杉、9/26＝石橋")
    lines.append("")
    lines.append("## 適用ルール（要約）")
    lines.append("")
    lines.append("| 項目 | 内容 |")
    lines.append("|------|------|")
    lines.append("| 希望日の読み方 | CSVの **TRUE = その日はNG**、FALSE = 候補日 |")
    lines.append("| 完了列 | **TRUE = 希望入力済み**、FALSE = 希望未確定・要再確認 |")
    lines.append("| 実施日 | **9/5, 7, 14, 19, 26, 28**（**9/12は往診中止**） |")
    lines.append("| 花輪院長 | 月曜午前（**10:15** 榎本駐車場集合・出発）。実施日 **9/7・14・28**。**今回は人数上限なし** |")
    lines.append("| 片山先生 | **9/7のみ**月曜午後（**13:15** ローソン前お迎え・出発） |")
    lines.append("| 鳥越先生 | **土曜** 9/5・19・26。通常は午後13:00出発（**9/5・9/19は12:30**）。16:30帰宅**目安** |")
    lines.append("| 同住所・同建物 | **可能な限り同日・連続訪問** |")
    lines.append("| 期限 | 介護・自費＝最終実施の2ヶ月後月末／医療＝30日後 |")
    lines.append("| 住所台帳 | 最新の編集用台帳CSVを使用 |")
    lines.append("")
    lines.append("## 医療患者の期限（9月は各1回）")
    lines.append("")
    lines.append("| 氏名 | ID | 期限 | 配置 | 遵守 |")
    lines.append("|------|-----|------|------|------|")
    medical_ids = ["b253", "b491", "b328", "b370", "b474", "b75"]
    by_pid: dict[str, list[Assignment]] = defaultdict(list)
    for a in assignments:
        by_pid[a.patient.chart_id].append(a)
    for cid in medical_ids:
        items = by_pid.get(cid, [])
        if not items:
            continue
        p = items[0].patient
        place = "、".join(f"{x.day_key}{x.doctor}" for x in items)
        dl = parse_deadline(p.deadline)
        first = DAY_META[items[0].day_key]["date"]
        ok = "OK：期限前" if (dl is None or first <= dl) else f"要確認：1回目{first}が期限後"
        lines.append(f"| {p.name} | {cid} | {fmt_deadline(p.deadline)} | {place} | {ok} |")
    lines.append("")
    lines.append("## 要確認・注意事項（要約）")
    lines.append("")
    notes = [
        "**片山は9/7のみ。** 月曜AM NGは9/7片山へ。花輪の人数上限は今回見ない。",
        "**9/12は往診中止。** 当該7名は9/19・26へ振替。後藤夫妻は9/19午後前半（リハ前）。",
        "**宮嶋**は9/5・7・28確定。9/19は上杉（午後）。",
        "**石橋**は希望が5・7・26のみ。5・7は宮嶋セットのため **9/26** を割当。",
        "**新井道男** … 希望どおり **9/28花輪**（期限9/30）。",
        "**石橋由美子** … 期限9/16・月曜13:00-13:40NGのため **9/14花輪AM**。",
        "**大越** … 期限9/16のため **9/7片山**。",
        "**猪熊和明** … 期限9/16。9/7不在のため **9/14花輪・三上の直後**。",
        "**安田哲** … 希望は19・26のみ。期限9/28のため **9/26鳥越**。",
        "**大和紀代子** … 9/26鳥越を **キャンセル（10月初旬へ）**。リストには取り消し線で残す。枠は國峯へ。",
        "**片野妙子** … 8/29キャンセル分を **9/5鳥越の先頭**（東大泉5）。",
        "**9/5・9/19出発** … 鳥越 **12:30** 出発（通常13:00）。9/19は雨谷先頭のため。",
        "**松崎安延** … プラウドタワーは火金の院長休憩往診。月土リスト対象外。"
        "候補は **9/8・11・15・18** の14:30–15:00。ヤナカ確認中、決定は常勤全体チャット。",
        "**ご夫婦同日** … 黒羽、坂本（片山）、後藤、長谷川。",
        "**清水輝男（b512）** … 新規初回。**9/7片山・大越の直後**（和光市白子1丁目4番3号）。",
        "**小林誠（b511）** … 新規・退院1ヶ月。**9/26鳥越・田代の直後**（高松。土12:30–15:30）。",
        "**東村博（b381）** … 再開。**9/26鳥越・吉田と澤味の間**（西大泉4）。",
        "**越智博（b271）** … 再開。**9/28花輪末尾**（大泉町2。"
        "他院訪問11:30帯回避。8/26退院の1ヶ月は9/26のため2日超過）。",
        "**雨谷浩子（b508）** … 新規。**9/19鳥越先頭**（新座市池田3-3-3）。",
        "**菅谷清子（b506）** … 新規。**9/19鳥越・後藤夫妻の直後**（FH大泉学園ハウス108）。",
        "**大橋正美（b513）** … 新規。**9/28花輪・和田の直後**（高野台4-12-12。期限9/29）。",
        "**國峯浩（b510）** … 新規。**9/26鳥越・安田の直前**（そんぽの家S西東京泉町211）。",
        "**造酒侚子（b514）** … 新規。**9/14花輪・今井鈴の直後**（学園町4-8-4。AM～13:00在宅）。",
        "**瓦林裕美（b301）** … 8月入院キャンセル分。**9/19鳥越・芳野の直後**（高野台3）。"
        "野上→久我の順。",
        "**大井静子（b199）** … 9/26別医療機関受診のため **9/19鳥越・菅谷の直後**（学2）。",
        "**仲里路（b428）** … 入院休止後の再開。**9/26鳥越・小林誠の直後**（S井荻）。",
        "**見米和子（b277）** … 9/4クリニック受診（往診リスト対象外）。",
    ]
    for i, n in enumerate(notes, 1):
        lines.append(f"{i}. {n}")
    lines.append("")
    lines.append("## 問題がある方・後調整が必要な方")
    lines.append("")
    lines.append("### A. 期限・希望ピン")
    lines.append("")
    lines.append("| ID | 氏名 | 内容 | 今回の対応 |")
    lines.append("|----|------|------|------------|")
    lines.append("| b253 | 新井道男 | 医療・9/28希望 | **9/28花輪** |")
    lines.append("| b491 | 石橋由美子 | 医療・期限9/16・13:00-13:40NG | **9/14花輪** |")
    lines.append("| b370 | 大越清次郎 | 医療・期限9/16 | **9/7片山** |")
    lines.append("| b328 | 猪熊和明 | 医療・期限9/16・9/7不在 | **9/14花輪・三上の直後** |")
    lines.append("| b75 | 安田哲 | 医療・期限9/28・土のみ | **9/26鳥越** |")
    lines.append("| b474 | 高橋一應 | 医療・期限9/30・マイナは月曜 | **9/14花輪** |")
    lines.append("| b492 | 大和紀代子 | 9/26キャンセル | **10月初旬へ**（9月リストには取り消し線で残す） |")
    lines.append("| b507 | 片野妙子 | 8/29キャンセル分 | **9/5鳥越先頭**（東大泉5）。2026/8/28追加 |")
    lines.append("| b342 | 三上丸子 | 10:30–11:30リハNG | **9/14花輪・11:30以降** |")
    lines.append("| b512 | 清水輝男 | 新規・和光白子1-4-3 | **9/7片山・大越の直後** |")
    lines.append("| b511 | 小林誠 | 新規・高松・土12:30-15:30 | **9/26鳥越・田代の直後** |")
    lines.append("| b381 | 東村博 | 再開・西大泉4 | **9/26鳥越・吉田と澤味の間** |")
    lines.append(
        "| b271 | 越智博 | 再開・大泉町2。退院1ヶ月は9/26 | "
        "**9/28花輪末尾**（他院11:30帯回避・2日超過） |"
    )
    lines.append("| b508 | 雨谷浩子 | 新規・新座池田 | **9/19鳥越先頭（12:30出発）** |")
    lines.append("| b506 | 菅谷清子 | 新規・FH大泉学園108 | **9/19鳥越・後藤夫妻の直後** |")
    lines.append("| b513 | 大橋正美 | 新規・高野台・期限9/29 | **9/28花輪・和田の直後** |")
    lines.append("| b510 | 國峯浩 | 新規・西東京泉町211 | **9/26鳥越・安田の直前** |")
    lines.append("| b514 | 造酒侚子 | 新規・学園町4-8-4・AM～13:00在宅 | **9/14花輪・今井鈴の直後** |")
    lines.append("| b301 | 瓦林裕美 | 8月入院キャンセル・高野台3 | **9/19鳥越・芳野の直後** |")
    lines.append("| b199 | 大井静子 | 9/26別医療機関受診 | **9/19鳥越・菅谷の直後** |")
    lines.append("| b428 | 仲里路 | 入院休止後再開・S井荻 | **9/26鳥越・小林誠の直後** |")
    if unassigned:
        lines.append("")
        lines.append("### D. 割当できなかった方（要手動）")
        lines.append("")
        lines.append("| ID | 氏名 | 区分 | 期限 | 備考 |")
        lines.append("|----|------|------|------|------|")
        for p in unassigned:
            lines.append(
                f"| {p.chart_id} | {p.name} | {p.insurance} | {fmt_deadline(p.deadline)} | "
                f"{' / '.join(p.notes) if p.notes else (p.comment[:40] if p.comment else '')} |"
            )
    lines.append("")

    doctor_slot_label = {
        "花輪": "午前",
        "片山": "午後",
        "鳥越午前": "午前",
        "鳥越": "午後（13:00〜16:30）",
    }
    doctor_depart = {"花輪": "10:15", "片山": "13:15", "鳥越午前": "10:00", "鳥越": "13:00"}

    for dk in DAY_ORDER:
        d = DAY_META[dk]["date"]
        dow = DAY_META[dk]["dow"]
        lines.append("")
        lines.append(f"## {d.month}/{d.day}({dow})")
        lines.append("")
        day_edit = {
            "9/5(土)": "この日の更新: 2026-08-28　出発を12:30に変更（この日のみ特例）。片野妙子（b507）は先頭。鴇田よし子（b373）はキャンセルのまま",
            "9/7(月)": "この日の更新: 2026-09-09　猪熊を片山から外す。清水輝男は大越の直後（白子1-4-3）",
            "9/14(月)": "この日の更新: 2026-09-11　出発10:00（特例）。三上丸子は5番目・11:30以降開始でNG回避",
            "9/19(土)": "この日の更新: 2026-09-15　大井静子を菅谷の直後（5番）に追加。別医療機関受診で9/26から移動",
            "9/26(土)": "この日の更新: 2026-09-17　仲里路を小林誠の直後に追加（S井荻・再開）",
            "9/28(月)": "この日の更新: 2026-09-17　越智博を花輪末尾へ（他院訪問11:30帯回避）。香水との入れ替えではない",
        }.get(dk)
        if day_edit:
            lines.append(f"> **{day_edit}**")
            lines.append("")
        day_items = by_day.get(dk, [])
        # summary sorted by deadline
        lines.append("**この日の往診予定（期限付き）:**")
        lines.append("")
        lines.append("| 氏名 | ID | 区分 | 期限 | 医師 |")
        lines.append("|------|-----|------|------|------|")
        for a in sorted(day_items, key=lambda x: (parse_deadline(x.patient.deadline) or date(2099, 1, 1), x.patient.name)):
            lines.append(
                f"| {a.patient.name} | {a.patient.chart_id} | {a.patient.insurance} | "
                f"{assignment_deadline_label(a, assignments)} | {a.doctor} |"
            )
        lines.append("")

        groups: dict[str, list[Assignment]] = defaultdict(list)
        for a in day_items:
            groups[a.doctor].append(a)

        for doc in DAY_META[dk]["doctors"]:
            group = groups.get(doc, [])
            if not group:
                continue
            group = order_group_with_overrides(group, doc, dk, overrides)
            depart_label = doctor_depart[doc]
            slot_label = doctor_slot_label[doc]
            if doc == "花輪" and dk == "9/14(月)":
                depart_label = "10:00"
            if doc == "鳥越" and dk in {"9/5(土)", "9/19(土)"}:
                depart_label = "12:30"
                slot_label = "午後（12:30〜16:30）"
            if (
                doc == "花輪"
                and group
                and group[0].patient.chart_id == "b288"
                and not group[0].cancelled
            ):
                depart_label = "1件目三鷹直行／2件目以降 11:15クリニック"
            heading_doc = "鳥越" if doc == "鳥越午前" else doc
            lines.append(
                f"### {heading_doc}先生（{slot_label}）｜出発 {depart_label}｜"
                f"件数 {len(group)}｜ドライバー: **{driver_for_day(dk)}**"
            )
            lines.append("")
            lines.append(
                "| 順 | 氏名 | ID | 区分 | 期限 | 住所 | 特記 | 予定時間 | 時間NG | 備考 |"
            )
            lines.append(
                "|---:|------|-----|------|------|------|------|----------|--------|------|"
            )
            for a in group:
                p = a.patient
                visit_addr = format_dual_visit_address(p.address or "") or "（住所未登録）"
                lines.append(
                    f"| {a.order} | {p.name} | {p.chart_id} | {p.insurance} | "
                    f"{assignment_deadline_label(a, assignments)} | "
                    f"{visit_addr} | {visit_flags_label(p)} | {a.eta} | "
                    f"{day_time_ng_label(p, dk)} | "
                    f"{build_remark(a, assignments)} |"
                )
            route = " → ".join(a.patient.area for a in group)
            lines.append("")
            lines.append(f"**動線（エリア順）:** {route}")
            lines.append("")

    # patient summary
    lines.append("")
    lines.append("## 患者別一覧（割当結果）")
    lines.append("")
    lines.append("| 氏名 | ID | 区分 | 期限 | 往診日 | 医師 | 回数 |")
    lines.append("|------|-----|------|------|--------|------|-----:|")
    patient_days: dict[str, list[Assignment]] = defaultdict(list)
    for a in assignments:
        patient_days[a.patient.chart_id].append(a)
    for cid in sorted(patient_days.keys(), key=lambda c: patient_days[c][0].patient.name):
        items = patient_days[cid]
        p = items[0].patient
        days_str = "、".join(
            f"{DAY_META[a.day_key]['date'].month}/{DAY_META[a.day_key]['date'].day}({DAY_META[a.day_key]['dow']})（{a.doctor}）"
            for a in items
        )
        docs = "複数" if len({a.doctor for a in items}) > 1 else items[0].doctor
        lines.append(
            f"| {p.name} | {cid} | {p.insurance} | {fmt_deadline(p.deadline)} | {days_str} | {docs} | {len(items)} |"
        )

    lines.append("")
    lines.append("## 日別件数サマリー")
    lines.append("")
    lines.append("| 日付 | 花輪 | 片山 | 鳥越 | 合計 |")
    lines.append("|------|-----:|-----:|-----:|-----:|")
    total = 0
    for dk in DAY_ORDER:
        d = DAY_META[dk]["date"]
        h = sum(1 for a in by_day[dk] if a.doctor == "花輪")
        k = sum(1 for a in by_day[dk] if a.doctor == "片山")
        t = sum(1 for a in by_day[dk] if a.doctor.startswith("鳥越"))
        s = h + k + t
        total += s
        han = str(h) if h else "—"
        kat = str(k) if k else "—"
        tor = str(t) if t else "—"
        lines.append(f"| {d.month}/{d.day}({DAY_META[dk]['dow']}) | {han} | {kat} | {tor} | {s} |")
    unique_patients = len(patient_days)
    lines.append("")
    lines.append(f"**往診総件数:** {total}件（対象患者 {unique_patients}名）")
    lines.append("")
    lines.append("---")
    lines.append("")
    out_rows = [r for r in not_on_list if r["kind"] == "対象外"]
    pause_rows = [r for r in not_on_list if r["kind"] != "対象外"]
    ledger = load_ledger()
    lines.append("## 対象外（月土ルート外・要往診）")
    lines.append("")
    lines.append("月土の日別リストには載せないが、別枠で往診する方です。")
    lines.append("")
    lines.append("| 氏名 | ID | 区分 | 医師 | 実施枠 | 予定時間 | 特記 | 住所 | 備考 |")
    lines.append("|------|-----|------|------|--------|----------|------|------|------|")
    for row in out_rows:
        addr = (ledger.get(row["id"]) or "").replace("|", "／")
        note = "。".join(
            x for x in (row.get("biko") or "", row["reason"]) if x
        ).replace("|", "／")
        lines.append(
            f"| {row['name']} | {row['id']} | {row['insurance']} | "
            f"{row.get('doctor') or '—'} | {row.get('slot') or '別枠'} | "
            f"{row.get('eta') or '—'} | {row.get('how') or '—'} | "
            f"{addr or '—'} | {note} |"
        )
    if not out_rows:
        lines.append("| — | — | — | — | — | — | — | — | 対象外の往診はありません |")
    lines.append("")
    lines.append("## 休止・中止（リスト非掲載）")
    lines.append("")
    lines.append("希望CSVにいるが、日別ルートに載せていない方です。")
    lines.append("")
    lines.append("| 氏名 | ID | 区分 | 分類 | 理由 |")
    lines.append("|------|-----|------|------|------|")
    for row in pause_rows:
        reason = row["reason"].replace("|", "／")
        lines.append(
            f"| {row['name']} | {row['id']} | {row['insurance']} | {row['kind']} | {reason} |"
        )
    lines.append("")
    lines.append("## 変更履歴")
    lines.append("")
    lines.append("- 2026-08-19: v0.1 9月往診リスト初版。希望CSV・医師枠（花輪7/14/28、片山7のみ、鳥越土4日）・ドライバー希望を反映。")
    lines.append("- 2026-08-19: v0.2 大和紀代子（b492）を9/26鳥越へ掲載。コメントの「姉のご逝去」による誤除外を修正。")
    lines.append("- 2026-08-20: ドライバー確定。9/5・7・28＝宮嶋、9/14・19＝上杉、9/26＝石橋、9/12＝未定。")
    lines.append("- 2026-08-20: v0.3 9/12往診中止。後藤→9/19午前、芳野・高橋侑子→9/19午後、長谷川・大井→9/26。三上丸子は11:30以降。")
    lines.append("- 2026-08-21: 休止・中止タブを追加。リスト非掲載の方と除外理由を一覧表示。")
    lines.append("- 2026-08-21: v0.4 後藤夫妻を9/19午後前半へ（下保谷→大町6）。午前枠を廃止。壽恵美住所は台帳どおり下保谷4-5-19。")
    lines.append("- 2026-08-21: 日付ナビの9/28右に対象外を追加。松崎安延など月土ルート外の要往診を表示。")
    lines.append("- 2026-08-21: v0.6 導線寄せ。9/5西大泉連続、9/14三上→和光末尾、9/26関町を和光直前、9/7片山は東側→西側→和光。川上は台帳住所（三原台）。和田はミモザ後の中盤。")
    lines.append("- 2026-08-25: v0.7 大和紀代子（b492）の9/26鳥越を往診確定。備考の「キャンセル」文言を外しリスト表示を通常往診に戻す。")
    lines.append("- 2026-08-27: v0.8 鴇田よし子（b373）の9/5鳥越をキャンセル。リストには残し取り消し線＋キャンセル表示。")
    lines.append(
        "- 2026-08-28: v0.9 大和紀代子（b492）の9/26鳥越をキャンセル（10月初旬へ）。"
        "リストには残し取り消し線＋キャンセル表示。"
    )
    lines.append(
        "- 2026-08-28: v0.10 片野妙子（b507）を9/5鳥越の先頭に追加（東大泉5。"
        "8/29キャンセル分の移動）。"
    )
    lines.append(
        "- 2026-08-28: v0.11 9/5鳥越の出発を12:30に変更（この日のみ特例。通常は13:00）。"
    )
    lines.append(
        "- 2026-09-03: v0.12 清水てるお（b512）を9/7片山・大越の直後、"
        "小林誠（b511）を9/7花輪先頭、東村博（b381）を9/26吉田と澤味の間、"
        "越智博（b271）を9/28香水の直前（花輪6名・退院1ヶ月は2日超過）に追加。"
        "見米和子は9/4クリニック受診。松崎は9/8・11・15・18候補でヤナカ確認中。"
    )
    lines.append(
        "- 2026-09-03: v0.13 小林誠（b511）を9/7花輪から9/26鳥越・田代みのりの直後へ移動"
        "（土曜12:30–15:30）。9/7花輪は4名に戻す。"
    )
    lines.append(
        "- 2026-09-09: v0.14 雨谷浩子（b508）を9/19先頭（12:30出発）、"
        "菅谷清子（b506）を後藤夫妻の直後、猪熊和明（b328）を9/14花輪・三上の直後、"
        "大橋正美（b513）を9/28和田の直後、國峯浩（b510）を9/26安田の直前へ。"
        "住所は台帳(6)。花輪・鳥越の人数上限は今回見ない。清水は輝男・白子1-4-3。"
    )
    lines.append(
        "- 2026-09-10: v0.15 ミキジュンコ（b514）を9/14花輪・今井鈴の直後に追加"
        "（学園町4-8-4。AM～13:00在宅）。人数上限は見ない。"
    )
    lines.append(
        "- 2026-09-11: v0.16 瓦林裕美（b301）を9/19鳥越・芳野の直後（9番）に追加。"
        "野上→久我の順に変更。9/14花輪は出発10:00（特例）。"
    )
    lines.append(
        "- 2026-09-15: v0.17 大井静子（b199）を9/26鳥越から9/19鳥越・菅谷の直後へ"
        "（別医療機関受診）。"
    )
    lines.append(
        "- 2026-09-17: v0.18 越智博（b271）を9/28花輪の末尾へ"
        "（他院訪問11:30帯との重複回避。香水との入れ替えではない）。"
    )
    lines.append(
        "- 2026-09-17: v0.19 仲里路（b428）を9/26鳥越・小林誠の直後へ"
        "（S井荻・入院休止後の再開。実働11件）。"
    )
    return "\n".join(lines) + "\n"



def export_patient_constraints(patients: list[Patient]) -> None:
    """HTML移動検証用の患者制約スナップショット。"""
    soft_capacity = {
        "花輪": 5,
        "片山": 11,
        "鳥越": 11,
    }
    day_capacity: dict[str, dict[str, int]] = {}
    for (doc, dk), cap in CAPACITY.items():
        day_capacity.setdefault(dk, {})[doc] = cap
    for dk, meta in DAY_META.items():
        day_capacity.setdefault(dk, {})
        for doc in meta["doctors"]:
            day_capacity[dk].setdefault(doc, soft_capacity.get(doc, 11))

    patients_out: dict[str, dict] = {}
    for p in patients:
        patients_out[p.chart_id] = {
            "name": p.name,
            "insurance": p.insurance,
            "deadline": p.deadline,
            "eligible_days": sorted(p.eligible_days, key=lambda d: DAY_ORDER.index(d) if d in DAY_ORDER else 99),
            "doctor_pref": p.doctor_pref,
            "visit_count": p.visit_count,
            "pair_with": p.pair_with,
            "pinned": p.pinned,
        }
    payload = {
        "version": 1,
        "capacity": soft_capacity,
        "day_capacity": day_capacity,
        "doctor_pref_labels": {
            "hanawa": "花輪",
            "katayama": "片山",
            "torikoe": "鳥越",
            "auto": "auto",
        },
        "patients": patients_out,
    }
    CONSTRAINTS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {CONSTRAINTS_PATH} ({len(patients_out)} patients)")


def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _eta_minutes(eta: str) -> int | None:
    m = re.search(r"(\d{1,2}):(\d{2})", eta or "")
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


# 予定時刻が重なってはいけない時間帯（開始〜終了は訪問10分）
TIME_HARD_RULES: dict[tuple[str, str], list[tuple]] = {
    ("b342", "月"): [("ng", "10:30", "11:30"), ("ng", "14:15", "15:15")],
    ("b138", "土"): [("from", "14:00")],
    ("b415", "土"): [("until_end", "15:00")],
    ("b421", "月"): [("until_start", "14:00")],
    ("b421", "土"): [("until_start", "14:00")],
    ("b278", "月"): [("ng", "09:30", "10:30")],
    ("b042", "土"): [("ng", "14:15", "15:15")],
    ("b401", "土"): [("ng", "14:15", "15:15")],
    ("b497", "土"): [("ng", "12:00", "13:00")],
    ("b246", "月"): [("ng", "15:30", "16:10")],
    ("b410", "月"): [("ng", "15:30", "16:10")],
    ("b116", "月"): [("ng", "12:15", "13:15")],
    ("b353", "月"): [("ng", "11:30", "12:30")],
    ("b368", "月"): [("ng", "10:15", "10:55")],
    ("b491", "月"): [("ng", "13:00", "13:40")],
    ("b427", "月"): [("ng", "09:00", "10:00")],
    ("b426", "土"): [("until_end", "16:30")],
    ("b498", "月"): [("ng", "11:15", "11:55")],
    ("b511", "月"): [("from", "10:30"), ("until_end", "13:00")],
    ("b511", "土"): [("from", "12:30"), ("until_end", "15:30")],
    ("b514", "月"): [("until_end", "13:00")],
}


def validate_time_ng(assignments: list[Assignment]) -> list[str]:
    """ETA が時間NGと重なっていないか。"""
    warnings: list[str] = []
    for a in assignments:
        if a.cancelled:
            continue
        start = _eta_minutes(a.eta)
        if start is None:
            continue
        end = start + VISIT_MIN
        dow = DAY_META[a.day_key]["dow"]
        for rule in TIME_HARD_RULES.get((a.patient.chart_id, dow), []):
            kind = rule[0]
            hit = False
            if kind == "ng":
                lo, hi = _hm(rule[1]), _hm(rule[2])
                hit = start < hi and end > lo
            elif kind == "from":
                hit = start < _hm(rule[1])
            elif kind == "until_end":
                hit = end > _hm(rule[1])
            elif kind == "until_start":
                hit = start >= _hm(rule[1])
            else:
                continue
            if hit:
                warnings.append(
                    f"{a.day_key} {a.doctor} {a.patient.name}({a.patient.chart_id}) "
                    f"ETA {a.eta} が時間NG {rule} と重なる"
                )
    return warnings


def validate_medical(assignments: list[Assignment], patients: list[Patient]) -> list[str]:
    warnings: list[str] = []
    by_id = {p.chart_id: p for p in patients}
    grouped: dict[str, list[Assignment]] = defaultdict(list)
    for a in assignments:
        if a.patient.insurance == "医療":
            grouped[a.patient.chart_id].append(a)
    for cid, items in grouped.items():
        p = by_id[cid]
        items = sorted(items, key=lambda x: DAY_META[x.day_key]["date"])
        dl = parse_deadline(p.deadline)
        if not items:
            warnings.append(f"{cid} {p.name}: 未割当")
            continue
        first = DAY_META[items[0].day_key]["date"]
        if dl and first > dl:
            warnings.append(f"{cid} {p.name}: 1回目{first}が期限{dl}後")
        text = (p.comment or "") + (p.status_note or "") + " ".join(p.notes)
        need2 = ("2回" in text) or ("月初" in text) or (p.visit_count >= 2)
        if need2 and len(items) < 2:
            warnings.append(f"{cid} {p.name}: 同月2回必要だが{len(items)}回のみ")
    return warnings


def main() -> None:
    patients = load_patients()
    export_patient_constraints(patients)
    overrides = load_schedule_overrides()
    assignments = assign_patients(patients)
    assignments = apply_route_overrides(assignments, patients, overrides)
    mark_cancelled_visits(assignments)
    md = generate_markdown(assignments, patients, overrides)
    OUTPUT_MD.write_text(md, encoding="utf-8")
    print(f"Wrote {OUTPUT_MD}")
    c = Counter(a.day_key for a in assignments)
    for dk in DAY_ORDER:
        print(dk, c.get(dk, 0))
    assigned_ids = {a.patient.chart_id for a in assignments}
    for p in patients:
        if p.chart_id not in assigned_ids:
            print("UNASSIGNED", p.chart_id, p.name, p.notes)
    for w in validate_medical(assignments, patients):
        print("MEDICAL_WARN", w)
    for w in validate_time_ng(assignments):
        print("TIME_NG_WARN", w)
    # medical summary
    for cid in ["b75", "b253", "b370", "b474", "b491", "b328"]:
        days = [a.day_key for a in assignments if a.patient.chart_id == cid]
        print("MEDICAL", cid, days)


if __name__ == "__main__":
    main()
