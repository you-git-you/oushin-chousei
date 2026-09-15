#!/usr/bin/env python3
"""8月往診リスト Markdown → 単一HTML（コピー用TSV付き）"""

from __future__ import annotations

import csv
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common import address_for_visit_day
from visit_cautions import DAY_VISIT_CAUTIONS


def render_day_cautions(day_key: str) -> str:
    items = DAY_VISIT_CAUTIONS.get(day_key) or []
    if not items:
        return ""
    blocks = []
    for c in items:
        img = ""
        if c.get("image"):
            img = (
                f'<img class="visit-caution-img" src="{html.escape(c["image"])}" '
                f'alt="{html.escape(c["title"])}">'
            )
        blocks.append(
            f"""
        <aside class="visit-caution" data-patient-id="{html.escape(c['id'])}">
          <h3>往診時の注意点｜{html.escape(c['name'])}（{html.escape(c['id'])}）</h3>
          <p class="visit-caution-title">{html.escape(c['title'])}</p>
          <p>{html.escape(c['body'])}</p>
          {img}
        </aside>"""
        )
    return "".join(blocks)

ROOT = SCRIPTS.parent
MD_PATH = ROOT / "exports/8月往診リスト_2026.md"
OUT_PATH = ROOT / "exports/8月往診リスト_2026.html"
CONSTRAINTS_PATH = ROOT / "exports/patient_constraints.json"
OVERRIDES_PATH = ROOT / "exports/schedule_overrides.json"
HOPE_CSV = ROOT / "🚙🚕🚗往診周り順👴🏻👴👴🏼suzuki - 8月往診日希望 (1).csv"
LEDGER_CSV = ROOT / "★台帳（訪問）★ 編集用-2026-08-25 - 編集用（介護）.csv"

DAY_RE = re.compile(r"^## (8/\d+\([月土]\))$")
DOC_RE = re.compile(r"^### (花輪|片山)先生|### 鳥越先生")
ROUTE_RE = re.compile(r"^\*\*動線（エリア順）:\*\* (.+)$")


def strip_md_bold(s: str) -> str:
    return re.sub(r"\*\*([^*]+)\*\*", r"\1", s).strip()


def format_updated_at_jst(dt: datetime) -> str:
    jst = dt.astimezone(ZoneInfo("Asia/Tokyo"))
    return f"{jst.year}/{jst.month}/{jst.day} {jst.hour:02d}:{jst.minute:02d}"


def load_last_updated_at() -> tuple[str, str]:
    """Return (ISO UTC, JST label) from schedule_overrides or MD mtime."""
    raw: str | None = None
    if OVERRIDES_PATH.exists():
        try:
            doc = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
            if isinstance(doc.get("updated_at"), str):
                raw = doc["updated_at"]
        except (json.JSONDecodeError, OSError):
            pass
    if raw:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    else:
        dt = datetime.fromtimestamp(MD_PATH.stat().st_mtime, tz=timezone.utc)
    return dt.isoformat(), format_updated_at_jst(dt)


def parse_table_row(line: str) -> list[str] | None:
    line = line.strip()
    if not line.startswith("|") or line.startswith("|--") or line.startswith("|---"):
        return None
    parts = [strip_md_bold(p.strip()) for p in line.strip("|").split("|")]
    return parts


def normalize_md_lines(text: str) -> list[str]:
    """表セル内の改行（次行が | で始まらない続き）を1行にまとめる。"""
    raw = text.splitlines()
    out: list[str] = []
    for line in raw:
        if (
            out
            and out[-1].strip().startswith("|")
            and line.strip()
            and not line.strip().startswith("|")
            and not line.startswith("#")
            and not line.startswith("**")
        ):
            out[-1] = out[-1].rstrip() + " " + line.strip()
        else:
            out.append(line)
    return out


def parse_md(text: str) -> dict:
    lines = normalize_md_lines(text)
    meta = {"title": "8月往診リスト（2026年）", "subtitle": "", "version": ""}
    if lines and lines[0].startswith("# "):
        meta["title"] = lines[0][2:].strip()
    for line in lines[:8]:
        if line.startswith("> **v"):
            meta["version"] = strip_md_bold(line.lstrip("> ").strip())
        if "作成日" in line and line.startswith(">"):
            meta["subtitle"] = line.lstrip("> ").strip()

    summary_rows: list[list[str]] = []
    patient_rows: list[list[str]] = []
    changelog: list[str] = []
    days: list[dict] = []

    in_summary = False
    in_patients = False
    in_changelog = False
    cur_day: dict | None = None
    cur_doc: dict | None = None

    for i, raw in enumerate(lines):
        line = raw.rstrip()
        if line == "## 変更履歴":
            in_changelog = True
            in_summary = False
            in_patients = False
            continue
        if in_changelog:
            if line.startswith("## "):
                in_changelog = False
            elif line.startswith("- "):
                changelog.append(line[2:].strip())
                continue
            else:
                continue
        if line == "## 日別件数サマリー":
            in_summary = True
            in_patients = False
            continue
        if line == "## 患者別一覧（割当結果）":
            in_patients = True
            in_summary = False
            continue
        if in_summary and line.startswith("## ") and "日別" not in line:
            in_summary = False
        if in_patients and line.startswith("## ") and "患者別" not in line:
            in_patients = False

        if in_summary:
            row = parse_table_row(line)
            if row and row[0].startswith("8/"):
                summary_rows.append(row)

        if in_patients:
            row = parse_table_row(line)
            if row and len(row) >= 6 and row[1].startswith("b"):
                patient_rows.append(row)

        m = DAY_RE.match(line)
        if m:
            cur_day = {
                "key": m.group(1),
                "summary": [],
                "doctors": [],
                "route": "",
                "edit_note": "",
            }
            days.append(cur_day)
            cur_doc = None
            continue

        if cur_day and line.startswith(">") and "この日の更新" in line:
            cur_day["edit_note"] = strip_md_bold(line.lstrip("> ").strip())
            continue

        if cur_day and line.startswith("**この日の往診予定"):
            continue

        if cur_day and not cur_doc:
            row = parse_table_row(line)
            if row and len(row) == 5 and row[1].startswith("b"):
                cur_day["summary"].append(
                    {"name": row[0], "id": row[1], "type": row[2], "deadline": row[3], "doctor": row[4]}
                )

        dm = DOC_RE.match(line)
        if dm and cur_day:
            doc_name = "鳥越" if "鳥越" in line else dm.group(1)
            cur_doc = {"name": doc_name, "header": line.replace("### ", ""), "visits": []}
            cur_day["doctors"].append(cur_doc)
            continue

        if cur_day and cur_doc:
            row = parse_table_row(line)
            if row and len(row) >= 9 and row[0].isdigit():
                if len(row) >= 10:
                    flags, eta, time_ng, note = row[6], row[7], row[8], row[9]
                else:
                    # 旧形式: … エリア 予定 備考
                    flags, eta, time_ng, note = "—", row[6], "—", row[7] if len(row) > 7 else ""
                    if len(row) >= 9:
                        flags, eta, time_ng, note = row[6], row[7], "—", row[8]
                cancelled = (eta or "").strip() == "キャンセル" or (eta or "").strip().startswith("キャンセル（")
                cur_doc["visits"].append(
                    {
                        "order": row[0],
                        "name": row[1],
                        "id": row[2],
                        "type": row[3],
                        "deadline": row[4],
                        "address": row[5].replace("\n", " "),
                        "flags": flags,
                        "eta": eta,
                        "time_ng": time_ng,
                        "note": note,
                        "cancelled": cancelled,
                    }
                )
            rm = ROUTE_RE.match(line)
            if rm:
                cur_day["route"] = rm.group(1)

    return {
        "meta": meta,
        "summary": summary_rows,
        "patients": patient_rows,
        "changelog": changelog,
        "days": days,
    }


def tsv_escape(cell: str) -> str:
    cell = cell.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    return cell


def visits_to_tsv(visits: list[dict], day: str, doctor: str) -> str:
    header = [
        "日付",
        "医師",
        "順",
        "氏名",
        "ID",
        "区分",
        "期限",
        "予定時間",
        "時間NG",
        "特記",
        "住所",
        "備考",
    ]
    rows = [header]
    for v in visits:
        rows.append(
            [
                day,
                doctor,
                v["order"],
                v["name"],
                v["id"],
                v["type"],
                v["deadline"],
                v["eta"],
                v.get("time_ng") or "—",
                v.get("flags") or v.get("area") or "—",
                v["address"],
                v["note"],
            ]
        )
    return "\n".join("\t".join(tsv_escape(c) for c in r) for r in rows)


def all_visits_tsv(days: list[dict]) -> str:
    header = [
        "日付",
        "医師",
        "順",
        "氏名",
        "ID",
        "区分",
        "期限",
        "予定時間",
        "時間NG",
        "特記",
        "住所",
        "備考",
    ]
    rows = [header]
    for d in days:
        for doc in d["doctors"]:
            for v in doc["visits"]:
                rows.append(
                    [
                        d["key"],
                        doc["name"],
                        v["order"],
                        v["name"],
                        v["id"],
                        v["type"],
                        v["deadline"],
                        v["eta"],
                        v.get("time_ng") or "—",
                        v.get("flags") or v.get("area") or "—",
                        v["address"],
                        v["note"],
                    ]
                )
    return "\n".join("\t".join(tsv_escape(c) for c in r) for r in rows)


def patients_to_tsv(patients: list[list[str]]) -> str:
    header = ["氏名", "ID", "区分", "期限", "往診日", "医師", "回数"]
    rows = [header] + patients
    return "\n".join("\t".join(tsv_escape(c) for c in r) for r in rows)


def doctor_class(name: str) -> str:
    if name == "花輪":
        return "hanawa"
    if name == "片山":
        return "katayama"
    return "torikoe"


FACILITY_HINTS: list[tuple[str, str]] = [
    ("ファミリー・ホスピス大泉学園", "FH大泉"),
    ("ファミリー・ホスピス上石神井", "FH上石神井"),
    ("そんぽの家S大泉北", "S大泉北"),
    ("そんぽの家S井荻", "S井荻"),
    ("そんぽの家S練馬土支田", "S土支田"),
    ("そんぽの家S西東京", "S西東京泉町"),
    ("ライブラリ練馬谷原", "L谷原"),
    ("CLASWELL下石神井", "CW下石"),
    ("ＣＬＡＳＷＥＬＬ下石神井", "CW下石"),
    ("アリア上井草", "アリア上井草"),
    ("やはら翔裕園", "谷原翔裕園"),
    ("AMANEKU", "AMANEKU大泉"),
]


def short_town_chome(address: str) -> str:
    """住所を町名＋丁目までに短縮（番地以降・マンション名は出さない）。"""
    if not address or address in {"—", "（住所未登録）"}:
        return "（住所未登録）"
    text = re.sub(r"\s+", "", address)
    facility = ""
    for key, label in FACILITY_HINTS:
        if key in address or key in text:
            facility = label
            break

    # 市区町村を落として町丁目を拾う
    m = re.search(
        r"(?:東京都|埼玉県)?(?:練馬区|杉並区|西東京市|和光市|三鷹市|武蔵野市)?"
        r"([^\d\-－]{2,20}?(?:町|通|台|丘|原)?)"
        r"(\d+)\s*[-－丁目]?",
        text,
    )
    if not m:
        # フォールバック: 「○○町2」や「下連雀5」
        m = re.search(r"([一-龥ぁ-んァ-ン]{2,12}(?:町|通|台|丘|原|雀)?)(\d+)", text)
    if m:
        town, chome = m.group(1), m.group(2)
        # 「市」「区」が町名に食い込んだ場合を軽く補正
        town = re.sub(r"^(?:練馬区|杉並区|西東京市|和光市|三鷹市|武蔵野市)", "", town)
        base = f"{town}{chome}"
    else:
        base = text[:18]

    if facility:
        return f"{base}（{facility}）"
    return base


def parse_driver_from_header(header: str) -> str:
    m = re.search(r"ドライバー[:：]\s*\*?\*?([^*｜\n]+)", header)
    if not m:
        return "未定"
    name = strip_md_bold(m.group(1)).strip()
    name = name.replace("さん", "").strip()
    return name or "未定"


def parse_depart_from_header(header: str, doctor: str) -> str:
    m = re.search(r"出発\s*([^｜|]+)", header)
    if m:
        return m.group(1).strip()
    if doctor == "花輪":
        return HANAWA_PICKUP_MEET
    if doctor == "片山":
        return "13:15"
    return "13:00"


def format_day_ja(day_key: str) -> str:
    """8/3(月) → 8月3日（月）"""
    m = re.match(r"8/(\d+)\(([月土])\)", day_key)
    if not m:
        return day_key
    return f"8月{int(m.group(1))}日（{m.group(2)}）"


def doctor_slot_label(doctor: str) -> str:
    if doctor == "花輪":
        return "午前"
    if doctor == "片山":
        return "午後"
    return "午後（13:00〜16:30）"


def day_sort_key(day_key: str) -> tuple[int, str]:
    m = re.match(r"8/(\d+)", day_key)
    return (int(m.group(1)) if m else 99, day_key)


def kana_to_hiragana(s: str) -> str:
    out = []
    for ch in s:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:  # カタカナ → ひらがな
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def format_display_kana(kana: str) -> str:
    """画面表示用のふりがな（ひらがな・半角スペース区切り）。"""
    s = kana_to_hiragana((kana or "").strip())
    s = re.sub(r"[\s　]+", " ", s).strip()
    return s


def kanji_name_html(name: str, kana: str) -> str:
    """漢字氏名の上にふりがなを小さく載せる。"""
    name_e = html.escape(name)
    kana_e = html.escape(format_display_kana(kana))
    inner = f"<strong>{name_e}</strong>"
    if not kana_e:
        return inner
    return (
        f'<span class="name-stack">'
        f'<span class="name-kana">{kana_e}</span>'
        f"{inner}"
        f"</span>"
    )


def surname_kana(kana: str) -> str:
    """ふりがなから名字部分だけ（空白区切りの先頭）。"""
    if not kana:
        return ""
    s = kana_to_hiragana(kana.strip())
    s = re.split(r"[\s　]+", s)[0]
    return s


def mask_surname_kana(kana: str) -> str:
    """ひらがな名字の2文字目を○にする。例: ときた → と○た"""
    sei = surname_kana(kana)
    if not sei:
        return "（名字不明）"
    if len(sei) == 1:
        return sei + "○"
    return sei[0] + "○" + sei[2:]


def visit_display_name(v: dict, kana_by_id: dict[str, str]) -> str:
    kana = kana_by_id.get(v.get("id") or "", "") or v.get("kana") or ""
    return mask_surname_kana(kana)


def doctor_sort_key(doctor: str) -> int:
    """同日に午前・午後があるとき花輪→片山→鳥越の順。"""
    return {"花輪": 0, "片山": 1, "鳥越": 2}.get(doctor, 9)


CLINIC_RETURN_ADDRESS = "〒178-0063 東京都練馬区東大泉1-28-7 フォンターナ琴坂 6F"
PICKUP_ADDRESS = "院長の駐車場（榎本駐車場）"
KATAYAMA_PICKUP_ADDRESS = "ローソン前"
HANAWA_PICKUP_MEET = "10:15"
KATAYAMA_HOME = "東京都練馬区大泉学園町6-28-34"
TORIGOE_HOME = "東京都練馬区東大泉2-40-8"

MAIL_DISCLAIMER = (
    "■ ご注意\n"
    "・利用者様の体調不良などにより当日キャンセルが出た場合、回り順や予定時刻の再調整が必要になり、"
    "内容が変わることがあります。その際は改めてご連絡いたします。\n"
)


def format_driver_recipient(name: str) -> str:
    s = (name or "").strip()
    if not s or s == "未定":
        return "〇〇様"
    s = s.replace("さん", "").strip()
    return f"{s}様"


def mail_closing() -> str:
    return "\n" + MAIL_DISCLAIMER + "\nよろしくお願いいたします。\n"


def strip_mail_footer(text: str) -> str:
    text = re.sub(r"\n*■ ご注意\n[\s\S]*", "", text)
    text = re.sub(r"\n*よろしくお願いいたします。\n?\s*$", "\n", text)
    return text.rstrip() + "\n"


def build_transport_section(
    doctor: str,
    depart: str,
    visits: list[dict],
    *,
    for_doctor: bool = False,
) -> str:
    """担当医師ごとのお迎え・待機・お送り先。医師向けは住所を省略し大まかな表現のみ。"""
    lines = ["■ 送迎・待機"]
    first_id = (visits[0].get("id") if visits else "") or ""
    if for_doctor:
        if doctor == "花輪":
            if first_id == "b288" or "11:15" in depart or "三鷹" in depart:
                lines.append(f"・お迎え：{PICKUP_ADDRESS}（{HANAWA_PICKUP_MEET}）")
                lines.append(
                    "・1件目：水上次義様は院長ご自宅から三鷹へ直行。"
                    "2件目以降は11:15クリニック再出発に合わせてください"
                )
            else:
                lines.append(f"・お迎え：{PICKUP_ADDRESS}（{depart}）")
            lines.append("・お送り：クリニックへ")
        elif doctor == "片山":
            lines.append(f"・お迎え：{KATAYAMA_PICKUP_ADDRESS}（{depart}）")
            lines.append("・お送り：片山先生ご自宅まで")
        elif doctor == "鳥越":
            lines.append(f"・お迎え：鳥越先生ご自宅（{depart}）")
            lines.append("・お送り：鳥越先生ご自宅まで（帰宅目安16:30）")
        else:
            lines.append(f"・出発：{depart}")
        return "\n".join(lines) + "\n"

    if doctor == "花輪":
        if first_id == "b288" or "11:15" in depart or "三鷹" in depart:
            lines.append(f"・お迎え／待機：{PICKUP_ADDRESS}（{HANAWA_PICKUP_MEET}）")
            lines.append(
                "・1件目：水上次義様は院長がご自宅から三鷹へ直行のため、"
                f"ドライバー待機は{PICKUP_ADDRESS}{HANAWA_PICKUP_MEET}。2件目以降は11:15クリニック再出発に合わせてください"
            )
        else:
            lines.append(f"・お迎え／出発：{PICKUP_ADDRESS}（{depart}）")
        lines.append(f"・お送り：{CLINIC_RETURN_ADDRESS}へお返し")
    elif doctor == "片山":
        lines.append(f"・お迎え／出発：{KATAYAMA_PICKUP_ADDRESS}（{depart}）")
        lines.append(f"・お送り：片山先生ご自宅（{KATAYAMA_HOME}）へお返し")
    elif doctor == "鳥越":
        lines.append(f"・お迎え／出発：鳥越先生ご自宅（{TORIGOE_HOME}）（{depart}）")
        lines.append(f"・お送り：鳥越先生ご自宅（{TORIGOE_HOME}）へお返し（帰宅目安16:30）")
    else:
        lines.append(f"・出発：{depart}")
    return "\n".join(lines) + "\n"


def build_route_mail_body(
    *,
    recipient: str,
    kind: str,
    day_key: str,
    doctor: str,
    depart: str,
    visits: list[dict],
    kana_by_id: dict[str, str],
    day_driver: str = "",
) -> tuple[str, str]:
    """(件名, 本文) を返す。kind は driver|doctor。氏名はひらがな名字＋伏せ字のみ。"""
    day_ja = format_day_ja(day_key)
    n = len(visits)
    slot = doctor_slot_label(doctor)

    news: list[str] = []
    mynas: list[str] = []
    time_notes: list[str] = []
    lines_order: list[str] = []

    dow_m = re.search(r"\(([月土])\)", day_key)
    dow_ch = dow_m.group(1) if dow_m else ""

    for v in visits:
        flags = v.get("flags") or ""
        time_ng = (v.get("time_ng") or "—").strip()
        short = short_town_chome(address_for_visit_day(v.get("address") or "", dow_ch))
        disp = visit_display_name(v, kana_by_id)
        tags: list[str] = []
        if "新規" in flags:
            tags.append("新規")
            news.append(f"{v['order']}件目・{disp}")
        if "マイナ" in flags:
            tags.append(flags if "マイナ" in flags else "マイナ")
            mynas.append(f"{v['order']}件目・{disp}（{flags}）")
        if time_ng and time_ng != "—":
            tags.append(time_ng)
            time_notes.append(f"{v['order']}件目 {disp}＝{time_ng}")
        tag_s = f"（{'／'.join(tags)}）" if tags else ""
        lines_order.append(f"{v['order']}. {short}{tag_s}")

    if kind == "driver":
        to_line = format_driver_recipient(recipient)
        subject = f"【往診送迎】{day_ja} {doctor}先生（{n}名）"
        intro = (
            f"{to_line}\n\n"
            "お世話になっております。\n"
            f"{day_ja}の往診送迎についてご連絡です。\n"
        )
        assign = (
            f"■ 担当\n"
            f"{doctor}先生（{slot}）／出発 {depart}／{n}名\n"
        )
        transport = build_transport_section(doctor, depart, visits) + "\n"
    else:
        to_line = f"{recipient}先生"
        subject = f"【往診予定】{day_ja}（{n}名）"
        intro = (
            f"{to_line}\n\n"
            "お世話になっております。\n"
            "8月の往診予定が決定いたしましたので、ご連絡いたします。\n"
            f"{day_ja}分のご予定です（{n}名）。\n"
        )
        assign = (
            f"■ 予定\n"
            f"{slot}／出発 {depart}／{n}名\n"
        )
        if day_driver:
            assign += f"\n■ 送迎担当\n{format_driver_recipient(day_driver)}\n"
        transport = build_transport_section(doctor, depart, visits, for_doctor=True) + "\n"

    special_lines: list[str] = []
    if news:
        special_lines.append(f"・新規: {len(news)}名（{'、'.join(news)}）")
    else:
        special_lines.append("・新規: なし")
    if mynas:
        special_lines.append(f"・マイナ保険: {len(mynas)}名（{'、'.join(mynas)}）")
    else:
        special_lines.append("・マイナ保険: なし（この枠）")
    if time_notes:
        special_lines.append("・時間NG／希望:")
        for t in time_notes:
            special_lines.append(f"　- {t}")
    else:
        special_lines.append("・時間NG／希望: 特記なし")

    body = (
        intro
        + "\n"
        + assign
        + "\n"
        + transport
        + "■ 回り順（町名・丁目まで）\n"
        + "\n".join(lines_order)
        + "\n\n"
        + "■ 特記\n"
        + "\n".join(special_lines)
        + mail_closing()
    )
    return subject, body


DAY_BLOCK_SEPARATOR = "\n\n\n────────────────────────\n\n\n"
SAME_DAY_DOCTOR_GAP = "\n\n"


def build_bulk_mail_body(group: str, kind: str, day_cards: list[dict]) -> tuple[str, str]:
    """同一受信者の複数日分を1通にまとめる。"""
    day_cards = sorted(
        day_cards,
        key=lambda c: (day_sort_key(c["day"]), doctor_sort_key(c["doctor"])),
    )
    uniq_days: list[str] = []
    seen: set[str] = set()
    for c in day_cards:
        if c["day"] not in seen:
            seen.add(c["day"])
            uniq_days.append(c["day"])
    days_ja = "・".join(format_day_ja(d) for d in uniq_days)
    n_days = len(uniq_days)
    if kind == "driver":
        to_line = group if group.endswith("様") else format_driver_recipient(group.replace("さん", ""))
        subject = f"【往診送迎】8月分まとめ（{n_days}日）"
        intro = (
            f"{to_line}\n\n"
            "お世話になっております。\n"
            f"8月の往診送迎について、{n_days}日分まとめてご連絡です（{days_ja}）。\n"
        )
    else:
        to_line = group if group.endswith("先生") else f"{group}先生"
        subject = f"【往診予定】8月分まとめ（{n_days}日）"
        intro = (
            f"{to_line}\n\n"
            "お世話になっております。\n"
            "8月の往診予定が決定いたしましたので、ご連絡いたします。\n"
            f"{n_days}日分（{days_ja}）をまとめてお送りいたしますので、ご確認ください。\n"
        )

    parts = [intro]
    # 日別の送迎担当（申し送り）
    day_driver_seen: set[str] = set()
    driver_summary: list[str] = []
    for c in day_cards:
        dk = c["day"]
        if dk in day_driver_seen:
            continue
        day_driver_seen.add(dk)
        drv = c.get("driver") or "未定"
        driver_summary.append(
            f"・{format_day_ja(dk)}：{format_driver_recipient(drv)}"
        )
    if driver_summary:
        parts.append("\n■ 送迎担当（日別）\n")
        parts.append("\n".join(driver_summary) + "\n")

    prev_day: str | None = None
    for i, c in enumerate(day_cards):
        if i > 0:
            if c["day"] != prev_day:
                parts.append(DAY_BLOCK_SEPARATOR)
            else:
                parts.append(SAME_DAY_DOCTOR_GAP)
        body = c["body"]
        marker = "■ 担当\n" if kind == "driver" else "■ 予定\n"
        idx = body.find(marker)
        chunk = body[idx:] if idx >= 0 else body
        chunk = strip_mail_footer(chunk)
        drv = c.get("driver") or "未定"
        parts.append(f"━━ {format_day_ja(c['day'])}｜{c['doctor']}先生 ━━\n")
        parts.append(f"送迎ドライバー：{format_driver_recipient(drv)}\n")
        parts.append(chunk.rstrip() + "\n")
        prev_day = c["day"]
    parts.append(mail_closing())
    return subject, "".join(parts)


def collect_mail_cards(
    days: list[dict],
    kana_by_id: dict[str, str] | None = None,
) -> dict[str, list[dict]]:
    """driver / doctor 向けメールカード一覧（日付順＋受信者ごと一括カード）。"""
    kana_by_id = kana_by_id or {}
    driver_cards: list[dict] = []
    doctor_cards: list[dict] = []

    for d in days:
        day_key = d["key"]
        docs_sorted = sorted(
            d["doctors"],
            key=lambda doc: doctor_sort_key(doc["name"]),
        )
        for doc in docs_sorted:
            driver = parse_driver_from_header(doc.get("header") or "")
            depart = parse_depart_from_header(doc.get("header") or "", doc["name"])
            visits = doc.get("visits") or []
            if not visits:
                continue

            subj_d, body_d = build_route_mail_body(
                recipient=driver,
                kind="driver",
                day_key=day_key,
                doctor=doc["name"],
                depart=depart,
                visits=visits,
                kana_by_id=kana_by_id,
                day_driver=driver,
            )
            driver_cards.append(
                {
                    "group": "未定" if driver == "未定" else format_driver_recipient(driver),
                    "day": day_key,
                    "doctor": doc["name"],
                    "driver": driver,
                    "subject": subj_d,
                    "body": body_d,
                    "label": f"{day_key} {doc['name']} → {format_driver_recipient(driver)}",
                    "kind_card": "day",
                }
            )

            subj_p, body_p = build_route_mail_body(
                recipient=doc["name"],
                kind="doctor",
                day_key=day_key,
                doctor=doc["name"],
                depart=depart,
                visits=visits,
                kana_by_id=kana_by_id,
                day_driver=driver,
            )
            doctor_cards.append(
                {
                    "group": f"{doc['name']}先生",
                    "day": day_key,
                    "doctor": doc["name"],
                    "driver": driver,
                    "subject": subj_p,
                    "body": body_p,
                    "label": f"{day_key} → {doc['name']}先生",
                    "kind_card": "day",
                }
            )

    def enrich_with_bulk(cards: list[dict], kind: str) -> list[dict]:
        # 日付順
        cards.sort(key=lambda c: (day_sort_key(c["day"]), doctor_sort_key(c["doctor"])))
        by_group: dict[str, list[dict]] = {}
        for c in cards:
            by_group.setdefault(c["group"], []).append(c)

        # グループ順: 最初の担当日が早い人から
        group_order = sorted(
            by_group.keys(),
            key=lambda g: day_sort_key(by_group[g][0]["day"]),
        )

        out: list[dict] = []
        for g in group_order:
            day_list = by_group[g]
            if len(day_list) >= 2:
                # 同一日内の複数医師枠は「日数」ではなくルート数。日ユニークで数える
                uniq_days = []
                seen = set()
                for c in day_list:
                    if c["day"] not in seen:
                        seen.add(c["day"])
                        uniq_days.append(c["day"])
                subj_b, body_b = build_bulk_mail_body(g, kind, day_list)
                days_joined = "・".join(uniq_days)
                out.append(
                    {
                        "group": g,
                        "day": day_list[0]["day"],
                        "doctor": "",
                        "subject": subj_b,
                        "body": body_b,
                        "label": f"{g}｜{len(uniq_days)}日分一括（{days_joined}）",
                        "kind_card": "bulk",
                    }
                )
            out.extend(day_list)
        return out

    return {
        "driver": enrich_with_bulk(driver_cards, "driver"),
        "doctor": enrich_with_bulk(doctor_cards, "doctor"),
    }


def load_kana_by_chart_id() -> dict[str, str]:
    out: dict[str, str] = {}
    if HOPE_CSV.exists():
        with HOPE_CSV.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                pid = (row.get("ID") or "").strip()
                kana = (row.get("ふりがな") or "").strip()
                if pid:
                    out[pid] = kana
    if LEDGER_CSV.exists():
        with LEDGER_CSV.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header:
                try:
                    i_id = header.index("ID")
                    i_kana = header.index("ふりがな")
                except ValueError:
                    i_id, i_kana = 2, 4
                for row in reader:
                    if len(row) <= max(i_id, i_kana):
                        continue
                    pid = (row[i_id] or "").strip()
                    kana = (row[i_kana] or "").strip()
                    if pid and pid not in out and kana:
                        out[pid] = kana
    return out


def build_search_index(data: dict, kana_by_id: dict[str, str]) -> list[dict]:
    entries: dict[str, dict] = {}
    for d in data["days"]:
        for doc in d["doctors"]:
            for v in doc["visits"]:
                pid = v["id"]
                if pid not in entries:
                    entries[pid] = {
                        "id": pid,
                        "name": v["name"],
                        "kana": kana_by_id.get(pid, ""),
                        "visits": [],
                    }
                entries[pid]["visits"].append(
                    {
                        "day": d["key"],
                        "doctor": doc["name"],
                        "order": v["order"],
                    }
                )
    for row in data["patients"]:
        if len(row) < 2:
            continue
        pid = row[1]
        if pid in entries:
            continue
        entries[pid] = {
            "id": pid,
            "name": row[0],
            "kana": kana_by_id.get(pid, ""),
            "visits": [],
            "schedule_note": row[4] if len(row) > 4 else "",
        }
    return sorted(entries.values(), key=lambda x: x["name"])


def day_chips_in_visit_order(day: dict) -> list[tuple[str, str, str, str]]:
    """(css class, patient id, name, doctor) in 往診順."""
    items: list[tuple[str, str, str, str]] = []
    for doc in day["doctors"]:
        dc = doctor_class(doc["name"])
        for v in doc["visits"]:
            chip_cls = f"{dc} cancelled" if v.get("cancelled") else dc
            items.append((chip_cls, v["id"], v["name"], doc["name"]))
    return items


def render_html(
    data: dict,
    kana_by_id: dict[str, str] | None = None,
    *,
    updated_at_iso: str,
    updated_at_label: str,
) -> str:
    meta = data["meta"]
    kana_by_id = kana_by_id or load_kana_by_chart_id()
    mail_cards = collect_mail_cards(data["days"], kana_by_id)
    mail_json = json.dumps(mail_cards, ensure_ascii=False)
    updated_at_html = html.escape(updated_at_label)

    changelog_items = data.get("changelog") or []
    changelog_lis = "".join(f"<li>{html.escape(item)}</li>" for item in reversed(changelog_items))
    changelog_html = f"""
    <section class="changelog-sheet" id="sheet-changelog" hidden>
      <div class="print-sheet-title print-only">
        <span class="print-updated-at print-only">最終更新: {updated_at_html}</span>
        <span class="print-doc-title">{html.escape(meta['title'])}</span>
        <span class="print-day">変更履歴</span>
        <span class="print-meta">{len(changelog_items)}件</span>
      </div>
      <h2 class="no-print">変更履歴</h2>
      <p class="changelog-updated">リスト最終更新: {updated_at_html}</p>
      <ol class="changelog-list">{changelog_lis}</ol>
    </section>"""
    summary_html = ""
    for row in data["summary"]:
        summary_html += f"""
        <tr>
          <td>{html.escape(row[0])}</td>
          <td class="num">{html.escape(row[1]) if row[1] != "—" else "—"}</td>
          <td class="num">{html.escape(row[2]) if row[2] != "—" else "—"}</td>
          <td class="num">{html.escape(row[3]) if row[3] != "—" else "—"}</td>
          <td class="num"><strong>{html.escape(row[4])}</strong></td>
        </tr>"""

    day_sections = ""
    for d in data["days"]:
        day_id = d["key"].replace("/", "").replace("(", "").replace(")", "")
        chips = ""
        for dc, pid, pname, doc_name in day_chips_in_visit_order(d):
            chips += f"""
            <span class="chip {dc}" title="{html.escape(pid)}">
              {html.escape(pname)} <small>{html.escape(doc_name)}</small>
            </span>"""

        blocks = ""
        for doc in d["doctors"]:
            dc = doctor_class(doc["name"])
            tsv_id = f"tsv-{day_id}-{doc['name']}"
            rows = ""
            for v in doc["visits"]:
                type_cls = "medical" if v["type"] == "医療" else ""
                if v.get("cancelled"):
                    type_cls = f"{type_cls} visit-cancelled".strip()
                name_core = kanji_name_html(v["name"], kana_by_id.get(v["id"], ""))
                if v.get("cancelled"):
                    name_html = (
                        f'<span class="visit-cancel-line">{name_core}'
                        f'<br><span class="id">{html.escape(v["id"])}</span></span>'
                        f' <span class="visit-cancel-label">キャンセル</span>'
                    )
                else:
                    name_html = (
                        f"{name_core}"
                        f"<br><span class=\"id\">{html.escape(v['id'])}</span>"
                    )
                rows += f"""
                <tr class="{type_cls}" data-patient-id="{html.escape(v['id'])}" data-patient-name="{html.escape(v['name'])}" data-day="{html.escape(d['key'])}" data-doctor="{html.escape(doc['name'])}" data-cancelled="{"1" if v.get("cancelled") else "0"}">
                  <td class="row-tools no-print">
                    <span class="drag-handle" title="ドラッグして並び替え" aria-hidden="true">⋮⋮</span>
                    <button type="button" class="move-day-btn" title="別の日へ移動">日</button>
                  </td>
                  <td class="order">{html.escape(v['order'])}</td>
                  <td class="name">{name_html}</td>
                  <td>{html.escape(v['type'])}</td>
                  <td class="deadline">{html.escape(v['deadline'])}</td>
                  <td class="eta">{html.escape(v['eta'])}</td>
                  <td class="time-ng">{html.escape(v.get('time_ng') or '—')}</td>
                  <td class="flags">{html.escape(v.get('flags') or v.get('area') or '—')}</td>
                  <td class="addr">{html.escape(v['address'])}</td>
                  <td class="note">{html.escape(v['note'])}</td>
                </tr>"""
            blocks += f"""
            <section class="doctor-block {dc}" data-doctor="{html.escape(doc['name'])}" data-day="{html.escape(d['key'])}" data-tsv-id="{tsv_id}">
              <div class="doctor-head">
                <h3>{html.escape(doc['header'])}</h3>
                <button type="button" class="copy-btn no-print" data-target="{tsv_id}" data-label="{html.escape(d['key'])} {html.escape(doc['name'])}">表をコピー（TSV）</button>
              </div>
              <textarea id="{tsv_id}" class="tsv-store" readonly aria-hidden="true">{html.escape(visits_to_tsv(doc['visits'], d['key'], doc['name']))}</textarea>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th class="no-print tools-h"></th>
                      <th class="order-h">#</th><th>氏名</th><th>区分</th><th>期限</th><th>予定</th><th>時間NG</th><th>特記</th><th>住所</th><th>備考</th>
                    </tr>
                  </thead>
                  <tbody>{rows}</tbody>
                </table>
              </div>
            </section>"""

        route = f'<p class="route">動線: {html.escape(d["route"])}</p>' if d["route"] else ""
        edit_note = (
            f'<p class="day-edit-note">📅 {html.escape(d["edit_note"])}</p>'
            if d.get("edit_note")
            else ""
        )
        total_visits = sum(len(doc["visits"]) for doc in d["doctors"])
        if total_visits >= 10:
            density = "dense"
        elif total_visits >= 7:
            density = "medium"
        else:
            density = "normal"
        doc_labels = " / ".join(
            f"{doc['name']}{len(doc['visits'])}件" for doc in d["doctors"]
        )
        day_sections += f"""
        <article class="day-card {density}" id="day-{day_id}" data-day="{html.escape(d['key'])}">
          <div class="print-sheet-title print-only">
            <span class="print-updated-at print-only">最終更新: {updated_at_html}</span>
            <span class="print-doc-title">{html.escape(meta['title'])}</span>
            <span class="print-day">{html.escape(d['key'])}</span>
            <span class="print-meta">{html.escape(doc_labels)} ・ 合計{total_visits}件</span>
          </div>
          <header class="day-header" id="day-{day_id}-head">
            <h2>{html.escape(d['key'])}</h2>
            <div class="day-actions no-print">
              <button type="button" class="copy-btn secondary" data-target="tsv-day-{day_id}" data-label="{html.escape(d['key'])} 全日">この日をまとめてコピー</button>
              <button type="button" class="print-btn" data-print-day="day-{day_id}" data-label="{html.escape(d['key'])}" onclick="OusehinPrint.one('day-{day_id}'); return false;">この日を印刷（A4）</button>
              <button type="button" class="map-btn" data-map-day="day-{day_id}" data-label="{html.escape(d['key'])}" onclick="OusehinRouteMap.one('day-{day_id}'); return false;">マップ</button>
            </div>
          </header>
          {edit_note}
          <textarea id="tsv-day-{day_id}" class="tsv-store" readonly aria-hidden="true">{html.escape(_day_tsv(d))}</textarea>
          <div class="chip-row no-print">{chips}</div>
          {blocks}
          {route}
          {render_day_cautions(d["key"])}
        </article>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(meta['title'])}</title>
  <script>
    window.OusehinPrint = (function() {{
      function clearModes() {{
        document.body.classList.remove('print-one-day', 'print-include-summary', 'print-all-days');
        document.querySelectorAll('.day-card').forEach(function(c) {{
          c.classList.remove('print-target');
        }});
      }}
      function getPrintStyles() {{
        var el = document.querySelector('style');
        return el ? el.textContent : '';
      }}
      function prepareClone(node) {{
        var clone = node.cloneNode(true);
        clone.removeAttribute('hidden');
        clone.hidden = false;
        clone.querySelectorAll('.no-print, .copy-btn, .tsv-store').forEach(function(el) {{
          el.remove();
        }});
        clone.querySelectorAll('.print-only').forEach(function(el) {{
          el.style.display = 'block';
        }});
        var srcImgs = node.querySelectorAll('img');
        var dstImgs = clone.querySelectorAll('img');
        for (var i = 0; i < dstImgs.length; i++) {{
          dstImgs[i].src = srcImgs[i].currentSrc || srcImgs[i].src;
        }}
        return clone;
      }}
      function whenImagesReady(doc, done) {{
        var finished = false;
        var finish = function() {{
          if (finished) return;
          finished = true;
          done();
        }};
        var imgs = Array.prototype.slice.call(doc.images || []);
        if (!imgs.length) {{
          finish();
          return;
        }}
        var left = imgs.length;
        var tick = function() {{
          left -= 1;
          if (left <= 0) finish();
        }};
        imgs.forEach(function(img) {{
          if (img.complete) tick();
          else {{
            img.addEventListener('load', tick);
            img.addEventListener('error', tick);
          }}
        }});
        setTimeout(finish, 4000);
      }}
      function printNodes(nodes, bodyClass) {{
        bodyClass = bodyClass || '';
        var iframe = document.createElement('iframe');
        iframe.setAttribute('title', 'print');
        iframe.style.cssText = 'position:fixed;width:0;height:0;border:0;visibility:hidden';
        document.body.appendChild(iframe);
        var win = iframe.contentWindow;
        var doc = win.document;
        doc.open();
        doc.write('<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><style>');
        doc.write(getPrintStyles());
        doc.write('body{{margin:0;padding:0}} .print-only{{display:block!important}} .no-print{{display:none!important}}');
        doc.write('body.print-all-days .changelog-sheet[hidden]{{display:block!important}}');
        doc.write('</style></head><body class="' + bodyClass + '">');
        doc.close();
        nodes.forEach(function(n) {{
          doc.body.appendChild(prepareClone(n));
        }});
        if (window.showToast) {{
          window.showToast('印刷ダイアログを開きます（背面に出る場合があります）');
        }}
        whenImagesReady(doc, function() {{
          win.focus();
          try {{
            win.print();
          }} catch (err) {{
            alert('印刷ダイアログを開けませんでした。Chrome または Safari でこのファイルを開き、⌘P（印刷）をお試しください。');
          }}
        }});
        setTimeout(function() {{ iframe.remove(); }}, 120000);
      }}
      return {{
        all: function() {{
          clearModes();
          var cards = Array.prototype.slice.call(document.querySelectorAll('.day-card'));
          if (!cards.length) {{
            window.print();
            return;
          }}
          var logEl = document.getElementById('sheet-changelog');
          if (logEl) {{
            cards = cards.concat([logEl]);
          }}
          printNodes(cards, 'print-all-days');
        }},
        summary: function() {{
          clearModes();
          var el = document.getElementById('summary-print');
          if (!el) return;
          printNodes([el], 'print-include-summary');
        }},
        one: function(id) {{
          clearModes();
          var card = document.getElementById(id);
          if (!card) return;
          printNodes([card], 'print-one-day');
        }}
      }};
    }})();
  </script>
  <style>
    :root {{
      --bg: #f4f6f9;
      --card: #fff;
      --text: #1a2332;
      --muted: #5c6b7f;
      --border: #dde3ec;
      --hanawa: #2d6a4f;
      --hanawa-bg: #e8f5ee;
      --katayama: #1d4e89;
      --katayama-bg: #e8f0fa;
      --torikoe: #7c4a03;
      --torikoe-bg: #fef3e2;
      --accent: #0f766e;
    }}
    * {{ box-sizing: border-box; }}
    html {{
      scroll-behavior: smooth;
      scroll-padding-top: var(--sticky-top, 9rem);
    }}
    body {{
      margin: 0;
      font-family: "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    .top {{
      background: linear-gradient(135deg, #0f766e 0%, #1d4e89 100%);
      color: #fff;
      padding: 1.25rem 1.5rem 1rem;
      position: sticky;
      top: 0;
      z-index: 20;
      box-shadow: 0 2px 12px rgba(0,0,0,.12);
    }}
    .top h1 {{ font-size: 1.35rem; font-weight: 700; }}
    .visually-hidden {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }}
    .top .sub {{ opacity: .92; font-size: .85rem; margin-bottom: .75rem; }}
    .top-actions {{ display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: .25rem; }}
    .top-head {{
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
      gap: .75rem 1rem;
      margin-bottom: .35rem;
    }}
    .top-head h1 {{ margin: 0; }}
    .top-head-tools {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: flex-end;
      gap: .5rem 1rem;
      flex: 1 1 280px;
    }}
    .patient-search {{
      position: relative;
      flex: 1 1 220px;
      max-width: 360px;
      min-width: 180px;
    }}
    .last-updated {{
      flex: 0 0 auto;
      margin: 0;
      font-size: .75rem;
      opacity: .9;
      white-space: nowrap;
    }}
    .patient-search input {{
      width: 100%;
      border: 1px solid rgba(255,255,255,.45);
      border-radius: 999px;
      padding: .45rem .9rem;
      font-size: .85rem;
      background: rgba(255,255,255,.95);
      color: var(--text);
    }}
    .patient-search input::placeholder {{ color: #64748b; }}
    .patient-search input:focus {{
      outline: 2px solid #fff;
      outline-offset: 1px;
    }}
    .patient-search-results {{
      position: absolute;
      left: 0;
      right: 0;
      top: calc(100% + .35rem);
      background: #fff;
      color: var(--text);
      border-radius: 10px;
      box-shadow: 0 8px 28px rgba(0,0,0,.18);
      max-height: min(50vh, 320px);
      overflow-y: auto;
      z-index: 30;
      border: 1px solid var(--border);
    }}
    .patient-search-results[hidden] {{ display: none !important; }}
    .patient-search-item {{
      display: block;
      width: 100%;
      text-align: left;
      border: none;
      border-bottom: 1px solid #f1f5f9;
      background: #fff;
      padding: .5rem .75rem;
      cursor: pointer;
      font-size: .82rem;
      line-height: 1.35;
    }}
    .patient-search-item:hover,
    .patient-search-item.active {{
      background: #ecfdf5;
    }}
    .patient-search-item strong {{ font-weight: 700; }}
    .patient-search-item .meta {{
      display: block;
      font-size: .75rem;
      color: var(--muted);
      margin-top: .1rem;
    }}
    .patient-search-empty {{
      padding: .65rem .75rem;
      font-size: .8rem;
      color: var(--muted);
    }}
    tr.search-hit {{
      outline: 2px solid #f59e0b;
      outline-offset: -2px;
      background: #fffbeb !important;
    }}
    .edit-banner {{
      background: #fef3c7;
      color: #92400e;
      border-bottom: 1px solid #f59e0b;
      padding: .55rem 1rem;
      font-size: .85rem;
      display: flex;
      flex-wrap: wrap;
      gap: .5rem 1rem;
      align-items: center;
      position: sticky;
      top: var(--sticky-top, 9rem);
      z-index: 19;
    }}
    .edit-banner[hidden] {{ display: none !important; }}
    .edit-banner .save-btn {{
      border: none;
      background: #92400e;
      color: #fff;
      font-weight: 600;
      font-size: .8rem;
      padding: .4rem .8rem;
      border-radius: 8px;
      cursor: pointer;
    }}
    .save-hint {{
      background: #ecfdf5;
      color: #065f46;
      border-bottom: 1px solid #6ee7b7;
      padding: .55rem 1rem;
      font-size: .8rem;
    }}
    .save-hint[hidden] {{ display: none !important; }}
    .row-tools {{
      width: 2.6rem;
      white-space: nowrap;
      vertical-align: middle;
      padding-right: .15rem !important;
    }}
    .tools-h {{ width: 2.6rem; }}
    .drag-handle {{
      cursor: grab;
      color: #94a3b8;
      font-size: .85rem;
      letter-spacing: -0.15em;
      user-select: none;
      display: inline-block;
      padding: .15rem .1rem;
    }}
    .drag-handle:active {{ cursor: grabbing; }}
    .move-day-btn {{
      border: 1px solid var(--border);
      background: #fff;
      color: var(--muted);
      font-size: .65rem;
      font-weight: 700;
      padding: .15rem .3rem;
      border-radius: 4px;
      cursor: pointer;
      margin-left: .1rem;
    }}
    .move-day-btn:hover {{ background: #f1f5f9; color: var(--text); }}
    tr.dragging {{ opacity: .45; }}
    tr.drop-before {{ box-shadow: inset 0 3px 0 #0f766e; }}
    tr.drop-target {{ box-shadow: inset 0 -3px 0 #0f766e; }}
    .doctor-block.drag-over-block {{
      outline: 2px dashed #0f766e;
      outline-offset: -2px;
      background: rgba(15, 118, 110, .04);
    }}
    .modal-root {{
      position: fixed;
      inset: 0;
      z-index: 50;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1rem;
    }}
    .modal-root[hidden] {{ display: none !important; }}
    .mail-modal-panel {{
      position: relative;
      background: #fff;
      border-radius: 12px;
      padding: 1rem 1.15rem 1.25rem;
      width: min(720px, 100%);
      max-height: min(92vh, 860px);
      overflow: auto;
      box-shadow: 0 12px 40px rgba(0,0,0,.2);
      z-index: 1;
    }}
    .mail-modal-panel h3 {{ margin: 0; font-size: 1.05rem; }}
    .mail-modal-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: .75rem;
      margin-bottom: .75rem;
      position: sticky;
      top: 0;
      background: #fff;
      z-index: 2;
      padding-bottom: .5rem;
      border-bottom: 1px solid var(--border);
    }}
    .mail-modal-panel.route-map-panel {{
      width: min(920px, 100%);
      max-height: min(94vh, 980px);
    }}
    .route-map-wrap {{
      margin: 0 0 .85rem;
    }}
    #route-map-canvas {{
      height: 320px;
      width: 100%;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #e2e8f0;
      z-index: 0;
      overflow: hidden;
    }}
    .map-status {{
      margin: .4rem 0 0;
      min-height: 1.1rem;
      font-size: .78rem;
      color: #0f766e;
    }}
    .map-pin {{ background: none !important; border: none !important; }}
    .map-pin-inner {{
      display: flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      border-radius: 999px;
      color: #fff;
      font-size: 12px;
      font-weight: 700;
      box-shadow: 0 1px 4px rgba(0,0,0,.35);
    }}
    .map-route {{
      margin: 0 0 1.1rem;
      padding-bottom: .85rem;
      border-bottom: 1px dashed var(--border);
    }}
    .map-route:last-child {{ margin-bottom: 0; padding-bottom: 0; border-bottom: 0; }}
    .map-route h4 {{ margin: 0 0 .55rem; font-size: 1rem; }}
    .map-route h4 span {{ font-weight: 600; color: #64748b; font-size: .85rem; margin-left: .35rem; }}
    .map-privacy {{
      margin: 0 0 1rem;
      padding: .65rem .75rem;
      border-radius: 8px;
      background: #fef2f2;
      border: 1px solid #fca5a5;
      color: #7f1d1d;
      font-size: .8rem;
      line-height: 1.45;
    }}
    .map-privacy strong {{ display: block; margin-bottom: .25rem; }}
    .map-privacy p {{ margin: .25rem 0 0; }}
    .map-live-hint {{ color: #9f1239; }}
    .map-warn {{
      margin: 0 0 .5rem;
      font-size: .8rem;
      color: #9a3412;
      background: #fff7ed;
      border: 1px solid #fdba74;
      border-radius: 8px;
      padding: .4rem .6rem;
    }}
    .map-stops {{
      margin: 0 0 .75rem;
      padding: 0;
      list-style: none;
    }}
    .map-stop {{
      display: grid;
      grid-template-columns: 1.1rem 4.2rem 1fr;
      gap: .35rem .5rem;
      align-items: start;
      font-size: .85rem;
      margin: 0;
      padding: .15rem 0 .55rem;
    }}
    .map-stop-rail {{
      grid-row: 1 / span 4;
      width: 4px;
      min-height: 100%;
      margin: .35rem auto 0;
      border-radius: 4px;
      background: #d1fae5;
    }}
    .map-stop.is-start .map-stop-rail {{ background: #93c5fd; }}
    .map-stop.is-end .map-stop-rail {{ background: #c4b5fd; }}
    .map-stop-badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 1.45rem;
      padding: 0 .35rem;
      border-radius: 6px;
      background: #ecfdf5;
      color: #065f46;
      font-size: .7rem;
      font-weight: 700;
      white-space: nowrap;
    }}
    .map-stop.is-start .map-stop-badge {{ background: #dbeafe; color: #1e40af; }}
    .map-stop.is-end .map-stop-badge {{ background: #ede9fe; color: #5b21b6; }}
    .map-stop-body {{ min-width: 0; }}
    .map-stop-place {{
      margin: 0;
      font-weight: 700;
      display: flex;
      flex-wrap: wrap;
      gap: .25rem .6rem;
      align-items: baseline;
    }}
    .map-stop-when {{ font-weight: 600; color: #0f766e; font-size: .8rem; }}
    .map-stop-addr {{ margin: .2rem 0 0; color: #334155; font-size: .8rem; word-break: break-all; }}
    .map-addr-label {{
      display: inline-block;
      font-size: .68rem;
      font-weight: 700;
      color: #64748b;
      margin-right: .25rem;
    }}
    .map-stop-note {{ margin: .2rem 0 0; font-size: .75rem; color: #b45309; }}
    .map-open-row {{ display: flex; flex-wrap: wrap; gap: .4rem; }}
    .map-open-link {{
      display: inline-block;
      border: none;
      text-decoration: none;
      background: #059669;
      color: #fff;
      font-weight: 600;
      font-size: .8rem;
      padding: .4rem .75rem;
      border-radius: 8px;
      cursor: pointer;
    }}
    .map-open-link:hover {{ background: #047857; }}
    .mail-close {{
      border: 1px solid var(--border);
      background: #f8fafc;
      border-radius: 8px;
      padding: .35rem .7rem;
      cursor: pointer;
      font-weight: 600;
      font-size: .8rem;
    }}
    .mail-group {{
      margin: 1rem 0 .5rem;
      font-size: .95rem;
      font-weight: 700;
      color: var(--accent);
      border-left: 3px solid var(--accent);
      padding-left: .5rem;
    }}
    .mail-card {{
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: .75rem .85rem;
      margin-bottom: .75rem;
      background: #f8fafc;
    }}
    .mail-card.bulk {{
      background: #ecfdf5;
      border-color: #6ee7b7;
    }}
    .mail-card-head {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: .5rem;
      margin-bottom: .45rem;
    }}
    .mail-card-label {{
      font-size: .82rem;
      font-weight: 600;
      color: var(--text);
    }}
    .mail-card.bulk .mail-card-label {{
      color: #065f46;
    }}
    .mail-copy-btn.bulk-copy {{
      background: #059669;
      color: #fff;
      box-shadow: none;
    }}
    .mail-copy-btn.bulk-copy:hover {{
      background: #047857;
      color: #fff;
    }}
    .mail-subject {{
      font-size: .78rem;
      color: var(--muted);
      margin-bottom: .4rem;
    }}
    .mail-body {{
      width: 100%;
      min-height: 10rem;
      max-height: 16rem;
      font-size: .78rem;
      line-height: 1.45;
      font-family: "Hiragino Sans", "Noto Sans JP", sans-serif;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: .55rem .65rem;
      background: #fff;
      resize: vertical;
      white-space: pre-wrap;
    }}
    .mail-btn {{
      border: none;
      background: #ecfdf5;
      color: #065f46;
      font-weight: 600;
      font-size: .8rem;
      padding: .45rem .85rem;
      border-radius: 8px;
      cursor: pointer;
      box-shadow: inset 0 0 0 1px #6ee7b7;
    }}
    .mail-btn:hover {{ background: #d1fae5; }}
    .top .mail-btn {{
      background: rgba(255,255,255,.18);
      color: #fff;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,.4);
    }}
    .top .mail-btn:hover {{ background: rgba(255,255,255,.28); }}
    .modal-backdrop {{
      position: absolute;
      inset: 0;
      background: rgba(15, 23, 42, .45);
    }}
    .modal-panel {{
      position: relative;
      background: #fff;
      border-radius: 12px;
      padding: 1.1rem 1.25rem;
      width: min(520px, 100%);
      max-height: min(90vh, 720px);
      overflow: auto;
      box-shadow: 0 12px 40px rgba(0,0,0,.2);
    }}
    .modal-panel h3 {{ margin: 0 0 .75rem; font-size: 1rem; }}
    .modal-panel label {{
      display: block;
      font-size: .8rem;
      color: var(--muted);
      margin: .55rem 0 .25rem;
    }}
    .modal-panel select {{
      width: 100%;
      padding: .45rem .5rem;
      border-radius: 8px;
      border: 1px solid var(--border);
      font-size: .9rem;
    }}
    .insert-list-label {{
      margin-top: .85rem;
      font-size: .8rem;
      font-weight: 600;
      color: var(--text);
    }}
    .insert-list {{
      margin-top: .4rem;
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      max-height: 280px;
      overflow-y: auto;
    }}
    .insert-slot {{
      display: block;
      width: 100%;
      text-align: left;
      border: none;
      border-bottom: 1px dashed #e2e8f0;
      background: #f8fafc;
      color: var(--accent);
      font-size: .78rem;
      font-weight: 600;
      padding: .4rem .7rem;
      cursor: pointer;
    }}
    .insert-slot:hover {{ background: #ecfdf5; }}
    .insert-slot.selected {{
      background: #0f766e;
      color: #fff;
    }}
    .insert-visit {{
      padding: .45rem .7rem;
      border-bottom: 1px solid var(--border);
      font-size: .8rem;
      background: #fff;
    }}
    .insert-visit .meta {{
      color: var(--muted);
      font-size: .72rem;
      margin-top: .1rem;
    }}
    .insert-empty {{
      padding: .75rem;
      color: var(--muted);
      font-size: .8rem;
    }}
    .move-warnings {{
      margin-top: .75rem;
      padding: .65rem .75rem;
      border-radius: 8px;
      background: #fffbeb;
      border: 1px solid #f59e0b;
      color: #92400e;
      font-size: .8rem;
    }}
    .move-warnings[hidden] {{ display: none !important; }}
    .move-warnings ul {{
      margin: .35rem 0 0;
      padding-left: 1.1rem;
    }}
    .move-warnings li {{ margin: .15rem 0; }}
    .modal-actions {{
      display: flex;
      justify-content: flex-end;
      gap: .5rem;
      margin-top: 1rem;
    }}
    .modal-actions button {{
      border: none;
      border-radius: 8px;
      padding: .45rem .85rem;
      font-weight: 600;
      cursor: pointer;
      font-size: .85rem;
    }}
    .modal-actions .cancel {{ background: #f1f5f9; color: #334155; }}
    .modal-actions .ok {{ background: var(--accent); color: #fff; }}
    .modal-actions .ok.warn {{ background: #b45309; }}
    .modal-actions .ok:disabled {{
      opacity: .45;
      cursor: not-allowed;
    }}
    .nav-days {{
      display: flex;
      flex-wrap: wrap;
      gap: .4rem;
      padding-top: .65rem;
      margin-top: .5rem;
      border-top: 1px solid rgba(255,255,255,.28);
      width: 100%;
    }}
    .nav-days a {{
      text-decoration: none;
      font-size: .8rem;
      padding: .35rem .65rem;
      border-radius: 999px;
      background: rgba(255,255,255,.18);
      color: #fff;
      border: 1px solid rgba(255,255,255,.4);
    }}
    .nav-days a:hover {{
      background: rgba(255,255,255,.32);
      border-color: #fff;
      color: #fff;
    }}
    .api-status {{
      margin: .35rem 0 0;
      font-size: .75rem;
      opacity: .9;
    }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 1rem 1rem 3rem; }}
    .summary-card {{
      background: var(--card);
      border-radius: 12px;
      padding: 1rem 1.25rem;
      margin-bottom: 1.25rem;
      border: 1px solid var(--border);
    }}
    .summary-card h2 {{ margin: 0 0 .75rem; font-size: 1rem; }}
    .changelog-card {{
      background: var(--card);
      border-radius: 12px;
      padding: 1rem 1.25rem;
      margin-bottom: 1.25rem;
      border: 1px solid var(--border);
    }}
    .changelog-card h2 {{ margin: 0 0 .35rem; font-size: 1rem; }}
    .changelog-sheet {{
      background: var(--card);
      border-radius: 12px;
      padding: 1rem 1.25rem 2rem;
      border: 1px solid var(--border);
    }}
    .changelog-sheet[hidden] {{ display: none !important; }}
    .changelog-sheet h2 {{ margin: 0 0 .35rem; font-size: 1.1rem; }}
    .changelog-list {{
      margin: 0;
      padding-left: 1.4rem;
      font-size: .9rem;
      line-height: 1.5;
    }}
    .changelog-list li {{ margin: .55rem 0; }}
    .chip.cancelled {{
      text-decoration: line-through;
      opacity: .65;
    }}
    .sheet-tabs {{
      position: sticky;
      bottom: 0;
      z-index: 20;
      display: flex;
      gap: .25rem;
      padding: .35rem .75rem .45rem;
      background: #e2e8f0;
      border-top: 1px solid #cbd5e1;
      box-shadow: 0 -4px 12px rgba(15, 23, 42, .08);
    }}
    .sheet-tab {{
      border: 1px solid #94a3b8;
      border-bottom: none;
      background: #cbd5e1;
      color: #334155;
      border-radius: 8px 8px 0 0;
      padding: .4rem .9rem;
      font-size: .85rem;
      cursor: pointer;
    }}
    .sheet-tab.active {{
      background: #fff;
      font-weight: 700;
      color: #0f766e;
      border-color: #0f766e;
    }}
    .changelog-updated {{
      margin: 0 0 .6rem;
      font-size: .82rem;
      color: var(--muted);
    }}
    .changelog-card ul {{
      margin: 0;
      padding-left: 1.2rem;
      font-size: .82rem;
      line-height: 1.45;
    }}
    .changelog-card li {{ margin: .35rem 0; }}
    .day-edit-note {{
      margin: 0 1.25rem .75rem;
      padding: .4rem .7rem;
      background: #ecfdf5;
      border: 1px solid #a7f3d0;
      border-radius: 8px;
      color: #065f46;
      font-size: .82rem;
    }}
    .visit-caution {{
      margin: .75rem 1.25rem 1.1rem;
      padding: .75rem 1rem 1rem;
      background: #fffbeb;
      border: 1px solid #fbbf24;
      border-radius: 10px;
    }}
    .visit-caution h3 {{
      margin: 0 0 .35rem;
      font-size: .95rem;
      color: #92400e;
    }}
    .visit-caution-title {{
      margin: 0 0 .35rem;
      font-weight: 700;
    }}
    .visit-caution p {{
      margin: 0 0 .6rem;
      font-size: .88rem;
      line-height: 1.45;
    }}
    .visit-caution-img {{
      display: block;
      max-width: 100%;
      height: auto;
      border-radius: 8px;
      border: 1px solid #fde68a;
    }}
    table.summary {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
    table.summary th, table.summary td {{
      padding: .45rem .5rem;
      border-bottom: 1px solid var(--border);
      text-align: left;
    }}
    table.summary .num {{ text-align: center; }}
    .copy-btn {{
      border: none;
      background: #fff;
      color: var(--accent);
      font-weight: 600;
      font-size: .8rem;
      padding: .45rem .85rem;
      border-radius: 8px;
      cursor: pointer;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,.4);
    }}
    .top .copy-btn {{ background: rgba(255,255,255,.15); color: #fff; }}
    .copy-btn:hover {{ filter: brightness(.97); }}
    .copy-btn.secondary {{
      background: var(--bg);
      color: var(--accent);
      box-shadow: inset 0 0 0 1px var(--border);
    }}
    .copy-btn.ok {{ background: #d1fae5; color: #065f46; }}
    .day-card {{
      background: var(--card);
      border-radius: 14px;
      border: 1px solid var(--border);
      margin-bottom: 1.5rem;
      overflow: hidden;
    }}
    .day-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: .75rem;
      flex-wrap: wrap;
      padding: 1rem 1.25rem;
      background: #f8fafc;
      border-bottom: 1px solid var(--border);
      scroll-margin-top: var(--sticky-top, 9rem);
    }}
    .day-header h2 {{ margin: 0; font-size: 1.25rem; }}
    .day-actions {{ display: flex; flex-wrap: wrap; gap: .4rem; align-items: center; }}
    .print-btn {{
      border: none;
      background: #fff7ed;
      color: #9a3412;
      font-weight: 600;
      font-size: .8rem;
      padding: .45rem .85rem;
      border-radius: 8px;
      cursor: pointer;
      box-shadow: inset 0 0 0 1px #fdba74;
    }}
    .print-btn:hover {{ background: #ffedd5; }}
    .map-btn {{
      border: none;
      background: #ecfdf5;
      color: #065f46;
      font-weight: 600;
      font-size: .8rem;
      padding: .45rem .85rem;
      border-radius: 8px;
      cursor: pointer;
      box-shadow: inset 0 0 0 1px #6ee7b7;
    }}
    .map-btn:hover {{ background: #d1fae5; }}
    .top .print-btn {{
      background: rgba(255,255,255,.2);
      color: #fff;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,.45);
    }}
    .file-hint {{
      background: #fff7ed;
      border-bottom: 1px solid #fdba74;
      color: #7c2d12;
      padding: .65rem 1rem;
      font-size: .85rem;
    }}
    .file-hint strong {{ color: #9a3412; }}
    .print-only {{ display: none; }}
    .chip-row {{
      display: flex;
      flex-wrap: wrap;
      gap: .35rem;
      padding: .75rem 1.25rem;
      border-bottom: 1px dashed var(--border);
    }}
    .chip {{
      font-size: .75rem;
      padding: .25rem .55rem;
      border-radius: 6px;
      background: #eee;
    }}
    .chip.hanawa {{ background: var(--hanawa-bg); color: var(--hanawa); }}
    .chip.katayama {{ background: var(--katayama-bg); color: var(--katayama); }}
    .chip.torikoe {{ background: var(--torikoe-bg); color: var(--torikoe); }}
    .chip small {{ opacity: .85; }}
    .doctor-block {{ padding: 0 0 1rem; }}
    .doctor-block.hanawa {{ border-left: 4px solid var(--hanawa); }}
    .doctor-block.katayama {{ border-left: 4px solid var(--katayama); }}
    .doctor-block.torikoe {{ border-left: 4px solid var(--torikoe); }}
    .doctor-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: .5rem;
      flex-wrap: wrap;
      padding: .85rem 1.25rem .5rem;
    }}
    .doctor-head h3 {{ margin: 0; font-size: .95rem; color: var(--muted); font-weight: 600; }}
    .table-wrap {{ overflow-x: auto; padding: 0 1rem; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: .82rem;
    }}
    th, td {{
      padding: .5rem .45rem;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
      text-align: left;
    }}
    th {{ background: #f8fafc; font-weight: 600; white-space: nowrap; }}
    tr.medical td {{ background: #fffbeb; }}
    tr.visit-cancelled td:not(.row-tools) {{
      text-decoration: line-through;
      color: #94a3b8;
    }}
    tr.visit-cancelled td.name .visit-cancel-line {{
      text-decoration: line-through;
      color: #94a3b8;
    }}
    tr.visit-cancelled td.name .visit-cancel-label {{
      text-decoration: none;
      color: #b45309;
      font-weight: 600;
      font-size: 0.85rem;
    }}
    tr.visit-cancelled td.name .id {{
      text-decoration: line-through;
      color: #94a3b8;
    }}
    .order, .order-h {{
      width: 1.4rem;
      max-width: 1.6rem;
      padding-left: .15rem;
      padding-right: .15rem;
      text-align: center;
      font-weight: 700;
      color: var(--muted);
      white-space: nowrap;
    }}
    .order-h {{ font-size: .75rem; }}
    .name-stack {{
      display: inline-flex;
      flex-direction: column;
      align-items: flex-start;
      line-height: 1.15;
    }}
    .name-kana {{
      font-size: .62rem;
      font-weight: 400;
      color: var(--muted);
      letter-spacing: .02em;
      line-height: 1.2;
    }}
    .name .id {{ color: var(--muted); font-size: .75rem; }}
    .eta {{ font-weight: 700; white-space: nowrap; color: var(--accent); }}
    .time-ng {{
      min-width: 9rem;
      max-width: 14rem;
      font-size: .78rem;
      font-weight: 600;
      color: #9f1239;
      line-height: 1.35;
    }}
    .time-ng:not(:empty) {{
      white-space: normal;
    }}
    .flags {{
      min-width: 4.5rem;
      max-width: 8rem;
      font-size: .78rem;
      font-weight: 600;
      color: #1e3a8a;
      white-space: normal;
      line-height: 1.35;
    }}
    .eta.eta-stale {{
      color: #b45309;
      opacity: .85;
    }}
    .eta.eta-stale::after {{
      content: " ※要再計算";
      font-weight: 500;
      font-size: .7rem;
    }}
    .print-btn:disabled,
    .copy-btn:disabled {{
      opacity: .45;
      cursor: not-allowed;
    }}
    .deadline {{ white-space: nowrap; }}
    .addr {{ min-width: 10rem; max-width: 14rem; word-break: break-all; }}
    .note {{ min-width: 10rem; color: var(--muted); font-size: .78rem; }}
    .route {{
      margin: 0;
      padding: .5rem 1.25rem 1rem;
      font-size: .8rem;
      color: var(--muted);
    }}
    .tsv-store {{
      position: absolute;
      left: -9999px;
      width: 1px;
      height: 1px;
      opacity: 0;
    }}
    .toast {{
      position: fixed;
      bottom: 1.25rem;
      right: 1.25rem;
      background: #111827;
      color: #fff;
      padding: .65rem 1rem;
      border-radius: 8px;
      font-size: .85rem;
      opacity: 0;
      pointer-events: none;
      transition: opacity .2s;
      z-index: 100;
    }}
    .toast.show {{ opacity: 1; }}
    @media (max-width: 640px) {{
      .day-header h2 {{ font-size: 1.1rem; }}
      td.addr {{ display: none; }}
    }}

    @page {{
      size: A4 portrait;
      margin: 10mm;
    }}
    @page landscape-sheet {{
      size: A4 landscape;
      margin: 8mm;
    }}

    @media print {{
      .no-print, .top, .toast, .tsv-store {{ display: none !important; }}
      body {{
        background: #fff;
        color: #000;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
      main {{ max-width: none; padding: 0; margin: 0; }}
      body:not(.print-include-summary) .summary-card {{ display: none !important; }}
      body.print-include-summary .day-card {{ display: none !important; }}
      /* iframe には対象カードだけ入るため print-one-day の非表示ルールは不要 */
      body.print-one-day .summary-card {{ display: none !important; }}

      .summary-card {{
        page-break-after: always;
        border: none;
        box-shadow: none;
        border-radius: 0;
      }}

      .day-card {{
        page-break-after: always;
        break-after: page;
        border: none;
        border-radius: 0;
        margin: 0;
        box-shadow: none;
        max-height: none;
        overflow: visible !important;
        display: block !important;
      }}
      .day-card:last-child {{ page-break-after: auto; }}
      /* 印刷は全日横向きA4（8/31など6件の日も他日と揃える） */
      .day-card {{ page: landscape-sheet; }}
      body.print-all-days .changelog-sheet {{
        page-break-before: always;
        break-before: page;
        page-break-after: auto;
        break-after: auto;
        page: landscape-sheet;
        display: block !important;
        border: none;
        box-shadow: none;
        border-radius: 0;
        margin: 0;
        padding: 0;
        max-height: none;
        overflow: visible !important;
      }}
      body.print-all-days .changelog-updated {{
        font-size: 10pt;
        color: #444;
        margin: 0 0 3mm;
      }}
      body.print-all-days .changelog-list {{
        font-size: 10pt;
        line-height: 1.45;
        padding-left: 6mm;
      }}
      body.print-all-days .changelog-list li {{ margin: 1.2mm 0; }}

      .print-sheet-title {{
        display: flex;
        flex-wrap: wrap;
        align-items: baseline;
        gap: .35rem .75rem;
        padding-bottom: 4mm;
        margin-bottom: 3mm;
        border-bottom: 2px solid #111;
        position: relative;
        padding-top: 5mm;
      }}
      .print-updated-at {{
        position: absolute;
        top: 0;
        right: 0;
        font-size: 9pt;
        color: #555;
        white-space: nowrap;
      }}
      .print-doc-title {{ font-size: 11pt; color: #333; }}
      .print-day {{ font-size: 19pt; font-weight: 800; }}
      .print-meta {{ font-size: 11pt; color: #444; margin-left: auto; }}

      .day-header {{ display: none; }}
      .chip-row {{ display: none; }}
      .visit-caution {{
        margin: 3mm 0 0;
        padding: 2.5mm 3mm;
        border: 1.5pt solid #b45309;
        background: #fffbeb !important;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
        page-break-inside: avoid;
        break-inside: avoid;
      }}
      .visit-caution h3 {{
        font-size: 11pt;
        color: #000;
        margin: 0 0 1.5mm;
      }}
      .visit-caution p {{
        font-size: 10pt;
        margin: 0 0 2mm;
        color: #111;
      }}
      .visit-caution-img {{
        max-height: 70mm;
        width: auto;
        max-width: 100%;
      }}

      .doctor-block {{
        padding: 0 0 2mm;
        border-left-width: 3px;
      }}
      .doctor-head {{
        padding: 1.5mm 0 1mm;
      }}
      .doctor-head h3 {{
        font-size: 11.5pt;
        color: #222;
      }}
      .table-wrap {{ padding: 0; overflow: visible; }}
      table {{
        font-size: 10pt;
        table-layout: fixed;
        width: 100%;
      }}
      .day-card.normal table {{ font-size: 10.5pt; }}
      table.summary {{ font-size: 10pt; }}
      th, td {{
        padding: 1.2mm 1mm;
        border: 1px solid #ccc;
        line-height: 1.3;
        vertical-align: top;
        overflow: visible;
        word-break: break-word;
        overflow-wrap: anywhere;
      }}
      th {{ background: #f0f0f0 !important; }}
      tr.medical td {{ background: #fff9e6 !important; }}
      .name .id {{ font-size: 8.5pt; }}
      .name-kana {{ font-size: 6.5pt; color: #555; }}
      th.order-h, td.order {{
        width: 2% !important;
        max-width: 1.4em;
        padding-left: 0.4mm !important;
        padding-right: 0.4mm !important;
        font-size: 9pt;
      }}
      td.name {{ width: 10%; }}
      td.deadline {{ width: 7%; }}
      td.eta {{ width: 6%; }}
      td.time-ng {{
        width: 16%;
        font-size: 9pt;
        font-weight: 700;
        color: #000;
        line-height: 1.3;
      }}
      td.flags {{
        width: 8%;
        font-size: 9pt;
        font-weight: 700;
        color: #000;
      }}
      td.addr {{ width: 14%; }}
      td.note {{ width: 20%; }}
      .eta {{ color: #000; font-weight: 700; white-space: nowrap; }}
      .addr {{
        font-size: 9pt;
        word-break: break-all;
      }}
      .day-card.dense .addr, .day-card.medium .addr {{
        font-size: 8.5pt;
      }}
      /* 備考のみ従来サイズのまま（他列は拡大） */
      .note {{
        display: table-cell;
        font-size: 6pt;
        color: #333;
        min-width: 0 !important;
        max-width: none;
        white-space: normal;
        overflow: visible;
        word-break: break-word;
        overflow-wrap: anywhere;
        line-height: 1.35;
      }}
      .day-card.dense .note, .day-card.medium .note {{
        font-size: 5.5pt;
      }}
      .day-card.dense .time-ng, .day-card.medium .time-ng {{
        font-size: 8.5pt;
      }}
      .route {{
        font-size: 9.5pt;
        padding: 1.5mm 0 0;
        margin: 0;
      }}
    }}
  </style>
</head>
<body>
  <div id="file-protocol-hint" class="file-hint no-print" hidden>
    エディタ内プレビューでは印刷できないことがあります。<strong>Chrome または Safari でこの HTML ファイルを開いて</strong>ください（Finder でダブルクリック → 開くアプリを選択）。
  </div>
  <header class="top">
    <div class="top-head">
      <h1>{html.escape(meta['title'])}</h1>
      <div class="top-head-tools">
        <div class="patient-search no-print" role="search">
          <label class="visually-hidden" for="patient-search-input">患者検索（氏名・ふりがな・ID）</label>
          <input
            type="search"
            id="patient-search-input"
            placeholder="氏名・ふりがな・ID で検索"
            autocomplete="off"
            spellcheck="false"
            enterkeyhint="search"
          />
          <div id="patient-search-results" class="patient-search-results" hidden></div>
        </div>
        <p class="last-updated no-print" id="last-updated-at" data-updated-at="{html.escape(updated_at_iso)}" aria-live="polite">
          <span class="last-updated-label">最終更新: {updated_at_html}</span>
        </p>
      </div>
    </div>
    <div class="top-actions">
      <button type="button" class="copy-btn" data-target="tsv-all" data-label="全往診ルート">全ルートコピー</button>
      <button type="button" class="copy-btn" data-target="tsv-patients" data-label="患者別一覧">患者一覧コピー</button>
      <button type="button" class="print-btn" id="print-all-days" onclick="OusehinPrint.all(); return false;">全日を印刷（日ごとA4）</button>
      <button type="button" class="mail-btn" id="btn-mail-driver">ドライバー連絡</button>
      <button type="button" class="mail-btn" id="btn-mail-doctor">医師連絡</button>
    </div>
    <nav class="nav-days no-print" aria-label="日付ジャンプ">
      {"".join(f'<a href="#day-{d["key"].replace("/", "").replace("(", "").replace(")", "")}-head">{html.escape(d["key"])}</a>' for d in data['days'])}
    </nav>
    <p id="api-status" class="api-status no-print" hidden>ローカルAPI接続済み</p>
  </header>
  <div id="edit-dirty-banner" class="edit-banner no-print" hidden>
    <span>未保存の変更があります。保存すると schedule.sqlite に反映され、リストを再生成します（反映後は再読み込み）。</span>
    <button type="button" class="save-btn" id="save-overrides-btn-banner">保存する</button>
  </div>
  <div id="edit-pending-apply" class="save-hint no-print" hidden>
    API未接続時は JSON をダウンロードしました。<code>python3 scripts/schedule_server.py</code> を起動してから保存するか、<code>apply_schedule_overrides.py</code> を実行してください。
  </div>
  <div id="save-hint" class="save-hint no-print" hidden></div>
  <main id="sheet-list">
    <section class="summary-card" id="summary-print">
      <div class="print-sheet-title print-only summary-print-title">
        <span class="print-updated-at print-only">最終更新: {updated_at_html}</span>
        <span class="print-doc-title">{html.escape(meta['title'])}</span>
        <span class="print-day">日別件数</span>
      </div>
      <h2>日別件数</h2>
      <table class="summary">
        <thead><tr><th>日付</th><th>花輪</th><th>片山</th><th>鳥越</th><th>合計</th></tr></thead>
        <tbody>{summary_html}</tbody>
      </table>
    </section>
    {day_sections}
  </main>
  {changelog_html}
  <nav class="sheet-tabs no-print" aria-label="シート">
    <button type="button" class="sheet-tab active" data-sheet="list">8月往診リスト</button>
    <button type="button" class="sheet-tab" data-sheet="changelog">変更履歴</button>
  </nav>
  <textarea id="tsv-all" class="tsv-store" readonly>{html.escape(all_visits_tsv(data['days']))}</textarea>
  <textarea id="tsv-patients" class="tsv-store" readonly>{html.escape(patients_to_tsv(data['patients']))}</textarea>
  <div id="toast" class="toast" role="status"></div>
  <div id="mail-modal" class="modal-root no-print" hidden>
    <div class="modal-backdrop" id="mail-modal-backdrop"></div>
    <div class="mail-modal-panel" role="dialog" aria-modal="true" aria-labelledby="mail-modal-title">
      <div class="mail-modal-head">
        <h3 id="mail-modal-title">連絡メール文</h3>
        <button type="button" class="mail-close" id="mail-modal-close">閉じる</button>
      </div>
      <div id="mail-modal-body"></div>
    </div>
  </div>
  <div id="route-map-modal" class="modal-root no-print" hidden>
    <div class="modal-backdrop" id="route-map-modal-backdrop"></div>
    <div class="mail-modal-panel route-map-panel" role="dialog" aria-modal="true" aria-labelledby="route-map-modal-title">
      <div class="mail-modal-head">
        <h3 id="route-map-modal-title">ルート地図</h3>
        <button type="button" class="mail-close" id="route-map-modal-close">閉じる</button>
      </div>
      <div class="route-map-wrap">
        <div id="route-map-canvas" role="img" aria-label="往診ルート地図"></div>
        <p id="route-map-status" class="map-status"></p>
      </div>
      <div id="route-map-modal-body"></div>
    </div>
  </div>
  <div id="move-day-modal" class="modal-root no-print" hidden>
    <div class="modal-backdrop" id="move-modal-backdrop"></div>
    <div class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="move-modal-title">
      <h3 id="move-modal-title">別の日へ移動</h3>
      <label for="move-day-select">移動先の日付</label>
      <select id="move-day-select"></select>
      <div id="move-doctor-wrap">
        <label for="move-doctor-select">医師</label>
        <select id="move-doctor-select"></select>
      </div>
      <div class="insert-list-label" id="insert-list-heading">移動先の往診順（挿入位置を選択）</div>
      <div id="move-insert-list" class="insert-list" role="listbox" aria-label="挿入位置"></div>
      <div id="move-warnings" class="move-warnings" hidden>
        <strong>確認が必要な点</strong>
        <ul id="move-warnings-list"></ul>
      </div>
      <div class="modal-actions">
        <button type="button" class="cancel" id="move-modal-cancel">キャンセル</button>
        <button type="button" class="ok" id="move-modal-ok" disabled>移動する</button>
      </div>
    </div>
  </div>
  <script>
    (function() {{
      if (location.protocol === 'file:') {{
        var hint = document.getElementById('file-protocol-hint');
        if (hint) hint.hidden = false;
      }}
    }})();

    (function() {{
      function syncStickyOffset() {{
        var bar = document.querySelector('header.top');
        if (!bar) return;
        var h = bar.getBoundingClientRect().height;
        document.documentElement.style.setProperty('--sticky-top', (Math.ceil(h) + 8) + 'px');
      }}
      syncStickyOffset();
      window.addEventListener('resize', syncStickyOffset);
      window.addEventListener('load', syncStickyOffset);
    }})();

    function showToast(msg) {{
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), 2200);
    }}
    window.showToast = showToast;
    async function copyText(text, label) {{
      try {{
        await navigator.clipboard.writeText(text);
      }} catch (e) {{
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.left = '0';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
      }}
      showToast('コピーしました: ' + label);
    }}
    window.copyText = copyText;
    async function copyFrom(id, label) {{
      const el = document.getElementById(id);
      if (!el) return;
      await copyText(el.value, label);
    }}
    document.querySelectorAll('.copy-btn').forEach(function(btn) {{
      btn.addEventListener('click', function() {{
        if (!btn.dataset.target) return;
        copyFrom(btn.dataset.target, btn.dataset.label || '表');
        btn.classList.add('ok');
        setTimeout(function() {{ btn.classList.remove('ok'); }}, 1200);
      }});
    }});

    (function setupMailModal() {{
      window.OUSEHIN_MAIL_CARDS = {mail_json};
      function openMailModal(kind) {{
        var data = (window.OUSEHIN_MAIL_CARDS || {{}})[kind] || [];
        var title = kind === 'driver' ? 'ドライバー連絡メール文' : '医師連絡メール文';
        document.getElementById('mail-modal-title').textContent = title;
        var body = document.getElementById('mail-modal-body');
        body.innerHTML = '';
        if (!data.length) {{
          body.innerHTML = '<p>表示できるメール文がありません。</p>';
        }} else {{
          var currentGroup = null;
          data.forEach(function(card, idx) {{
            if (card.group !== currentGroup) {{
              currentGroup = card.group;
              var gh = document.createElement('div');
              gh.className = 'mail-group';
              gh.textContent = currentGroup;
              body.appendChild(gh);
            }}
            var wrap = document.createElement('div');
            wrap.className = 'mail-card' + (card.kind_card === 'bulk' ? ' bulk' : '');
            var copyLabel = card.kind_card === 'bulk' ? '一括コピー' : '本文をコピー';
            wrap.innerHTML =
              '<div class="mail-card-head">' +
                '<span class="mail-card-label"></span>' +
                '<button type="button" class="copy-btn secondary mail-copy-btn' +
                  (card.kind_card === 'bulk' ? ' bulk-copy' : '') +
                '">' + copyLabel + '</button>' +
              '</div>' +
              '<div class="mail-subject"></div>' +
              '<textarea class="mail-body" readonly></textarea>';
            wrap.querySelector('.mail-card-label').textContent = card.label || '';
            wrap.querySelector('.mail-subject').textContent = '件名: ' + (card.subject || '');
            wrap.querySelector('.mail-body').value = card.body || '';
            wrap.querySelector('.mail-copy-btn').addEventListener('click', function() {{
              copyText(card.body || '', card.label || 'メール文');
            }});
            body.appendChild(wrap);
          }});
        }}
        document.getElementById('mail-modal').hidden = false;
      }}
      function closeMailModal() {{
        document.getElementById('mail-modal').hidden = true;
      }}
      var btnDrv = document.getElementById('btn-mail-driver');
      var btnDoc = document.getElementById('btn-mail-doctor');
      if (btnDrv) btnDrv.addEventListener('click', function() {{ openMailModal('driver'); }});
      if (btnDoc) btnDoc.addEventListener('click', function() {{ openMailModal('doctor'); }});
      var closeBtn = document.getElementById('mail-modal-close');
      var backdrop = document.getElementById('mail-modal-backdrop');
      if (closeBtn) closeBtn.addEventListener('click', closeMailModal);
      if (backdrop) backdrop.addEventListener('click', closeMailModal);
    }})();

    document.querySelectorAll('.print-btn[data-print-day]').forEach(function(btn) {{
      btn.addEventListener('click', function() {{
        if (btn.dataset.label) showToast('印刷: ' + btn.dataset.label);
      }});
    }});

    var printAll = document.getElementById('print-all-days');
    if (printAll) {{
      printAll.addEventListener('click', function() {{
        showToast('印刷ダイアログを開きます（各日1枚）');
      }});
    }}

    document.querySelectorAll('.sheet-tab').forEach(function(tab) {{
      tab.addEventListener('click', function() {{
        var sheet = tab.getAttribute('data-sheet');
        document.querySelectorAll('.sheet-tab').forEach(function(t) {{
          t.classList.toggle('active', t === tab);
        }});
        var listEl = document.getElementById('sheet-list');
        var logEl = document.getElementById('sheet-changelog');
        if (listEl) listEl.hidden = sheet !== 'list';
        if (logEl) logEl.hidden = sheet !== 'changelog';
      }});
    }});
  </script>
  <script>
    window.OUSEHIN_API_BASE = "http://127.0.0.1:8765";
    window.OUSEHIN_PERIOD_KEY = "2026-08";
  </script>
  <script>
/*__SCHEDULE_DND_JS__*/
  </script>
  <script>
/*__SCHEDULE_ROUTE_MAP_JS__*/
  </script>
</body>
</html>"""


def _day_tsv(day: dict) -> str:
    parts = []
    for doc in day["doctors"]:
        parts.append(visits_to_tsv(doc["visits"], day["key"], doc["name"]))
    return "\n".join(parts)


def load_constraints_json() -> dict:
    if not CONSTRAINTS_PATH.exists():
        return {
            "version": 1,
            "capacity": {"花輪": 8, "片山": 11, "鳥越": 11},
            "day_capacity": {},
            "doctor_pref_labels": {
                "hanawa": "花輪",
                "katayama": "片山",
                "torikoe": "鳥越",
                "auto": "auto",
            },
            "patients": {},
        }
    return json.loads(CONSTRAINTS_PATH.read_text(encoding="utf-8"))


def inject_dnd_js(html_text: str) -> str:
    js_path = Path(__file__).with_name("schedule_dnd.js")
    js = js_path.read_text(encoding="utf-8")
    html_text = html_text.replace("/*__SCHEDULE_DND_JS__*/", js)
    map_js = Path(__file__).with_name("schedule_route_map.js").read_text(encoding="utf-8")
    return html_text.replace("/*__SCHEDULE_ROUTE_MAP_JS__*/", map_js)


def inject_constraints(html_text: str, constraints: dict, search_index: list[dict]) -> str:
    blob = json.dumps(constraints, ensure_ascii=False)
    idx_blob = json.dumps(search_index, ensure_ascii=False)
    tag = (
        f"<script>window.OUSEHIN_CONSTRAINTS = {blob};</script>\n"
        f"  <script>window.OUSEHIN_SEARCH_INDEX = {idx_blob};</script>\n"
        f"  <script>\n/*__SCHEDULE_DND_JS__*/"
    )
    return html_text.replace("<script>\n/*__SCHEDULE_DND_JS__*/", tag, 1)


def main() -> None:
    text = MD_PATH.read_text(encoding="utf-8")
    data = parse_md(text)
    constraints = load_constraints_json()
    kana_by_id = load_kana_by_chart_id()
    search_index = build_search_index(data, kana_by_id)
    updated_at_iso, updated_at_label = load_last_updated_at()
    html_out = inject_dnd_js(
        inject_constraints(
            render_html(
                data,
                kana_by_id,
                updated_at_iso=updated_at_iso,
                updated_at_label=updated_at_label,
            ),
            constraints,
            search_index,
        )
    )
    OUT_PATH.write_text(html_out, encoding="utf-8")
    n = len(constraints.get("patients") or {})
    print(f"Wrote {OUT_PATH} ({len(data['days'])} days, {n} constraint patients)")


if __name__ == "__main__":
    main()
