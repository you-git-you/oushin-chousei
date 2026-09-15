#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""9月往診対象一覧 Markdown → 閲覧用 HTML。"""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
MD_PATH = ROOT / "records" / "9月往診対象一覧_2026.md"
OUT_PATH = ROOT / "exports" / "9月往診対象一覧_2026.html"


def strip_md_bold(s: str) -> str:
    return re.sub(r"\*\*([^*]+)\*\*", r"\1", s).strip()


def parse_table_row(line: str) -> list[str] | None:
    line = line.strip()
    if not line.startswith("|") or re.match(r"^\|[\s\-:|]+\|$", line):
        return None
    return [strip_md_bold(c.strip()) for c in line.strip("|").split("|")]


def parse_md(text: str) -> dict:
    lines = text.splitlines()
    intro: list[str] = []
    medical: list[dict[str, str]] = []
    home: list[dict[str, str]] = []
    clinic: list[dict[str, str]] = []
    tsv_home = ""
    tsv_clinic = ""
    title = "2026年9月 往診対象一覧"

    section: str | None = None
    home_headers: list[str] | None = None
    clinic_headers: list[str] | None = None
    in_tsv = False
    tsv_kind: str | None = None
    tsv_lines: list[str] = []

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("# "):
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            heading = line[3:].strip()
            if heading.startswith("8月往診リストの医療"):
                section = "medical"
            elif heading == "一覧（往診）":
                section = "home"
                home_headers = None
            elif heading.startswith("一覧（通院"):
                section = "clinic"
                clinic_headers = None
            elif heading.startswith("スプレッドシート用"):
                section = "tsv"
            elif heading == "除外（休止・終了）":
                section = "footer"
            else:
                section = None
            in_tsv = False
            continue

        if section is None and line and not line.startswith("|"):
            if line.startswith("**") or line.startswith("基準日"):
                intro.append(strip_md_bold(line))

        if section == "medical":
            cells = parse_table_row(line)
            if not cells or cells[0] == "patient_id":
                continue
            if len(cells) >= 5:
                medical.append(
                    {
                        "patient_id": cells[0],
                        "name": cells[1],
                        "kana": cells[2],
                        "august": cells[3],
                        "deadline": cells[4],
                    }
                )
            elif len(cells) >= 4:
                medical.append(
                    {
                        "patient_id": cells[0],
                        "name": cells[1],
                        "kana": "",
                        "august": cells[2],
                        "deadline": cells[3],
                    }
                )

        if section == "home":
            cells = parse_table_row(line)
            if not cells:
                continue
            if cells[0] == "patient_id":
                home_headers = cells
                continue
            if home_headers and len(cells) >= len(home_headers):
                home.append(dict(zip(home_headers, cells)))

        if section == "clinic":
            cells = parse_table_row(line)
            if not cells:
                continue
            if cells[0] == "patient_id":
                clinic_headers = cells
                continue
            if clinic_headers and len(cells) >= len(clinic_headers):
                clinic.append(dict(zip(clinic_headers, cells)))

        if section == "tsv":
            if line.startswith("### 往診"):
                tsv_kind = "home"
                tsv_lines = []
                in_tsv = False
                continue
            if line.startswith("### 通院"):
                if tsv_kind == "home" and tsv_lines:
                    tsv_home = "\n".join(tsv_lines)
                tsv_kind = "clinic"
                tsv_lines = []
                in_tsv = False
                continue
            if line.strip().startswith("```"):
                in_tsv = not in_tsv
                if not in_tsv:
                    if tsv_kind == "clinic":
                        tsv_clinic = "\n".join(tsv_lines)
                    elif tsv_kind == "home" and tsv_lines:
                        tsv_home = "\n".join(tsv_lines)
                continue
            if in_tsv and line:
                tsv_lines.append(line)

    if not tsv_home and tsv_kind == "home" and tsv_lines:
        tsv_home = "\n".join(tsv_lines)
    if not tsv_clinic and tsv_kind == "clinic" and tsv_lines:
        tsv_clinic = "\n".join(tsv_lines)

    return {
        "title": title,
        "intro": intro,
        "medical": medical,
        "home": home,
        "clinic": clinic,
        "tsv_home": tsv_home,
        "tsv_clinic": tsv_clinic,
    }


def insurance_slug(label: str) -> str:
    mapping = {"医療": "iryo", "介護": "kaigo", "自費": "jihi", "不明": "unknown"}
    return mapping.get(label.strip(), "unknown")


def insurance_badge(label: str) -> str:
    slug = insurance_slug(label)
    text = label.strip() or "不明"
    return f'<span class="ins ins-{slug}" title="保険区分">{html.escape(text)}</span>'


def status_badge(status: str) -> str:
    s = (status or "").strip()
    if not s:
        return ""
    if s == "休止":
        cls = "status-paused"
    elif s == "終了":
        cls = "status-ended"
    else:
        cls = "status-other"
    return f'<span class="status-badge {cls}">{html.escape(s)}</span>'


def category_badge(cat: str) -> str:
    if "休止" in cat:
        cls = "cat-badge-paused"
    elif "終了" in cat:
        cls = "cat-badge-ended"
    elif "8月予定（医療）" in cat:
        cls = "cat-badge-aug-med"
    elif "7月実施済" in cat:
        cls = "cat-badge-july"
    elif "要確認" in cat:
        cls = "cat-badge-confirm"
    elif "未実施" in cat:
        cls = "cat-badge-deferred"
    elif "通院" in cat:
        cls = "cat-badge-clinic"
    else:
        cls = "cat-badge-other"
    return f'<span class="cat-badge {cls}">{html.escape(cat)}</span>'


def row_class(insurance: str, category: str, priority: str, deadline: str) -> str:
    """行の見た目は付けず、フィルタ用 data-* のみ（呼び出し側で設定）。"""
    return "data-row"


def count_by_insurance(rows: list[dict[str, str]], key: str = "区分") -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        ins = r.get(key, "不明") or "不明"
        counts[ins] = counts.get(ins, 0) + 1
    return counts


def format_date_short(iso: str) -> str:
    if not iso or iso in ("—", "要確認"):
        return iso or "—"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso)
    if m:
        return f"{int(m.group(2))}/{int(m.group(3))}"
    return iso


def _list_section(ins_label: str, category: str) -> str:
    if ins_label == "医療":
        return "医療"
    tail_cats = ("要確認", "7月未実施", "休止（参照）", "終了（参照）")
    if category in tail_cats or "休止" in category or "終了" in category:
        return "その他"
    if ins_label == "介護":
        return "介護"
    if ins_label == "自費":
        return "自費"
    return "その他"


HOME_TABLE_COLS = 10

HOME_TABLE_HEAD = """
            <tr>
              <th>ID</th><th>氏名</th><th>フリガナ</th><th>区分</th><th>状態</th><th>最終往診</th><th>8月予定</th>
              <th>期限</th><th>担当</th><th>備考</th>
            </tr>"""

CLINIC_TABLE_HEAD = """
            <tr>
              <th>ID</th><th>氏名</th><th>フリガナ</th><th>区分</th><th>状態</th><th>最終受診</th><th>期限</th>
              <th>担当</th><th>備考</th>
            </tr>"""


def render_table_rows(
    rows: list[dict[str, str]], *, kind: str, show_sections: bool = True
) -> str:
    out: list[str] = []
    prev_section: str | None = None
    for r in rows:
        if kind == "home":
            cat = r.get("カテゴリ", "")
            dl = r.get("期限", "")
            ins_label = r.get("区分", "不明")
            ins = insurance_slug(ins_label)
            section = _list_section(ins_label, cat)
            if show_sections and section != prev_section:
                out.append(
                    f'<tr class="section-row" data-section="{html.escape(section)}">'
                    f'<td colspan="{HOME_TABLE_COLS}"><strong>{html.escape(section)}</strong></td></tr>'
                )
                prev_section = section
            cls = row_class(ins_label, cat, "", dl)
            op_status = r.get("状態", "")
            kana = r.get("フリガナ", "")
            search = " ".join(
                [
                    r.get("patient_id", ""),
                    r.get("氏名", ""),
                    kana,
                    r.get("メイン担当", ""),
                    ins_label,
                    op_status,
                ]
            )
            out.append(
                f"""<tr class="{cls}" data-category="{html.escape(cat)}"
                  data-insurance="{html.escape(ins)}"
                  data-status="{html.escape(op_status)}"
                  data-search="{html.escape(search.lower())}">
  <td class="mono">{html.escape(r.get("patient_id", ""))}</td>
  <td class="name"><strong>{html.escape(r.get("氏名", ""))}</strong></td>
  <td class="kana">{html.escape(kana)}</td>
  <td>{insurance_badge(ins_label)}</td>
  <td>{status_badge(op_status)}</td>
  <td class="date">{html.escape(format_date_short(r.get("最終往診日", "")))}</td>
  <td class="date">{html.escape(format_date_short(r.get("8月予定", "")))}</td>
  <td class="deadline">{html.escape(format_date_short(dl))}</td>
  <td>{html.escape(r.get("メイン担当", ""))}</td>
  <td class="note">{html.escape(r.get("備考", ""))}</td>
</tr>"""
            )
        else:
            cat = r.get("カテゴリ", "")
            dl = r.get("期限", "")
            ins_label = r.get("区分", "不明")
            ins = insurance_slug(ins_label)
            cls = row_class(ins_label, cat, "", dl)
            op_status = r.get("状態", "")
            kana = r.get("フリガナ", "")
            search = " ".join(
                [
                    r.get("patient_id", ""),
                    r.get("氏名", ""),
                    kana,
                    ins_label,
                    op_status,
                ]
            )
            out.append(
                f"""<tr class="{cls}" data-category="{html.escape(cat)}"
                  data-insurance="{html.escape(ins)}"
                  data-status="{html.escape(op_status)}"
                  data-search="{html.escape(search.lower())}">
  <td class="mono">{html.escape(r.get("patient_id", ""))}</td>
  <td class="name"><strong>{html.escape(r.get("氏名", ""))}</strong></td>
  <td class="kana">{html.escape(kana)}</td>
  <td>{insurance_badge(ins_label)}</td>
  <td>{status_badge(op_status)}</td>
  <td class="date">{html.escape(format_date_short(r.get("最終受診日", "")))}</td>
  <td class="deadline">{html.escape(format_date_short(dl))}</td>
  <td>{html.escape(r.get("メイン担当", ""))}</td>
  <td class="note">{html.escape(r.get("備考", ""))}</td>
</tr>"""
            )
    return "\n".join(out)


def render_html(data: dict, *, updated_label: str) -> str:
    med_count = len(data["medical"])
    home_iryo = [r for r in data["home"] if r.get("区分") == "医療"]
    med_ref_ids = {m["patient_id"] for m in data["medical"]}
    home_iryo_ids = {r["patient_id"] for r in home_iryo}
    med_ok = med_count == 6 and len(home_iryo) == 6 and home_iryo_ids == med_ref_ids

    home_by_pid = {r["patient_id"]: r for r in data["home"]}
    med_ref_rows: list[dict[str, str]] = []
    for m in data["medical"]:
        row = home_by_pid.get(m["patient_id"])
        if row:
            med_ref_rows.append(row)

    med_table_body = render_table_rows(med_ref_rows, kind="home", show_sections=True)

    home_count = len(data["home"])
    clinic_count = len(data["clinic"])
    home_ins = count_by_insurance(data["home"])
    clinic_ins = count_by_insurance(data["clinic"])
    intro_html = "".join(f"<p>{html.escape(p)}</p>" for p in data["intro"])

    med_status = (
        f"医療往診 {med_count}名（8月リストと一致）"
        if med_ok
        else f"⚠ 医療人数要確認: 参照表{med_count}名 / 往診一覧{len(home_iryo)}名"
    )

    def ins_stat_line(counts: dict[str, int]) -> str:
        order = ["医療", "介護", "自費", "不明"]
        parts = [f"{k}{counts.get(k, 0)}" for k in order if counts.get(k)]
        return "・".join(parts)

    home_ins_line = ins_stat_line(home_ins)
    clinic_ins_line = ins_stat_line(clinic_ins)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(data["title"])}</title>
  <style>
    :root {{
      --bg: #f7f8fa;
      --card: #fff;
      --text: #2c3340;
      --muted: #6b7280;
      --border: #e5e7eb;
      --accent: #4b6a8a;
      --sticky: 56px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Yu Gothic UI", sans-serif;
      font-size: 14px;
      line-height: 1.5;
      color: var(--text);
      background: var(--bg);
    }}
    header.top {{
      position: sticky;
      top: 0;
      z-index: 100;
      background: #3d4f63;
      color: #f9fafb;
      padding: 14px 20px;
      box-shadow: 0 1px 3px rgba(0,0,0,.08);
    }}
    header.top h1 {{ margin: 0 0 4px; font-size: 1.35rem; font-weight: 700; }}
    header.top .meta {{ font-size: 0.85rem; opacity: 0.92; }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      padding: 12px 20px;
      background: var(--card);
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: var(--sticky);
      z-index: 90;
    }}
    .toolbar input[type="search"] {{
      flex: 1;
      min-width: 180px;
      max-width: 320px;
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      font-size: 14px;
    }}
    .toolbar select {{
      padding: 8px 10px;
      border-radius: 8px;
      border: 1px solid var(--border);
    }}
    .stats {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .stat {{
      background: #f3f4f6;
      color: #4b5563;
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 500;
    }}
    .stat.clinic {{ background: #f3f4f6; color: #4b5563; }}
    button.copy-btn {{
      padding: 8px 14px;
      border: none;
      border-radius: 8px;
      background: var(--accent);
      color: #fff;
      font-weight: 600;
      cursor: pointer;
      font-size: 13px;
    }}
    button.copy-btn:hover {{ filter: brightness(1.05); }}
    main {{ max-width: 1400px; margin: 0 auto; padding: 16px 20px 48px; }}
    .intro {{
      background: var(--card);
      border-radius: 12px;
      padding: 14px 18px;
      margin-bottom: 16px;
      border: 1px solid var(--border);
      color: var(--muted);
    }}
    .intro p {{ margin: 0.35em 0; }}
    section.panel {{
      background: var(--card);
      border-radius: 12px;
      border: 1px solid var(--border);
      margin-bottom: 20px;
      overflow: hidden;
    }}
    section.panel h2 {{
      margin: 0;
      padding: 12px 16px;
      font-size: 1rem;
      background: #f8fafc;
      border-bottom: 1px solid var(--border);
    }}
    .table-wrap {{ overflow-x: auto; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      padding: 8px 10px;
      text-align: left;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }}
    thead th {{
      background: #f1f5f9;
      font-weight: 600;
      white-space: nowrap;
    }}
    tr.data-row:hover {{ background: #fafbfc; }}
    td.mono {{ font-family: ui-monospace, monospace; font-size: 12px; color: var(--muted); }}
    td.kana {{ font-size: 12px; color: var(--muted); white-space: nowrap; }}
    td.note {{ max-width: 280px; font-size: 12px; color: var(--muted); }}
    td.date {{ white-space: nowrap; }}
    td.deadline {{ font-weight: 500; }}
    .ins {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 500;
      border: 1px solid transparent;
      line-height: 1.4;
    }}
    .ins-iryo {{ background: #eceef3; color: #525b6e; border-color: #d8dce4; }}
    .ins-kaigo {{ background: #e9eeeb; color: #4d5c54; border-color: #d5ddd8; }}
    .ins-jihi {{ background: #f0ece8; color: #6b6158; border-color: #e0d9d0; }}
    .ins-unknown {{ background: #f0f1f3; color: #6b7280; border-color: #e2e4e8; }}
    .cat-badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 11px;
      white-space: nowrap;
      font-weight: 500;
      line-height: 1.4;
      border: 1px solid transparent;
    }}
    .cat-badge-aug-med {{ background: #ebe9f0; color: #5c5768; border-color: #dcd8e6; }}
    .cat-badge-july {{ background: #e8edf2; color: #4f5f6f; border-color: #d5dde5; }}
    .cat-badge-confirm {{ background: #f2efe8; color: #6b6355; border-color: #e5e0d4; }}
    .cat-badge-deferred {{ background: #f0eaea; color: #6f5555; border-color: #e4d8d8; }}
    .cat-badge-clinic {{ background: #e9eeeb; color: #4d5c54; border-color: #d5ddd8; }}
    .cat-badge-other {{ background: #f0f1f3; color: #6b7280; border-color: #e2e4e8; }}
    .cat-badge-paused {{ background: #f2efe8; color: #6b6355; border-color: #e5e0d4; }}
    .cat-badge-ended {{ background: #f0eaea; color: #6f5555; border-color: #e4d8d8; }}
    .status-badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 600;
      border: 1px solid transparent;
    }}
    .status-paused {{ background: #f2efe8; color: #6b6355; border-color: #e5e0d4; }}
    .status-ended {{ background: #f0eaea; color: #6f5555; border-color: #e4d8d8; }}
    .status-other {{ background: #f0f1f3; color: #6b7280; border-color: #e2e4e8; }}
    tr.section-row td {{
      background: #eef2f6;
      font-size: 12px;
      color: #4b5563;
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px 20px;
      align-items: center;
      padding: 12px 16px;
      margin-bottom: 16px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      font-size: 12px;
    }}
    .legend-group {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }}
    .legend-title {{ font-weight: 700; color: var(--muted); margin-right: 4px; }}
    .legend-note {{ width: 100%; color: var(--muted); font-size: 12px; margin: 0; }}
    .stat.iryo {{ background: #eceef3; color: #525b6e; }}
    .stat.kaigo {{ background: #e9eeeb; color: #4d5c54; }}
    .stat.jihi {{ background: #f0ece8; color: #6b6158; }}
    .med-panel-note {{
      margin: 0;
      padding: 8px 16px 0;
      font-size: 12px;
      color: var(--muted);
    }}
    .med-panel-note.ok {{ color: #5c6b58; font-weight: 500; }}
    .hidden-row {{ display: none; }}
    .tsv-store {{ position: absolute; left: -9999px; height: 0; width: 0; opacity: 0; }}
    #toast {{
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #1e293b;
      color: #fff;
      padding: 10px 16px;
      border-radius: 8px;
      opacity: 0;
      transition: opacity 0.2s;
      z-index: 200;
      pointer-events: none;
    }}
    #toast.show {{ opacity: 1; }}
    @media (max-width: 768px) {{
      th:nth-child(n+8), td:nth-child(n+8) {{ display: none; }}
      td.note {{ display: none; }}
    }}
    @media print {{
      header.top, .toolbar, .copy-btn, #toast {{ display: none !important; }}
      body {{ background: #fff; }}
      section.panel {{ break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <header class="top">
    <h1>{html.escape(data["title"])}</h1>
    <div class="meta">更新: {html.escape(updated_label)} ｜ 往診 {home_count}名（{html.escape(home_ins_line)}）／ 通院 {clinic_count}名（{html.escape(clinic_ins_line)}）</div>
  </header>
  <div class="toolbar">
    <input type="search" id="q" placeholder="氏名・フリガナ・ID・担当で検索…" autocomplete="off">
    <select id="ins-filter" aria-label="保険区分">
      <option value="">すべての区分</option>
      <option value="iryo">医療</option>
      <option value="kaigo">介護</option>
      <option value="jihi">自費</option>
      <option value="unknown">不明</option>
    </select>
    <div class="stats">
      <span class="stat iryo">医療 {home_ins.get("医療", 0)}</span>
      <span class="stat kaigo">介護 {home_ins.get("介護", 0)}</span>
      <span class="stat jihi">自費 {home_ins.get("自費", 0)}</span>
      <span class="stat clinic">通院 {clinic_count}</span>
    </div>
    <button type="button" class="copy-btn" data-target="tsv-home" data-label="往診TSV">往診TSVコピー</button>
    <button type="button" class="copy-btn" data-target="tsv-clinic" data-label="通院TSV">通院TSVコピー</button>
  </div>
  <main>
    <div class="intro">{intro_html}</div>

    <div class="legend" aria-label="凡例">
      <div class="legend-group">
        <span class="legend-title">保険区分</span>
        {insurance_badge("医療")}
        {insurance_badge("介護")}
        {insurance_badge("自費")}
        {insurance_badge("不明")}
      </div>
      <div class="legend-group">
        <span class="legend-title">状態</span>
        {status_badge("休止")}
        {status_badge("終了")}
      </div>
      <p class="legend-note">※ <strong>9月往診調整の「医療」は6名</strong>（8月往診リストの医療往診）。通院の医療は通院一覧で管理します。並びは<strong>医療→介護→自費→その他</strong>（各あいうえお順）。</p>
    </div>

    <section class="panel" id="medical-ref">
      <h2>8月往診リストの医療（{med_count}名）— 9月期限の目安</h2>
      <p class="med-panel-note {"ok" if med_ok else ""}">{html.escape(med_status)}</p>
      <div class="table-wrap">
        <table id="table-medical" class="list-table">
          <thead>{HOME_TABLE_HEAD}
          </thead>
          <tbody>{med_table_body}</tbody>
        </table>
      </div>
    </section>

    <section class="panel" id="home-list">
      <h2>一覧（往診）</h2>
      <div class="table-wrap">
        <table id="table-home" class="list-table">
          <thead>{HOME_TABLE_HEAD}
          </thead>
          <tbody>
            {render_table_rows(data["home"], kind="home")}
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel" id="clinic-list">
      <h2>一覧（通院・クリニック受診）</h2>
      <div class="table-wrap">
        <table id="table-clinic" class="list-table">
          <thead>{CLINIC_TABLE_HEAD}
          </thead>
          <tbody>
            {render_table_rows(data["clinic"], kind="clinic")}
          </tbody>
        </table>
      </div>
    </section>
  </main>

  <textarea id="tsv-home" class="tsv-store" readonly>{html.escape(data["tsv_home"])}</textarea>
  <textarea id="tsv-clinic" class="tsv-store" readonly>{html.escape(data["tsv_clinic"])}</textarea>
  <div id="toast" role="status"></div>

  <script>
    (function() {{
      var stickyTop = document.querySelector('header.top');
      function syncSticky() {{
        if (!stickyTop) return;
        document.documentElement.style.setProperty('--sticky', Math.ceil(stickyTop.offsetHeight) + 'px');
      }}
      syncSticky();
      window.addEventListener('resize', syncSticky);

      function showToast(msg) {{
        var t = document.getElementById('toast');
        t.textContent = msg;
        t.classList.add('show');
        setTimeout(function() {{ t.classList.remove('show'); }}, 2200);
      }}

      document.querySelectorAll('.copy-btn').forEach(function(btn) {{
        btn.addEventListener('click', async function() {{
          var el = document.getElementById(btn.dataset.target);
          if (!el) return;
          try {{
            await navigator.clipboard.writeText(el.value);
          }} catch (e) {{
            el.select();
            document.execCommand('copy');
          }}
          showToast('コピーしました: ' + (btn.dataset.label || ''));
        }});
      }});

      var q = document.getElementById('q');
      var ins = document.getElementById('ins-filter');
      function applyFilter() {{
        var term = (q.value || '').trim().toLowerCase();
        var insVal = ins.value;
        document.querySelectorAll('tr.data-row, tr.section-row').forEach(function(tr) {{
          if (tr.classList.contains('section-row')) {{
            tr.classList.remove('hidden-row');
            return;
          }}
          var okSearch = !term || (tr.dataset.search || '').indexOf(term) >= 0;
          var okIns = !insVal || tr.dataset.insurance === insVal;
          tr.classList.toggle('hidden-row', !(okSearch && okIns));
        }});
      }}
      q.addEventListener('input', applyFilter);
      ins.addEventListener('change', applyFilter);
    }})();
  </script>
</body>
</html>"""


def main() -> None:
    if not MD_PATH.is_file():
        raise SystemExit(f"Markdown がありません: {MD_PATH}")
    text = MD_PATH.read_text(encoding="utf-8")
    data = parse_md(text)
    mtime = datetime.fromtimestamp(MD_PATH.stat().st_mtime, tz=ZoneInfo("Asia/Tokyo"))
    updated = mtime.strftime("%Y/%m/%d %H:%M")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render_html(data, updated_label=updated), encoding="utf-8")
    home_iryo = sum(1 for r in data["home"] if r.get("区分") == "医療")
    print(
        f"Wrote {OUT_PATH} (home={len(data['home'])} clinic={len(data['clinic'])} "
        f"med_ref={len(data['medical'])} home_iryo={home_iryo})"
    )


if __name__ == "__main__":
    main()
