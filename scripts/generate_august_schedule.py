# -*- coding: utf-8 -*-
"""8月往診リストを均等配置・ルート最適化付きで生成する。"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common import dual_visit_location_hint, format_dual_visit_address
from visit_cautions import DAY_VISIT_CAUTIONS

ROOT = SCRIPTS.parent
HOPE_CSV = ROOT / "🚙🚕🚗往診周り順👴🏻👴👴🏼suzuki - 8月往診日希望 (1).csv"
LEDGER_CSV = ROOT / "★台帳（訪問）★ 編集用-2026-08-25 - 編集用（介護）.csv"
HISTORY_CSV = ROOT / "raw/3 往診履歴 7ab6c23709254f879aab52376aa63f2d_all.csv"
OUTPUT_MD = ROOT / "exports/8月往診リスト_2026.md"
OVERRIDES_PATH = ROOT / "exports/schedule_overrides.json"
CONSTRAINTS_PATH = ROOT / "exports/patient_constraints.json"

EXCLUDED_IDS = {
    "b428", "b297", "b450", "b467", "b418", "b478", "b264", "b242", "b442",
    "b11",  # 吉田一代：特養入所・終了見込み（CM確認中）
    "b447",  # 髙橋孝太郎：ご逝去（8/31予定キャンセル）
}

# 休止・終了コメントがあっても仮配置する（要確認）
INCLUDE_DESPITE_STATUS = frozenset()

DAY_META = {
    "8/1(土)": {"date": date(2026, 8, 1), "dow": "土", "doctors": ["鳥越"]},
    "8/3(月)": {"date": date(2026, 8, 3), "dow": "月", "doctors": ["花輪", "片山"]},
    "8/8(土)": {"date": date(2026, 8, 8), "dow": "土", "doctors": ["鳥越"]},
    "8/15(土)": {"date": date(2026, 8, 15), "dow": "土", "doctors": ["鳥越"]},
    "8/17(月)": {"date": date(2026, 8, 17), "dow": "月", "doctors": ["花輪", "片山"]},
    "8/22(土)": {"date": date(2026, 8, 22), "dow": "土", "doctors": ["鳥越"]},
    "8/24(月)": {"date": date(2026, 8, 24), "dow": "月", "doctors": ["花輪"]},
    "8/29(土)": {"date": date(2026, 8, 29), "dow": "土", "doctors": ["鳥越"]},
    "8/31(月)": {"date": date(2026, 8, 31), "dow": "月", "doctors": ["花輪"]},
}

DAY_ORDER = list(DAY_META.keys())

# 日付ごとの送迎ドライバー（同日の全医師枠で共通）
DRIVER_BY_DAY: dict[str, str] = {
    "8/1(土)": "荒井",
    "8/3(月)": "荒井",
    "8/8(土)": "石橋",
    "8/15(土)": "宮嶋",
    "8/17(月)": "宮嶋",
    "8/22(土)": "上杉",
    "8/24(月)": "上杉",
    "8/29(土)": "宮嶋",
    "8/31(月)": "上杉",
}


def driver_for_day(day_key: str) -> str:
    name = DRIVER_BY_DAY.get(day_key)
    if not name:
        return "未定"
    return f"{name}さん"


CAPACITY = {
    ("花輪", "8/3(月)"): 5,
    ("花輪", "8/17(月)"): 5,
    ("花輪", "8/24(月)"): 5,
    ("花輪", "8/31(月)"): 7,  # 今回のみ新規・山﨑＋吉澤追加で7名可
    ("片山", "8/3(月)"): 11,
    ("片山", "8/17(月)"): 11,
    ("鳥越", "8/1(土)"): 8,  # 期限必須が多く16:30帰宅を守るため抑制
    ("鳥越", "8/8(土)"): 11,  # 高橋一應＋西勝追加など
    ("鳥越", "8/15(土)"): 8,
    ("鳥越", "8/22(土)"): 10,  # 瓦林追加。帰宅目安は割当制約にしない
    ("鳥越", "8/29(土)"): 12,  # 今回のみ新規・片野追加で12名可
}

# クリニック（東大泉）からのエリア優先順（西→東・近→遠の目安）
AREA_CLUSTER_ORDER = {
    "関町": 10,
    "L谷原": 20,
    "谷原": 20,
    "井草3": 30,
    "S井荻": 35,
    "アリア井草": 40,
    "CW下石": 45,
    "下石": 50,
    "下石神井3": 50,
    "石台1": 55,
    "石台2": 56,
    "石台7": 57,
    "石町2": 58,
    "石町3": 59,
    "上石": 60,
    "FH上石神井": 62,
    "高野台": 65,
    "三原台": 68,
    "南5": 69,
    "南大泉": 69,
    "西3": 70,
    "西5": 72,
    "学1": 75,
    "学2": 76,
    "学3": 77,
    "学4": 78,
    "学5": 79,
    "学6": 80,
    "FH": 82,
    "FH大泉": 82,
    "大町1": 85,
    "大町2": 86,
    "大町3": 87,
    "大町6": 88,
    "大泉町3": 87,
    "S大泉町5": 88,
    "東1": 90,
    "東2": 91,
    "東5": 92,
    "東6": 93,
    "東大泉": 94,
    "土支田": 95,
    "土支田4": 96,
    "和光": 100,
    "光が丘": 105,
    "吉祥寺": 110,  # 三鷹・吉祥寺（当院から約40分）
    "西東京市泉町2-14-13 そんぽの家S西東京泉町317": 115,
}

MITAKA_KEYWORDS = ("三鷹", "吉祥寺", "下連雀")
WAKO_KEYWORDS = ("和光", "埼玉")
CLINIC_TO_MITAKA_MIN = 40
TORIGOE_HOME_TO_MITAKA_MIN = 25  # 鳥越先生自宅（東大泉）出発時の一般的な三鷹見込み
# 患者別：出発地点からの所要（明示指定。鳥越でも25分にしない）
DEPARTURE_TRAVEL_MIN_BY_ID: dict[str, int] = {
    "b216": 40,  # 鴇田榮子（三鷹市下連雀）
    "b288": 40,  # 水上次義（三鷹市下連雀・同棟）
}
CLINIC_TO_WAKO_MIN = 30
DEFAULT_TRAVEL_MIN = 12
VISIT_MIN = 10
FIRST_VISIT_OFFSET_MIN = 20

# ルート上に残し、表ではキャンセル表示（ETA・移動時間に含めない）
CANCELLED_VISIT_KEYS: frozenset[tuple[str, str, str]] = frozenset({
    ("8/15(土)", "鳥越", "b216"),  # 鴇田榮子・終了
    ("8/15(土)", "鳥越", "b492"),  # 大和紀代子・9月へ移動
    ("8/15(土)", "鳥越", "b301"),  # 瓦林裕美・体調不良のため8/22へ
    ("8/22(土)", "鳥越", "b301"),  # 瓦林裕美・入院
    ("8/29(土)", "鳥越", "b507"),  # 片野妙子・9/5へ
})
CANCELLED_VISIT_REMARK: dict[tuple[str, str, str], str] = {
    ("8/15(土)", "鳥越", "b216"): "キャンセル（終了）",
    ("8/15(土)", "鳥越", "b492"): "キャンセル（9月へ移動）",
    ("8/15(土)", "鳥越", "b301"): "キャンセル（体調不良・8/22へ）",
    ("8/22(土)", "鳥越", "b301"): "キャンセル（入院）",
    ("8/29(土)", "鳥越", "b507"): "キャンセル（9/5へ移動）",
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


def load_ledger() -> dict[str, str]:
    out: dict[str, str] = {}
    with LEDGER_CSV.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        try:
            i_id = header.index("ID")
            i_addr = header.index("利用者住所")
        except ValueError:
            # フォールバック（旧DictReader互換）
            f.seek(0)
            for row in csv.DictReader(f):
                cid = (row.get("ID") or "").strip()
                if cid:
                    out[cid] = (row.get("利用者住所") or "").strip()
            return out
        for row in reader:
            if len(row) <= max(i_id, i_addr):
                continue
            cid = (row[i_id] or "").strip()
            if cid:
                out[cid] = (row[i_addr] or "").strip()
    return out


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
    if "和光" in address or address.startswith("埼玉"):
        return "和光"
    if "光が丘" in address:
        return "光が丘"
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
    if "西東京" in address and "泉町" in address:
        return "西東京市泉町2-14-13 そんぽの家S西東京泉町317"
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
    if "南大泉" in address:
        m = re.search(r"南大泉(\d)", address)
        return f"南{m.group(1)}" if m else "南大泉"
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
            cid = (row.get("ID") or "").strip()
            if not cid or cid in EXCLUDED_IDS:
                continue
            status = (row.get("休止・再開・終了") or "") + (row.get("コメント") or "")
            if any(k in status for k in ("終了", "休止", "逝去", "入院中", "往診不要", "キャンセル")):
                if cid not in INCLUDE_DESPITE_STATUS:
                    if any(
                        k in status
                        for k in ("終了", "逝去", "入院中", "往診不要", "キャンセル")
                    ) and cid not in INCLUDE_DESPITE_STATUS:
                        continue

            eligible = set()
            for dk in DAY_ORDER:
                val = (row.get(dk) or "").strip().upper()
                if val == "FALSE":
                    eligible.add(dk)

            # 8/10は実施日外
            comment = (row.get("コメント") or "").strip()
            status_note = (row.get("休止・再開・終了") or "").strip()
            myna_raw = (row.get("マイナ利用") or "").strip().upper()
            p = Patient(
                chart_id=cid,
                name=(row.get("名前") or "").strip(),
                insurance=(row.get("区分") or "").strip(),
                deadline=(row.get("往診期限") or "").strip(),
                comment=comment,
                status_note=status_note,
                eligible_days=eligible,
                address=ledger.get(cid, ""),
                doctor_pref=classify_doctor_pref(comment, row.get("区分") or "", row.get("名前") or ""),
                myna=myna_raw == "TRUE",
                hope_biko=(row.get("備考") or "").strip(),
            )
            p.area = infer_area(cid, p.address, hist_areas)

            # 同建物ペア
            if cid == "b236":
                p.pair_with = "b451"
            if cid == "b451":
                p.pair_with = "b236"
            if cid == "b322":
                p.pair_with = "b452"
            if cid == "b452":
                p.pair_with = "b322"
            if cid == "b149":
                p.pair_with = "b148"
            if cid == "b148":
                p.pair_with = "b149"
            if cid == "b398":
                p.pair_with = "b443"
            if cid == "b443":
                p.pair_with = "b398"
            if cid == "b349":
                p.pair_with = "b213"
            if cid == "b213":
                p.pair_with = "b349"

            patients.append(p)

    # 飯田・新井武芳・相川など CSV上 FALSE が無いが調整対象
    extra_ids = {"b404", "b482", "b495", "b83", "b395", "b406", "b489", "b392", "b399", "b447", "b328", "b364", "b335"}
    for p in patients:
        if p.chart_id in extra_ids and not p.eligible_days:
            # コメントから手動で候補日を付与
            manual = manual_eligible(p)
            if manual:
                p.eligible_days = manual

    append_manual_patients(patients, ledger, hist_areas)
    apply_pins(patients)
    return patients


def append_manual_patients(
    patients: list[Patient],
    ledger: dict[str, str],
    hist_areas: dict[str, str],
) -> None:
    """希望CSV未掲載だが台帳・手動配置がある患者。"""
    by_id = {p.chart_id: p for p in patients}
    specs: list[tuple[str, dict]] = [
        (
            "b501",
            {
                "name": "西勝昭子",
                "insurance": "自費",
                "deadline": "2026-08-31",
                "address": "東京都練馬区南田中5-7-11",
                "eligible_days": {"8/8(土)"},
                "notes": ["8月新規・南田中5-7-11"],
                "doctor_pref": "torikoe",
            },
        ),
        (
            "b502",
            {
                "name": "飯澤和子",
                "insurance": "介護",
                "deadline": "",
                "eligible_days": {"8/29(土)"},
                "notes": ["2026/8/15リスト追加。そんぽの家S土支田505。繁田の直後・土支田塊の前"],
                "doctor_pref": "torikoe",
            },
        ),
        (
            "b504",
            {
                "name": "山﨑百子",
                "insurance": "介護",
                "deadline": "",
                "eligible_days": {"8/31(月)"},
                "notes": ["2026/8/15リスト追加。シェーン泉103。新井と高橋の間（花輪6名・今回限り）"],
                "doctor_pref": "hanawa",
            },
        ),
        (
            "b505",
            {
                "name": "宮脇恭子",
                "insurance": "介護",
                "deadline": "",
                "eligible_days": {"8/24(月)"},
                "notes": ["2026/8/15リスト追加。学園町6-15-2。川井の直後"],
                "doctor_pref": "hanawa",
            },
        ),
        (
            "b507",
            {
                "name": "片野妙子",
                "insurance": "介護",
                "deadline": "",
                "address": "東京都練馬区東大泉5丁目15-2-405",
                "eligible_days": {"8/29(土)"},
                "notes": [],
                "doctor_pref": "torikoe",
            },
        ),
        (
            "b503",
            {
                "name": "吉澤一広",
                "insurance": "介護",
                "deadline": "",
                "address": "練馬区南大泉5-21-46　スターハイム小室106",
                "eligible_days": {"8/31(月)"},
                "notes": [],
                "doctor_pref": "hanawa",
            },
        ),
    ]
    for cid, spec in specs:
        if cid in by_id:
            continue
        addr = spec.get("address") or ledger.get(cid, "")
        p = Patient(
            chart_id=cid,
            name=spec["name"],
            insurance=spec["insurance"],
            deadline=spec.get("deadline", ""),
            comment="",
            status_note="",
            eligible_days=set(spec.get("eligible_days") or []),
            address=addr,
            doctor_pref=str(spec.get("doctor_pref") or "auto"),
        )
        p.area = infer_area(cid, addr, hist_areas)
        p.notes.extend(spec.get("notes") or [])
        patients.append(p)


def manual_eligible(p: Patient) -> set[str]:
    c = p.comment
    if p.chart_id == "b404":  # 新井武芳
        return {"8/3(月)", "8/17(月)", "8/24(月)", "8/31(月)", "8/1(土)", "8/15(土)", "8/22(土)", "8/29(土)"}
    if p.chart_id == "b482":  # 相川玲子
        return {"8/3(月)", "8/17(月)", "8/24(月)", "8/31(月)", "8/22(土)", "8/29(土)"}
    if p.chart_id == "b495":  # 大内英継
        return {"8/15(土)", "8/22(土)", "8/29(土)"}
    if p.chart_id in {"b83", "b395", "b489"}:
        # 希望CSV: 月曜TRUE=NGのため土曜のみ
        return {d for d in DAY_ORDER if DAY_META[d]["dow"] == "土"}
    if p.chart_id == "b406":
        # 月曜すべてNGのため土曜のみ
        return {d for d in DAY_ORDER if DAY_META[d]["dow"] == "土"}
    if p.chart_id == "b392":
        return {"8/3(月)", "8/17(月)", "8/24(月)", "8/31(月)"}
    if p.chart_id == "b399":
        return {"8/3(月)", "8/17(月)", "8/24(月)", "8/31(月)", "8/8(土)", "8/15(土)", "8/22(土)", "8/29(土)"}
    if p.chart_id == "b447":
        return {"8/3(月)", "8/17(月)"}
    if p.chart_id == "b328":
        return {"8/3(月)", "8/17(月)"}
    if p.chart_id == "b364":
        return {"8/3(月)", "8/17(月)", "8/24(月)", "8/31(月)", "8/8(土)", "8/15(土)", "8/22(土)", "8/29(土)"}
    if p.chart_id == "b335" and not p.eligible_days:
        return {d for d in DAY_ORDER if DAY_META[d]["dow"] == "土"}
    return set()


def apply_pins(patients: list[Patient]) -> None:
    by_id = {p.chart_id: p for p in patients}

    # 固定・優先割当
    if "b457" in by_id:  # 今野淳子 8/1のみ
        by_id["b457"].pinned = {"8/1(土)": "鳥越"}
        by_id["b457"].eligible_days = {"8/1(土)"}
    if "b499" in by_id:  # 髙橋朱美：花輪定員5のため8/3片山へ
        by_id["b499"].pinned = {"8/3(月)": "片山"}
        by_id["b499"].eligible_days = {"8/3(月)"}
        by_id["b499"].doctor_pref = "katayama"
        if not by_id["b499"].address:
            by_id["b499"].notes.append("台帳住所なし・要確認")
        else:
            by_id["b499"].notes.append("新規・花輪定員5のため8/3片山（住所は最新台帳反映）")
    if "b417" in by_id:  # 小谷野：花輪定員5のため8/3片山へ
        by_id["b417"].pinned = {"8/3(月)": "片山"}
        by_id["b417"].eligible_days = {"8/3(月)", "8/17(月)"}
        by_id["b417"].doctor_pref = "katayama"
        by_id["b417"].notes.append("花輪定員5のため片山へ")
    if "b75" in by_id:  # 安田哲 医療2回（期限8/3前＋同月2回）
        by_id["b75"].visit_count = 2
        by_id["b75"].pinned = {"8/1(土)": "鳥越", "8/29(土)": "鳥越"}
        by_id["b75"].eligible_days = {"8/1(土)", "8/29(土)"}
        by_id["b75"].notes.append("医療2回：期限前8/1＋同月延長8/29")
    if "b208" in by_id:  # 岩城宏之 期限8/15・関町
        by_id["b208"].pinned = {"8/1(土)": "鳥越"}
        by_id["b208"].eligible_days = {"8/1(土)", "8/8(土)", "8/15(土)"}
        by_id["b208"].doctor_pref = "torikoe"
        by_id["b208"].notes.append("期限8/15。8/1鳥越・関町（安田直後）")
    if "b253" in by_id:  # 新井道男 医療2回（希望: 8/1or8/3 と 8/31。8/17はNG）
        by_id["b253"].visit_count = 2
        by_id["b253"].pinned = {"8/3(月)": "片山", "8/31(月)": "花輪"}
        by_id["b253"].eligible_days = {"8/1(土)", "8/3(月)", "8/31(月)"}
        by_id["b253"].notes.append("医療2回：期限前8/3（片山）＋同月延長8/31（花輪・希望どおり）")
    if "b370" in by_id:  # 大越 期限8/12・同月2回（2回目は8/17片山）
        by_id["b370"].visit_count = 2
        by_id["b370"].pinned = {"8/3(月)": "片山", "8/17(月)": "片山"}
        by_id["b370"].eligible_days = {"8/3(月)", "8/17(月)"}
        by_id["b370"].notes.append("医療2回：期限前8/3＋同月延長8/17（片山・花輪定員5）")
    if "b474" in by_id:  # 高橋一應 期限8/12前8/8＋同月延長8/31花輪
        by_id["b474"].visit_count = 2
        by_id["b474"].pinned = {"8/8(土)": "鳥越", "8/31(月)": "花輪"}
        by_id["b474"].eligible_days = {"8/8(土)", "8/31(月)"}
        by_id["b474"].notes.append("医療2回：期限前8/8＋同月延長8/31")
    if "b328" in by_id:  # 猪熊 医療・期限8/27前（希望未記入）
        by_id["b328"].pinned = {"8/17(月)": "片山"}
        by_id["b328"].eligible_days = {
            d for d in (by_id["b328"].eligible_days or set(DAY_ORDER))
            if DAY_META[d]["date"] <= date(2026, 8, 27)
        }
        by_id["b328"].notes.append("医療1回：期限8/27前の8/17（希望未記入）")
    if "b245" in by_id:  # 桐渕京子 期限8/1・リスケ
        by_id["b245"].pinned = {"8/1(土)": "鳥越"}
        by_id["b245"].eligible_days = {"8/1(土)"}
        by_id["b245"].notes.append("7/19中止リスケ・期限8/1のため必須")
    if "b425" in by_id:  # 小野俊幸 在宅可能性は8/1最高
        by_id["b425"].pinned = {"8/1(土)": "鳥越"}
        by_id["b425"].eligible_days = {"8/1(土)", "8/8(土)"}
        by_id["b425"].notes.append("ドタキャンリスケ・8/1在宅可能性高")
    if "b456" in by_id:  # 中原美奈子 期限8/8・リスケ
        by_id["b456"].pinned = {"8/8(土)": "鳥越"}
        by_id["b456"].eligible_days = {"8/1(土)", "8/3(月)", "8/8(土)"}
        by_id["b456"].notes.append("7/18中止リスケ・期限8/8当日配置")
    if "b500" in by_id:  # 徳山慶子 新規・なるべく早く
        by_id["b500"].pinned = {"8/3(月)": "花輪"}
        by_id["b500"].eligible_days = {"8/1(土)", "8/3(月)"}
        if not by_id["b500"].address:
            by_id["b500"].notes.append("8月新規・なるべく早く（住所要確認）")
        else:
            by_id["b500"].notes.append("8月新規・なるべく早く（住所は最新台帳反映）")
    if "b495" in by_id:  # 大内英継 月曜AM・13-15NG → 土曜（8/22は前半に熊谷・上東あり）
        by_id["b495"].pinned = {"8/22(土)": "鳥越"}
        by_id["b495"].eligible_days = {"8/22(土)", "8/29(土)"}
        by_id["b495"].doctor_pref = "torikoe"
        by_id["b495"].notes.append("月曜AM・13-15NG/土曜13-14NGのため8/22中盤")
    if "b482" in by_id:  # 相川 土曜14:00-15:30のみ
        by_id["b482"].pinned = {"8/22(土)": "鳥越"}
        by_id["b482"].eligible_days = {"8/22(土)", "8/29(土)"}
        by_id["b482"].notes.append("土曜14:00-15:30のみ可")
    if "b494" in by_id:  # 杉町 土15-16NG・月曜NG
        by_id["b494"].eligible_days = {d for d in DAY_ORDER if DAY_META[d]["dow"] == "土"}
        by_id["b494"].doctor_pref = "torikoe"
    if "b445" in by_id:  # 村松：FH大泉 → 8/29クラスター寄り
        by_id["b445"].eligible_days = {"8/15(土)", "8/29(土)"}
        by_id["b445"].pinned = {"8/29(土)": "鳥越"}
        by_id["b445"].notes.append("FH大泉のため同施設と同日寄り")
    if "b216" in by_id:  # 鴇田（三鷹）：8/15は終了キャンセルだが表に残す
        by_id["b216"].pinned = {"8/15(土)": "鳥越"}
        by_id["b216"].eligible_days = {"8/15(土)"}
        by_id["b216"].notes.append("三鷹のためルート先頭（8/15は終了キャンセル）")
    if "b501" in by_id:  # 西勝昭子 8/8鳥越末尾
        by_id["b501"].pinned = {"8/8(土)": "鳥越"}
        by_id["b501"].eligible_days = {"8/8(土)"}
        by_id["b501"].address = "東京都練馬区南田中5-7-11"
        by_id["b501"].area = infer_area("b501", by_id["b501"].address, {})
        by_id["b501"].doctor_pref = "torikoe"
        by_id["b501"].notes.append("8/8鳥越・ルート末尾")
    if "b505" in by_id:  # 宮脇恭子 新規・8/24花輪・川井の直後
        by_id["b505"].pinned = {"8/24(月)": "花輪"}
        by_id["b505"].eligible_days = {"8/24(月)"}
        by_id["b505"].doctor_pref = "hanawa"
        by_id["b505"].notes.append("2026/8/15追加。川井の直後（学園町）")
    if "b502" in by_id:  # 飯澤和子 新規・8/29鳥越・土支田寄せ
        by_id["b502"].pinned = {"8/29(土)": "鳥越"}
        by_id["b502"].eligible_days = {"8/29(土)"}
        by_id["b502"].doctor_pref = "torikoe"
        by_id["b502"].notes.append("2026/8/15追加。繁田の直後・土支田塊の前")
    if "b507" in by_id:  # 片野妙子 新規・8/29鳥越末尾（東大泉5・帰宅寄せ）
        by_id["b507"].pinned = {"8/29(土)": "鳥越"}
        by_id["b507"].eligible_days = {"8/29(土)"}
        by_id["b507"].doctor_pref = "torikoe"
        by_id["b507"].address = "東京都練馬区東大泉5丁目15-2-405"
        by_id["b507"].area = infer_area("b507", by_id["b507"].address, {})
        by_id["b507"].notes.append(
            "2026/8/25追加。土支田のあと末尾。2026-08-28キャンセル・9/5先頭へ"
        )
    if "b503" in by_id:  # 吉澤一広 新規・8/31花輪・嶋の直後（南大泉5）
        by_id["b503"].pinned = {"8/31(月)": "花輪"}
        by_id["b503"].eligible_days = {"8/31(月)"}
        by_id["b503"].doctor_pref = "hanawa"
        by_id["b503"].address = "練馬区南大泉5-21-46　スターハイム小室106"
        by_id["b503"].area = infer_area("b503", by_id["b503"].address, {})
        by_id["b503"].notes.append("2026/8/27追加。嶋の直後・新井の直前（南大泉5・今回限り花輪7名）")
    if "b504" in by_id:  # 山﨑百子 新規・8/31花輪・新井と高橋の間
        by_id["b504"].pinned = {"8/31(月)": "花輪"}
        by_id["b504"].eligible_days = {"8/31(月)"}
        by_id["b504"].doctor_pref = "hanawa"
        by_id["b504"].notes.append("2026/8/15追加。新井と高橋の間（花輪6名・今回限り）")
        by_id["b504"].notes.append(
            "往診時注意: 入口靴箱に鍵。開錠して入室、退室時は施錠"
        )
    if "b392" in by_id:  # 五味：月曜枠が埋まりやすいため月末へ
        by_id["b392"].pinned = {"8/31(月)": "花輪"}
        by_id["b392"].eligible_days = {"8/24(月)", "8/31(月)"}
    if "b395" in by_id:  # 府川：月曜すべてNG → 8/29鳥越（関町・安田と同日）
        by_id["b395"].pinned = {"8/29(土)": "鳥越"}
        by_id["b395"].eligible_days = {d for d in DAY_ORDER if DAY_META[d]["dow"] == "土"}
        by_id["b395"].doctor_pref = "torikoe"
        by_id["b395"].notes.append("希望CSV月曜NGのため8/29鳥越（関町）")
    if "b406" in by_id:  # 渡邊：月曜すべてNG → 8/22鳥越（石台・吉岡直後）
        by_id["b406"].pinned = {"8/22(土)": "鳥越"}
        by_id["b406"].eligible_days = {d for d in DAY_ORDER if DAY_META[d]["dow"] == "土"}
        by_id["b406"].doctor_pref = "torikoe"
        by_id["b406"].notes.append("月曜すべてNGのため8/22鳥越（石台・吉岡直後）")
    if "b491" in by_id:  # 石橋由美子 医療・期限8/26前（8/24枠を渡邊へ譲り8/17片山）
        by_id["b491"].pinned = {"8/17(月)": "片山"}
        by_id["b491"].eligible_days = {
            d for d in (by_id["b491"].eligible_days or set(DAY_ORDER))
            if DAY_META[d]["date"] <= date(2026, 8, 26)
        } or {"8/17(月)"}
        by_id["b491"].doctor_pref = "katayama"
        by_id["b491"].notes.append("医療1回：期限8/26前の8/17片山（13:00-13:40NG回避）")
    if "b441" in by_id:  # 河村：1250-1350NG → 8/17片山の14時以降
        by_id["b441"].pinned = {"8/17(月)": "片山"}
        by_id["b441"].eligible_days = {"8/3(月)", "8/17(月)"}
        by_id["b441"].doctor_pref = "katayama"
        by_id["b441"].notes.append("花輪定員5のため8/17片山へ（1250-1350NGのため14時以降）")
    if "b240" in by_id:  # 希望未記入・土曜末尾回避
        by_id["b240"].pinned = {"8/17(月)": "片山"}
        by_id["b240"].eligible_days = {"8/3(月)", "8/17(月)"}
        by_id["b240"].notes.append("完了=FALSE・希望未記入")
    if "b153" in by_id:  # 長田：8/1,22,29はSSで16:30迄NG → 8/8か8/15のみ
        by_id["b153"].pinned = {"8/15(土)": "鳥越"}
        by_id["b153"].eligible_days = {"8/8(土)", "8/15(土)"}
        by_id["b153"].notes.append("8/1・22・29はSSのため16:30迄NG")
    if "b329" in by_id:  # 岩間：枠調整で8/1（今村と入替）
        by_id["b329"].pinned = {"8/1(土)": "鳥越"}
        by_id["b329"].eligible_days = {"8/1(土)", "8/8(土)", "8/15(土)", "8/22(土)", "8/29(土)"}
        by_id["b329"].doctor_pref = "torikoe"
        by_id["b329"].notes.append("枠調整で8/1鳥越")
    if "b83" in by_id:  # 坂本：月曜すべてNG → 土曜鳥越
        by_id["b83"].pinned = {"8/1(土)": "鳥越"}
        by_id["b83"].eligible_days = {d for d in DAY_ORDER if DAY_META[d]["dow"] == "土"}
        by_id["b83"].doctor_pref = "torikoe"
        by_id["b83"].notes.append("希望CSV月曜NGのため8/1鳥越")
    if "b479" in by_id:  # 今村：8/22へ
        by_id["b479"].pinned = {"8/22(土)": "鳥越"}
        by_id["b479"].eligible_days = {"8/1(土)", "8/15(土)", "8/22(土)", "8/29(土)"}
        by_id["b479"].doctor_pref = "torikoe"
    if "b484" in by_id:  # 三原：片山NG・月曜NG・土曜へ
        by_id["b484"].pinned = {"8/22(土)": "鳥越"}
        by_id["b484"].eligible_days = {"8/22(土)"}
        by_id["b484"].notes.append(
            "往診時注意: 路上駐車せず自宅駐車場へ。スライド柵は開けてよい"
        )
    if "b489" in by_id:  # 繁田
        by_id["b489"].pinned = {"8/29(土)": "鳥越"}
        by_id["b489"].eligible_days = {"8/15(土)", "8/22(土)", "8/29(土)"}
    if "b404" in by_id:  # 新井武芳：土16時以降NG → S大泉北の和泉・岡部と同日8/8
        by_id["b404"].pinned = {"8/8(土)": "鳥越"}
        by_id["b404"].eligible_days = {"8/8(土)", "8/15(土)", "8/22(土)", "8/29(土)"}
        by_id["b404"].notes.append("S大泉北のため和泉・岡部と同日")
        by_id["b404"].pair_with = "b349"
    if "b399" in by_id:  # 岡田：希望未記入 → FH大泉クラスターの8/29へ
        by_id["b399"].pinned = {"8/29(土)": "鳥越"}
        by_id["b399"].eligible_days = {"8/15(土)", "8/22(土)", "8/29(土)"}
        by_id["b399"].notes.append("完了=FALSE・FH大泉のため同施設と同日寄り")
    if "b492" in by_id:  # 大和：8/15へ（西大泉）
        by_id["b492"].pinned = {"8/15(土)": "鳥越"}
        by_id["b492"].eligible_days = {"8/15(土)", "8/8(土)", "8/22(土)", "8/29(土)"}
        by_id["b492"].notes.append("枠調整で8/15へ。2026-08-15キャンセル・9月往診へ移動")
    if "b335" in by_id:  # 吉岡典照：希望は8/8・22・29のみ
        by_id["b335"].pinned = {"8/22(土)": "鳥越"}
        by_id["b335"].eligible_days = {"8/8(土)", "8/22(土)", "8/29(土)"}
        by_id["b335"].doctor_pref = "torikoe"
        by_id["b335"].notes.append("希望CSVで8/1・8/15 NGのため8/22鳥越")
    if "b301" in by_id:  # 瓦林：8/15体調不良 → 8/22。8/22は入院キャンセル
        by_id["b301"].pinned = {"8/15(土)": "鳥越", "8/22(土)": "鳥越"}
        by_id["b301"].eligible_days = {"8/15(土)", "8/22(土)", "8/29(土)"}
        by_id["b301"].doctor_pref = "torikoe"
        by_id["b301"].notes.append(
            "8/22は今村の直後（高野台）。8/15は体調不良で8/22へリスケ。2026-08-21入院キャンセル"
        )
    if "b288" in by_id:  # 水上（三鷹）→ 花輪の一番最初
        by_id["b288"].pinned = {"8/17(月)": "花輪"}
        by_id["b288"].eligible_days = {"8/3(月)", "8/17(月)", "8/24(月)", "8/31(月)"}
        by_id["b288"].doctor_pref = "hanawa"
        by_id["b288"].notes.append("三鷹のため花輪ルート先頭（一番最初）")
    if "b184" in by_id:  # 杉山：昼前後希望 → 8/17片山序盤
        by_id["b184"].pinned = {"8/17(月)": "片山"}
        by_id["b184"].eligible_days = {"8/3(月)", "8/17(月)"}
        by_id["b184"].doctor_pref = "katayama"
        by_id["b184"].notes.append("昼前後希望・花輪負荷軽減で片山へ")
    if "b446" in by_id:  # 滝口：制約薄 → 8/3片山
        by_id["b446"].pinned = {"8/3(月)": "片山"}
        by_id["b446"].eligible_days = {"8/3(月)", "8/17(月)"}
        by_id["b446"].doctor_pref = "katayama"
        by_id["b446"].notes.append("花輪負荷軽減のため片山へ")
    if "b346" in by_id:  # 嶋：8/31花輪（上石ペア直後・午前で昼NG回避）
        by_id["b346"].pinned = {"8/31(月)": "花輪"}
        by_id["b346"].eligible_days = {"8/31(月)"}
        by_id["b346"].doctor_pref = "hanawa"
        by_id["b346"].notes.append("8/31花輪へ移動（上石直後・午前で12:00–13:00 NG回避）")
    if "b364" in by_id:  # 釜田：時間帯NG多い → 土曜中盤
        by_id["b364"].pinned = {"8/29(土)": "鳥越"}
        by_id["b364"].eligible_days = {"8/8(土)", "8/15(土)", "8/29(土)"}
    if "b396" in by_id:  # 中村：月曜はデイ（片山/花輪）
        by_id["b396"].pinned = {"8/3(月)": "片山"}
        by_id["b396"].eligible_days = {"8/3(月)", "8/17(月)", "8/24(月)"}
    if "b414" in by_id:  # 西野：土曜11:30-12:30NGのみ
        by_id["b414"].eligible_days = {"8/8(土)", "8/15(土)", "8/29(土)"}
    if "b376" in by_id:
        by_id["b376"].pinned = {"8/17(月)": "花輪"}
    if "b408" in by_id:
        by_id["b408"].doctor_pref = "hanawa"
        by_id["b408"].pinned = {"8/17(月)": "花輪"}
    if "b144" in by_id:  # 原篤：処方箋・院長希望
        by_id["b144"].doctor_pref = "hanawa"
        by_id["b144"].pinned = {"8/17(月)": "花輪"}
        by_id["b144"].notes.append("処方箋希望のため院長")
    if "b423" in by_id:
        by_id["b423"].pinned = {"8/17(月)": "花輪"}
    if "b493" in by_id:
        by_id["b493"].pinned = {"8/29(土)": "鳥越"}
    if "b420" in by_id:  # 並木 8/10振替→8/8
        by_id["b420"].pinned = {"8/8(土)": "鳥越"}
        by_id["b420"].eligible_days = {"8/8(土)"}
    if "b466" in by_id:
        by_id["b466"].eligible_days = {"8/24(月)", "8/31(月)"}
    if "b396" in by_id:  # 中村智子 area
        by_id["b396"].doctor_pref = "katayama"
        by_id["b396"].area = "谷原翔裕園（月：谷原／土：石町8）"
    # 同建物・同施設ペアは同日に固定
    pair_days = {
        ("b322", "b452"): ("8/8(土)", "鳥越"),   # 海上・山岸（L谷原）
        ("b149", "b148"): ("8/15(土)", "鳥越"),  # 平峯夫妻
        ("b349", "b213"): ("8/8(土)", "鳥越"),   # 和泉・岡部（S大泉北）
        ("b398", "b443"): ("8/8(土)", "鳥越"),  # 寺野夫妻
        ("b236", "b451"): ("8/29(土)", "鳥越"),  # 中川・高雄（齊藤荘）
        ("b500", "b483"): ("8/3(月)", "花輪"),  # 徳山・木村チヱ（FH大泉）
        ("b364", "b493"): ("8/29(土)", "鳥越"),  # 釜田・宮本（FH大泉）
        ("b320", "b380"): ("8/22(土)", "鳥越"),  # 上東・鳥山（S井荻）
        ("b392", "b488"): ("8/31(月)", "花輪"),  # 五味・加賀谷（上石）
    }
    for (a, b), (dk, doc) in pair_days.items():
        for pid in (a, b):
            if pid in by_id:
                by_id[pid].pinned[dk] = doc
                by_id[pid].eligible_days = {dk}
        if a in by_id and b in by_id:
            by_id[a].pair_with = b
            by_id[b].pair_with = a
    # S大泉北：新井武芳も和泉・岡部と同日
    if "b404" in by_id and "b349" in by_id:
        by_id["b404"].pinned = {"8/8(土)": "鳥越"}
        by_id["b404"].eligible_days = {"8/8(土)"}
        by_id["b404"].pair_with = "b349"
    if "b221" in by_id:  # 石橋光喜 月曜AM希望 → 8/3花輪
        by_id["b221"].doctor_pref = "hanawa"
        by_id["b221"].pinned = {"8/3(月)": "花輪"}
    if "b465" in by_id:  # 後藤 土曜NG
        by_id["b465"].doctor_pref = "katayama"
    if "b357" in by_id:  # 木村一久：鳥越NG・月曜11時以降NG → 8/24花輪AM
        by_id["b357"].doctor_pref = "hanawa"
        by_id["b357"].pinned = {"8/24(月)": "花輪"}
        by_id["b357"].notes.append("鳥越NG・月曜11時以降NGのため花輪AM")
    if "b325" in by_id:  # 増田：院長AM限定
        by_id["b325"].doctor_pref = "hanawa"
        by_id["b325"].pinned = {"8/3(月)": "花輪"}
        by_id["b325"].eligible_days = {"8/3(月)", "8/17(月)", "8/24(月)", "8/31(月)"}
    if "b490" in by_id:  # 平岡：月曜PM NG → 花輪のみ
        by_id["b490"].doctor_pref = "hanawa"


def choose_doctor(p: Patient, day_key: str, counts: dict[tuple[str, str], int]) -> str | None:
    if day_key in p.pinned:
        doc = p.pinned[day_key]
        if counts.get((doc, day_key), 0) < CAPACITY.get((doc, day_key), 99):
            return doc
        return None
    dow = DAY_META[day_key]["dow"]
    if dow == "土":
        if counts.get(("鳥越", day_key), 0) < CAPACITY.get(("鳥越", day_key), 11):
            return "鳥越"
        return None
    # 月曜
    if p.doctor_pref == "hanawa":
        if counts.get(("花輪", day_key), 0) < CAPACITY.get(("花輪", day_key), 5):
            return "花輪"
        return None
    if p.doctor_pref == "katayama":
        if day_key in {"8/3(月)", "8/17(月)"} and counts.get(("片山", day_key), 0) < CAPACITY.get(("片山", day_key), 11):
            return "片山"
        if counts.get(("花輪", day_key), 0) < CAPACITY.get(("花輪", day_key), 5):
            return "花輪"
        return None
    if p.doctor_pref == "torikoe":
        return None
    # auto: 月曜は花輪優先、片山枠は8/3・8/17のみ
    if day_key in {"8/3(月)", "8/17(月)"}:
        if counts.get(("花輪", day_key), 0) < CAPACITY.get(("花輪", day_key), 5):
            return "花輪"
        if counts.get(("片山", day_key), 0) < CAPACITY.get(("片山", day_key), 11):
            return "片山"
    if counts.get(("花輪", day_key), 0) < CAPACITY.get(("花輪", day_key), 5):
        return "花輪"
    return None


def day_load_score(counts: dict[tuple[str, str], int], day_key: str) -> int:
    return sum(counts.get((doc, day_key), 0) for doc in DAY_META[day_key]["doctors"])



def load_schedule_overrides() -> dict:
    """HTML手動編集の正本オーバーレイ。routes: {day: {doctor: [chart_id,...]}}"""
    import sys

    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    try:
        from schedule.config import DEFAULT_PERIOD_KEY
        from schedule.sqlite_store import SqliteScheduleRepository

        store = SqliteScheduleRepository()
        if store.has_routes(DEFAULT_PERIOD_KEY):
            doc = store.export_overrides_document(DEFAULT_PERIOD_KEY)
            routes = doc.get("routes") or {}
            if isinstance(routes, dict) and routes:
                print(
                    f"Loaded schedule overrides from db/schedule.sqlite "
                    f"({DEFAULT_PERIOD_KEY}, {len(routes)} days)"
                )
                return doc
    except Exception as e:
        print(f"WARN: schedule DB unavailable, falling back to JSON: {e}")

    if not OVERRIDES_PATH.exists():
        return {}
    try:
        data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARN: failed to load overrides: {e}")
        return {}
    if not isinstance(data, dict):
        return {}
    routes = data.get("routes") or {}
    if not isinstance(routes, dict) or not routes:
        return {}
    print(f"Loaded schedule overrides from {OVERRIDES_PATH.name}")
    return data


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
    from collections import Counter

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
        "b474": 0, "b75": 0, "b245": 0, "b253": 0, "b370": 0, "b457": 0,
        "b425": 1, "b456": 1, "b491": 1, "b328": 1,
        "b322": 2, "b452": 2, "b149": 2, "b148": 2, "b349": 2, "b213": 2,
        "b398": 2, "b443": 2, "b236": 2, "b451": 2,
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
    target_per_day["8/3(月)"] = 11
    target_per_day["8/17(月)"] = 11
    target_per_day["8/31(月)"] = 4

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
            return TORIGOE_HOME_TO_MITAKA_MIN if doctor == "鳥越" else CLINIC_TO_MITAKA_MIN
        if any(k in next_area for k in WAKO_KEYWORDS) or next_area == "和光":
            return CLINIC_TO_WAKO_MIN if doctor != "鳥越" else 20
        return FIRST_VISIT_OFFSET_MIN
    if is_mitaka_area(next_area, next_address):
        return TORIGOE_HOME_TO_MITAKA_MIN if doctor == "鳥越" else CLINIC_TO_MITAKA_MIN
    if prev_area == next_area:
        return 5
    # 近隣エリアの短縮（16:30帰宅・NG余裕のため）
    near = {
        frozenset({"東1", "石台1"}): 12,
        frozenset({"東1", "石台2"}): 12,
        frozenset({"西3", "西5"}): 10,
        frozenset({"西5", "東1"}): 15,
        frozenset({"西3", "東1"}): 15,
        frozenset({"土支田", "東5"}): 12,
        frozenset({"土支田4", "東5"}): 12,
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
    if cid == "b301":  # 瓦林：末尾回避
        return (1, 9)
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
    if doctor != "鳥越" or len(group) <= 1:
        if doctor == "花輪" and len(group) > 1:
            # 水上（三鷹）は明示的に先頭。木村一久は11時前希望でその次〜中盤頭
            first = [a for a in group if a.patient.chart_id == "b288"]
            kimura = [a for a in group if a.patient.chart_id == "b357"]
            rest = [a for a in group if a.patient.chart_id not in {"b288", "b357"}]
            if kimura:
                head = [a for a in rest if a.patient.area in {"—", ""}]
                tail = [a for a in rest if a.patient.area not in {"—", ""}]
                return first + head + kimura + tail
            if first:
                return first + rest
            return group
        if doctor == "片山" and len(group) > 1:
            # 万一片山に残っても先頭優先キーを反映
            return sorted(group, key=lambda a: time_window_priority(a, doctor))
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


def torikoe_depart_time(day_key: str, group: list[Assignment]) -> time:
    """鳥越の出発時刻。先頭がキャンセルの日は実訪問に合わせて遅らせる。"""
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
        start = datetime(2026, 8, 1, 9, 20) if mitaka_first else datetime(2026, 8, 1, 10, 15)
    elif doctor == "片山":
        start = datetime(2026, 8, 1, 13, 15)
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
        elif is_mitaka_area(a.patient.area, a.patient.address) and doctor == "鳥越":
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
    known_new = {"b500", "b499", "b502", "b503", "b504", "b505", "b507"}  # 徳山・髙橋朱美・飯澤・吉澤・山﨑・宮脇・片野
    if p.chart_id in known_new:
        flags.append("新規")
    if p.chart_id == "b504":
        flags.append("鍵（入口靴箱）")
    if p.chart_id == "b484":
        flags.append("駐車は自宅駐車場")
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
        "b491": {"月": "13:00–13:40 NG｜前後で回避"},  # 石橋由美子
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


def generate_markdown(
    assignments: list[Assignment],
    patients: list[Patient] | None = None,
    overrides: dict | None = None,
) -> str:
    overrides = overrides or {}
    by_day: dict[str, list[Assignment]] = defaultdict(list)
    for a in assignments:
        by_day[a.day_key].append(a)

    unassigned = []
    if patients:
        assigned_ids = {a.patient.chart_id for a in assignments}
        for p in patients:
            if p.chart_id not in assigned_ids:
                unassigned.append(p)

    lines: list[str] = []
    lines.append("# 8月往診リスト（2026年）")
    lines.append("")
    lines.append("> 作成日: 2026-07-26 ｜ 希望CSV＋最新台帳＋医療期限是正＋花輪負荷軽減／同建物同日")
    lines.append("> **v3.19: 2026-08-28 片野妙子（b507）の8/29往診をキャンセル（9/5先頭へ）**")
    lines.append(">")
    lines.append("> **ドライバー:** 8/1・3＝荒井、8/8＝石橋、8/15・17・29＝宮嶋、8/22・24・31＝上杉")
    lines.append("")
    lines.append("## 適用ルール（要約）")
    lines.append("")
    lines.append("| 項目 | 内容 |")
    lines.append("|------|------|")
    lines.append("| 希望日の読み方 | CSVの **TRUE = その日はNG**、FALSE = 候補日 |")
    lines.append("| 完了列 | **TRUE = 希望入力済み**、FALSE = 希望未確定・要再確認（割当除外にはしない） |")
    lines.append("| 実施日 | 土曜・月曜のうち **8/10を除く9日**（8/1, 3, 8, 15, 17, 22, 24, 29, 31） |")
    lines.append("| 花輪院長 | 月曜午前（**10:15** 榎本駐車場集合・出発）・**最大5名**（**8/31のみ今回限り7名可**）。**8/10以外の月曜OK**。超過分は片山へ |")
    lines.append("| 片山先生 | **8/3・8/17の月曜午後のみ**（**13:15** ローソン前お迎え・出発）・最大11名 |")
    lines.append("| 鳥越先生 | **土曜すべて**（13:00自宅お迎え〜16:30帰宅**目安**）・最大11名（**8/29のみ今回限り12名可**） ※帰宅時刻はリスト上の注意喚起であり、割当で厳密合わせしない |")
    lines.append("| 同住所・同建物 | **可能な限り同日・連続訪問**（曜日制約で不可の場合は分割） |")
    lines.append("| 期限 | 介護・自費＝最終実施の2ヶ月後月末／医療＝30日後 |")
    lines.append("| 医療の同月2回 | コメントで2回指定、または月初に期限前配置した場合は同月末にもう1回入れて期限を延長 |")
    lines.append("| 移動時間 | **水上・鴇田は出発から約40分**。その他の三鷹は当院→約40分／鳥越自宅→約25分（患者別上書き優先） |")
    lines.append("| 住所台帳 | 最新の編集用台帳CSVを使用（新規の住所反映） |")
    lines.append("")
    lines.append("## 医療患者の期限・同月2回（遵守状況）")
    lines.append("")
    lines.append("| 氏名 | ID | 元期限 | 配置 | 回数 | 遵守 |")
    lines.append("|------|-----|--------|------|-----:|------|")
    medical_rows = [
        ("安田哲", "b75", "8/3", "8/1（1回目）・8/29（2回目）", 2, "OK：期限前＋同月2回"),
        ("新井道男", "b253", "8/5", "8/3片山（1回目）・8/31花輪（2回目）", 2, "OK：期限前＋同月2回／希望どおり8/31"),
        ("大越清次郎", "b370", "8/12", "8/3片山（1回目）・8/17片山（2回目）", 2, "OK：期限前＋同月2回／花輪定員5"),
        ("高橋一應", "b474", "8/12", "8/8（1回目）・8/31（2回目）", 2, "OK：期限前＋同月延長2回"),
        ("石橋由美子", "b491", "8/26", "8/17片山", 1, "OK：期限前1回（8/17片山）"),
        ("猪熊和明", "b328", "8/27", "8/17", 1, "OK：期限前1回（希望未記入）"),
    ]
    for name, cid, dl, place, n, status in medical_rows:
        lines.append(f"| {name} | {cid} | {dl} | {place} | {n} | {status} |")
    lines.append("")
    lines.append("## 花輪→片山への振替（負荷軽減）")
    lines.append("")
    lines.append("| 日付 | 氏名 | ID | 備考 |")
    lines.append("|------|------|-----|------|")
    lines.append("| 8/3 | 滝口敬文 | b446 | 制約が合うため片山へ |")
    lines.append("| 8/3 | 新井道男（1回目） | b253 | 医療1回目を片山へ（2回目は8/31花輪） |")
    lines.append("| 8/3 | 大越清次郎（1回目） | b370 | 医療1回目は片山（2回目も8/17片山） |")
    lines.append("| 8/3 | 髙橋朱美・小谷野 | b499/b417 | 花輪定員5のため片山へ |")
    lines.append("| 8/17 | 杉山弘子 | b184 | 昼前後希望・片山へ |")
    lines.append("| 8/17 | 河村・大越2回目 | b441/b370 | 花輪定員5のため片山へ |")
    lines.append("| 8/31 | 嶋勝秀 | b346 | 8/17片山から移動・上石直後（午前で昼NG回避） |")
    lines.append("| 8/31 | 新井道男（2回目） | b253 | 希望どおり8/31花輪（府川と入替） |")
    lines.append("")
    lines.append("※水上次義（b288）は三鷹のため **8/17花輪の先頭**（自宅直行）。2件目以降は **11:15クリニック再出発**。")
    lines.append("")
    lines.append("## 要確認・注意事項（要約）")
    lines.append("")
    notes = [
        "**医療は期限前に1回目必達。** 2回目は1回目の30日後が新期限（同月延長）。",
        "**新井道男** … 期限8/5前の **8/3片山** ＋ **8/31花輪**（希望どおり。8/17はNG）。",
        "**希望日NG解消** … 府川→8/29、坂本→8/1、渡邊→8/22、吉岡→8/22。石橋→8/17片山、瓦林→8/15。吉田一代は終了見込みで除外。",
        "**大越清次郎** … 期限8/12前の **8/3片山** ＋ **8/17片山**。",
        "**高橋一應** … 期限8/12前の **8/8** ＋同月延長の **8/31花輪**。",
        "**安田哲** … 期限8/3前の **8/1** ＋ **8/29**（コメント指定）。",
        "**桐渕京子（期限8/1）** … 7/19中止リスケ。**8/1必須**。",
        "**中原美奈子（期限8/8）** … **8/8** 配置（8/1から変更）。",
        "**徳山慶子（新規）** … **8/3花輪**（木村チヱと同施設同日）。",
        "**髙橋朱美（新規）** … **8/3片山**（花輪定員5のため）。大泉町6-27-22。",
        "**加賀谷由紀子** … **8/31花輪**（五味文三と上石エリア同日・6月開始済み）。",
        "**花輪定員5** … 超過分は8/3・8/17片山へ。8/24は最大5。**8/31のみ今回限り7名**（山﨑百子・吉澤一広）。",
        "**新規3名（2026-08-15追加）** … 宮脇恭子→8/24花輪（川井の直後）、飯澤和子→8/29鳥越（土支田寄せ）、山﨑百子→8/31花輪（新井と高橋の間）。",
        "**片野妙子（新規・b507）** … **8/29キャンセル**（リストに残し取り消し線）。**9/5鳥越の先頭**へ移動。",
        "**吉澤一広（新規・b503）** … **8/31花輪の4件目**（南大泉5-21-46。嶋の直後・新井の直前）。今回限り7名。",
        "**大和紀代子（b492）** … **8/15キャンセル**（リストに残し取り消し線）。**9月往診へ移動**。",
        "**同建物寄せ** … S大泉北（和泉・岡部・新井武芳）8/8、FH大泉（釜田・宮本・岡田・村松）8/29、上東・鳥山8/22 など。",
        "**水上次義（三鷹）** … **8/17花輪の一番最初**（院長自宅から直行・約40分）。**2件目以降はフォンターナ琴坂から11:15再出発**。",
        "**宮本智子** … 土曜15:00–16:00 NGのため **8/29は15時前** に配置。",
        "**鴇田榮子（三鷹・同棟）** … **8/15鳥越の一番最初**（出発→約40分／月曜NG）。",
        "**8/8 和泉・岡部** … 16:00希望に対し15時台後半。新井武芳は16時前終了。",
    ]
    for i, n in enumerate(notes, 1):
        lines.append(f"{i}. {n}")
    lines.append("")
    lines.append("## 問題がある方・後調整が必要な方・今回寄せきれなかった方")
    lines.append("")
    lines.append("### A. 問題がある方（期限・制約・データ）")
    lines.append("")
    lines.append("| ID | 氏名 | 内容 | 今回の対応 |")
    lines.append("|----|------|------|------------|")
    lines.append("| b253 | 新井道男 | 医療・期限8/5・同月2回指定 | **8/3片山＋8/31花輪**（1回目は期限前） |")
    lines.append("| b370 | 大越清次郎 | 医療・期限8/12・同月2回 | **8/3片山＋8/17片山** |")
    lines.append("| b474 | 高橋一應 | 医療・期限8/12・月初寄り | **8/8＋8/31**（同月延長） |")
    lines.append("| b75 | 安田哲 | 医療・期限8/3・同月2回 | **8/1＋8/29** |")
    lines.append("| b245 | 桐渕京子 | 期限8/1・リスケ | 8/1必須 |")
    lines.append("| b456 | 中原美奈子 | 期限8/8・リスケ | 8/8配置 |")
    lines.append("| b500 | 徳山慶子 | 新規・期限空 | 8/3花輪（木村チヱと同日）。期限確認は別途 |")
    lines.append("| b499 | 髙橋朱美 | 新規 | **8/3片山**（花輪定員5） |")
    lines.append("| b488 | 加賀谷由紀子 | 期限9/7（6月開始） | **8/31花輪**（五味と上石同日） |")
    lines.append("| b505 | 宮脇恭子 | 新規・期限空 | **8/24花輪**（川井の直後）。2026/8/15追加 |")
    lines.append("| b502 | 飯澤和子 | 新規・期限空 | **8/29鳥越**（繁田の直後・土支田塊の前）。2026/8/15追加 |")
    lines.append("| b504 | 山﨑百子 | 新規・期限空 | **8/31花輪**（新井と高橋の間・今回6名）。2026/8/15追加 |")
    lines.append("| b507 | 片野妙子 | 8/29キャンセル | **9/5鳥越先頭へ**（8月リストには取り消し線で残す） |")
    lines.append("| b503 | 吉澤一広 | 新規・期限空 | **8/31花輪4件目**（南大泉5。嶋の直後）。2026/8/27追加 |")
    lines.append("")
    lines.append("### 最新台帳で住所が判明した方")
    lines.append("")
    lines.append("| ID | 氏名 | 住所（最新台帳） | ルート上の扱い |")
    lines.append("|----|------|------------------|---------------|")
    lines.append("| b499 | 髙橋朱美 | 練馬区大泉町6-27-22 | 8/3片山・大町6 |")
    lines.append("| b500 | 徳山慶子 | FH大泉学園ハウス305 | 8/3花輪・木村チヱと同日 |")
    lines.append(
        "| b488 | 加賀谷由紀子 | 練馬区上石神井2-22-27そんぽの家上石神井215 | "
        "8/31花輪・五味(上石南町)と同日 |"
    )
    lines.append("| b505 | 宮脇恭子 | 練馬区大泉学園町6-15-2 | 8/24花輪・川井（学4）の直後 |")
    lines.append("| b502 | 飯澤和子 | 練馬区土支田2-21-3　そんぽの家S土支田505号室 | 8/29鳥越・土支田寄せ |")
    lines.append("| b504 | 山﨑百子 | 練馬区大泉学園町3-17-49　シェーン泉 103 | 8/31花輪・新井と高橋の間 |")
    lines.append("| b507 | 片野妙子 | 東京都練馬区東大泉5丁目15-2-405 | 8/29キャンセル・9/5先頭へ |")
    lines.append("| b503 | 吉澤一広 | 練馬区南大泉5-21-46　スターハイム小室106 | 8/31花輪4件目（嶋の直後） |")
    lines.append("")
    lines.append("### B. 後々調整が必要そうな方")
    lines.append("")
    lines.append("| ID | 氏名 | 内容 | 次アクション |")
    lines.append("|----|------|------|--------------|")
    lines.append("| b240 | 山本英喜 | 完了=FALSE・希望日/コメント空 | 希望日の確認連絡 |")
    lines.append("| b399 | 岡田貞子 | 完了=FALSE・希望日/コメント空 | 希望日の確認連絡（FH大泉寄せで8/29配置済） |")
    lines.append("| b328 | 猪熊和明 | 医療・完了=FALSE・希望未記入 | 8/17配置済み。本人希望の確認 |")
    lines.append("| b431 | 堀川京子 | 土曜NG。月曜DS空き待ち | DS確定後に再確認 |")
    lines.append("| b493 | 宮本智子 | 土曜15:00–16:00 NG／資格確認書切替 | **8/29は15時前配置**。連絡後に資格確認 |")
    lines.append("| b457 | 今野淳子 | 8/3入院予定。8/1のみ可 | 8/1後は休止管理 |")
    lines.append("| b492 | 大和紀代子 | 8/15キャンセル | **9月往診へ移動**（8月リストには取り消し線で残す） |")
    lines.append(
        "| b11 | 吉田一代 | 特養入所・終了の可能性大（CM確認中） | "
        "**8月リストから除外**（確定したら削除のまま） |"
    )
    lines.append("")
    lines.append("### C. 今回の調整で寄せきれなかった／注意が残る制約")
    lines.append("")
    lines.append("| ID | 氏名 | 残る課題 |")
    lines.append("|----|------|----------|")
    lines.append("| b349 / b213 | 和泉・岡部 | 16:00希望に対し15時台後半〜16時台になりやすい |")
    lines.append("| b245 | 桐渕京子 | 8/1最終付近。遅延に弱い |")
    lines.append("| b465 / b469 | 後藤・萱槇（CW下石） | 後藤は月曜のみ／萱槇は土曜のみのため同日不可 |")
    lines.append("| b391 / b320・b380 | 松村と上東・鳥山（S井荻） | 松村は月曜のみ／上東・鳥山は土曜のみのため同日不可 |")
    lines.append("| FH大泉全体 | 今野・杉町・木村一久など | 曜日・時間制約のため全日寄せは不可（徳山＋木村チヱ／8/29クラスタに分割） |")
    lines.append("| b357 | 木村一久 | 月曜11:00以降NG → 10台確認 |")
    lines.append("| — | 時間帯NG全般 | ETAは目安。当日微調整前提 |")
    if unassigned:
        lines.append("")
        lines.append("### D. 割当できなかった方（要手動）")
        lines.append("")
        lines.append("| ID | 氏名 | 区分 | 期限 | 備考 |")
        lines.append("|----|------|------|------|------|")
        for p in unassigned:
            lines.append(
                f"| {p.chart_id} | {p.name} | {p.insurance} | {fmt_deadline(p.deadline)} | "
                f"{' / '.join(p.notes) if p.notes else p.comment[:40]} |"
            )
    lines.append("")
    lines.append("## 対象外（往診リストから除外）")
    lines.append("")
    lines.append("| ID | 氏名 | 理由 |")
    lines.append("|----|------|------|")
    excluded = [
        ("b428", "仲里路", "入院・休止中"),
        ("b297", "八尋洋子", "7/22終了"),
        ("b450", "白井みおり", "ご逝去"),
        ("b467", "新濵善二郎", "7月終了予定・往診不要"),
        ("b418", "加藤隆行", "入院・休止中"),
        ("b478", "土屋一子", "終了"),
        ("b264", "阿部貞子", "休止中"),
        ("b242", "谷崎英一", "キャンセル方向（入院経過）"),
        ("b442", "飯田千徳", "終了のため除外"),
        ("b447", "髙橋孝太郎", "ご逝去（8/31予定キャンセル）"),
    ]
    for cid, name, reason in excluded:
        lines.append(f"| {cid} | {name} | {reason} |")

    doctor_slot_label = {
        "花輪": "午前",
        "片山": "午後",
        "鳥越": "午後（13:00〜16:30）",
    }
    doctor_depart = {"花輪": "10:15", "片山": "13:15", "鳥越": "13:00"}

    for dk in DAY_ORDER:
        d = DAY_META[dk]["date"]
        dow = DAY_META[dk]["dow"]
        lines.append("")
        lines.append(f"## {d.month}/{d.day}({dow})")
        lines.append("")
        day_edit = {
            "8/15(土)": "この日の更新: 2026-08-15　大和紀代子（b492）をキャンセル（9月へ）。瓦林裕美（b301）を体調不良でキャンセル（8/22へ）。鴇田榮子は終了キャンセルのまま",
            "8/22(土)": "この日の更新: 2026-08-21　瓦林裕美（b301）を入院のためキャンセル（リストに残し取り消し線）",
            "8/24(月)": "この日の更新: 2026-08-15　新規・宮脇恭子（b505）を川井の直後に追加",
            "8/29(土)": "この日の更新: 2026-08-28　片野妙子（b507）をキャンセル（9/5先頭へ。リストに残し取り消し線）",
            "8/31(月)": "この日の更新: 2026-08-27　新規・吉澤一広（b503）を嶋の直後（4件目）に追加（南大泉5・今回7名）",
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
            cap = CAPACITY.get((doc, dk), 0)
            depart_label = doctor_depart[doc]
            if doc == "鳥越" and dk == "8/15(土)" and group and group[0].cancelled:
                depart_label = "13:30"
            if (
                doc == "花輪"
                and group
                and group[0].patient.chart_id == "b288"
                and not group[0].cancelled
            ):
                depart_label = "1件目三鷹直行／2件目以降 11:15クリニック"
            lines.append(
                f"### {doc}先生（{doctor_slot_label[doc]}）｜出発 {depart_label}｜"
                f"定員 {len(group)}/{cap}｜ドライバー: **{driver_for_day(dk)}**"
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
        for caution in DAY_VISIT_CAUTIONS.get(dk, []):
            lines.append(
                f"**往診時の注意点（{caution['name']} {caution['id']}）:** "
                f"{caution['title']}。{caution['body']}"
            )
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
        t = sum(1 for a in by_day[dk] if a.doctor == "鳥越")
        s = h + k + t
        total += s
        han = str(h) if h else "—"
        kat = str(k) if k else "—"
        tor = str(t) if t else "—"
        lines.append(f"| {d.month}/{d.day}({DAY_META[dk]['dow']}) | {han} | {kat} | {tor} | {s} |")
    unique_patients = len(patient_days)
    lines.append("")
    lines.append(f"**往診総件数:** {total}件（対象患者 {unique_patients}名 ＋ 医療の2回往診分）")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 変更履歴")
    lines.append("")
    lines.append("- 2026-07-23: 初版作成（ドライバー未割当）")
    lines.append("- 2026-07-23: 各日別リストに期限列を追加")
    lines.append("- 2026-07-23: 各日見出し下に期限付きサマリーを追加、期限表記を8/31形式に統一")
    lines.append("- 2026-07-23: v2 月全体への均等配置・ルート最適化（三鷹40分見込み）")
    lines.append("- 2026-07-26: v3 希望CSV更新版反映（高橋一應8/8是正、リスケ・新規追加、問題報告拡充）")
    lines.append("- 2026-07-26: v3.1 最新編集用台帳の住所反映（髙橋朱美・徳山慶子）、ルート再計算")
    lines.append("- 2026-07-26: v3.2 医療の期限前必達・同月2回を強制（大越・高橋一應の2回目追加、表示を更新期限に変更）")
    lines.append("- 2026-07-26: v3.3 花輪→片山振替（滝口・新井1回目・飯田・水上・杉山）、同建物同日寄せ（S大泉北・FH大泉・S井荻等）")
    lines.append("- 2026-07-26: v3.4 水上を8/17花輪先頭・鴇田を8/15鳥越先頭へ（三鷹を末尾にしない指定）")
    lines.append("- 2026-07-26: v3.5 水上・鴇田は出発から40分でETA計算（鳥越25分ルールの例外）")
    lines.append("- 2026-07-26: v3.6 8月ドライバー割当（荒井・石橋・宮嶋・上杉）")
    lines.append("- 2026-07-27: v3.9 NG時間余裕（宮本15時前等）・水上は自宅直行＋11:15クリニック再出発")
    lines.append("- 2026-07-27: v3.10 平峯16:30帰宅のため瓦林を8/15→8/29（池田の後・高野台）へ移動")
    lines.append("- 2026-07-27: v3.8 花輪定員5・片山11（案A）。8/3・8/17へ振替、医療2回目を8/17片山へ")
    lines.append("- 2026-07-27: v3.7 HTML手動並び替え・別日移動を schedule_overrides.json で維持")
    lines.append(
        "- 2026-08-15: v3.11 新規3名を8月リストへ追加。"
        "宮脇恭子（b505）→8/24花輪・川井の直後、"
        "飯澤和子（b502）→8/29鳥越・繁田の直後（土支田寄せ）、"
        "山﨑百子（b504）→8/31花輪・新井と高橋の間（今回限り花輪6名）。"
        "台帳は編集用（介護）(3).csv"
    )
    lines.append(
        "- 2026-08-15: v3.12 大和紀代子（b492）の8/15往診をキャンセル（9月へ移動）。"
        "リストには鴇田榮子と同様に残し取り消し線＋キャンセル表示。"
    )
    lines.append(
        "- 2026-08-15: v3.13 瓦林裕美（b301）の8/15往診を体調不良でキャンセルし、"
        "8/22鳥越・今村弘之（高野台4）の直後へリスケ。8/15リストにはキャンセル表示で残す。"
    )
    lines.append(
        "- 2026-08-21: v3.14 瓦林裕美（b301）の8/22往診を入院のためキャンセル。"
        "リストには取り消し線＋キャンセル表示で残す。"
    )
    lines.append(
        "- 2026-08-21: v3.15 山﨑百子（b504）の8/31往診時注意（自宅入口の靴箱に鍵）を"
        "リストと印刷に追加。"
    )
    lines.append(
        "- 2026-08-21: v3.16 三原千砂子（b484）の8/22往診時注意（路上ではなく自宅駐車場。"
        "スライド式の柵は開けてよい）をリストと印刷（一括・個別）に追加。"
    )
    lines.append(
        "- 2026-08-25: v3.17 片野妙子（b507）を8/29鳥越の末尾に追加（東大泉5丁目15-2-405。"
        "土支田のあと・鳥越自宅へ帰宅。今回限り12名）。"
    )
    lines.append(
        "- 2026-08-27: v3.18 吉澤一広（b503）を8/31花輪の4件目に追加（南大泉5-21-46。"
        "嶋の直後・新井の直前。今回限り7名）。"
    )
    lines.append(
        "- 2026-08-28: v3.19 片野妙子（b507）の8/29鳥越をキャンセル（9/5先頭へ）。"
        "リストには残し取り消し線＋キャンセル表示。"
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
    from collections import Counter
    c = Counter(a.day_key for a in assignments)
    for dk in DAY_ORDER:
        print(dk, c.get(dk, 0))
    assigned_ids = {a.patient.chart_id for a in assignments}
    for p in patients:
        if p.chart_id not in assigned_ids:
            print("UNASSIGNED", p.chart_id, p.name, p.notes)
    for w in validate_medical(assignments, patients):
        print("MEDICAL_WARN", w)
    # medical summary
    for cid in ["b75", "b253", "b370", "b474", "b491", "b328"]:
        days = [a.day_key for a in assignments if a.patient.chart_id == cid]
        print("MEDICAL", cid, days)


if __name__ == "__main__":
    main()
