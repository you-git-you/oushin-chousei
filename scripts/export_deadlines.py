# -*- coding: utf-8 -*-
"""期限一覧を exports/ に Markdown / CSV で出力する。

判断方針（docs/decisions.md）:
  - 医療: 30日後
  - 介護・自費・不明: 2ヶ月後月末
  - 未突合は一覧に残し「要確認」とする
  - 終了患者は除外
  - 最終実施日は completed / needs_review のみ（未来の scheduled は除外）
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DB_PATH,
    EXPORTS_DIR,
    deadline_for,
    insurance_label_ja,
)


def connect() -> sqlite3.Connection:
    """読み取り用にDBを開く。"""
    if not DB_PATH.exists():
        raise SystemExit(f"DBがありません。先に import_from_csv.py を実行してください: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_deadline_rows(conn: sqlite3.Connection, as_of: date, cutoff: date) -> list[dict]:
    """期限が cutoff 以前の患者行を返す。"""
    # 最終実施日
    sql = """
    SELECT
        p.patient_id,
        p.name,
        p.name_kana,
        p.insurance_type,
        p.care_level,
        p.status AS patient_status,
        p.main_staff,
        p.matched,
        p.visit_code,
        MAX(e.performed_at) AS last_performed,
        (
            SELECT e2.source FROM events e2
            WHERE e2.patient_id = p.patient_id
              AND e2.status IN ('completed', 'needs_review')
              AND e2.performed_at IS NOT NULL
              AND e2.performed_at <= ?
              AND e2.performed_at = (
                  SELECT MAX(e3.performed_at) FROM events e3
                  WHERE e3.patient_id = p.patient_id
                    AND e3.status IN ('completed', 'needs_review')
                    AND e3.performed_at IS NOT NULL
                    AND e3.performed_at <= ?
              )
            ORDER BY
              CASE e2.source
                WHEN 'oushin_rireki' THEN 0
                WHEN 'clinic' THEN 1
                WHEN 'yoyaku' THEN 2
                ELSE 9
              END
            LIMIT 1
        ) AS last_source
    FROM patients p
    JOIN events e
      ON e.patient_id = p.patient_id
     AND e.status IN ('completed', 'needs_review')
     AND e.performed_at IS NOT NULL
     AND e.performed_at <= ?
    WHERE p.status != 'ended'
    GROUP BY p.patient_id
    """
    as_of_s = as_of.isoformat()
    rows = conn.execute(sql, (as_of_s, as_of_s, as_of_s)).fetchall()

    # 休止理由
    pause_reasons = {
        r["patient_id"]: r["reason"]
        for r in conn.execute(
            """
            SELECT patient_id, reason FROM status_changes
            WHERE change_type = 'pause'
            ORDER BY effective_date DESC
            """
        )
    }

    out: list[dict] = []
    for r in rows:
        last = date.fromisoformat(r["last_performed"])
        insurance = r["insurance_type"] or "unknown"
        dl = deadline_for(last, insurance)
        if dl > cutoff:
            continue
        out.append(
            {
                "patient_id": r["patient_id"],
                "name": r["name"],
                "name_kana": r["name_kana"] or "",
                "insurance_type": insurance,
                "insurance_ja": insurance_label_ja(insurance),
                "care_level": r["care_level"] or "",
                "patient_status": r["patient_status"],
                "main_staff": r["main_staff"] or "",
                "matched": r["matched"],
                "visit_code": r["visit_code"] or "",
                "last_performed": last,
                "last_source": r["last_source"] or "",
                "deadline": dl,
                "days_left": (dl - as_of).days,
                "paused": r["patient_status"] == "paused",
                "pause_reason": pause_reasons.get(r["patient_id"]) or "",
                "needs_review": r["matched"] == 0 or insurance == "unknown",
            }
        )

    out.sort(
        key=lambda x: (
            x["deadline"],
            {"iryo": 0, "jihi": 1, "kaigo": 2, "unknown": 3}.get(x["insurance_type"], 9),
            x["name_kana"] or x["name"],
        )
    )
    return out


def source_label(source: str) -> str:
    """ソースコードを日本語表示へ。"""
    return {
        "oushin_rireki": "往診履歴",
        "yoyaku": "往診予約履歴",
        "clinic": "クリニック受診",
    }.get(source, source)


def fmt(d: date) -> str:
    """表示用日付。"""
    return f"{d.year}/{d.month}/{d.day}"


def md_table(items: list[dict]) -> str:
    """Markdown表を組み立てる。"""
    lines = [
        "| # | 氏名 | ふりがな | 区分 | 介護度 | 最終往診/受診 | 根拠 | 期限 | 残日数 | メイン担当 | 備考 |",
        "|---:|---|---|---|---|---|---|---|---:|---|---|",
    ]
    for i, r in enumerate(items, 1):
        remarks = []
        if r["paused"]:
            remarks.append("休止中")
        if r["patient_status"] == "scheduled":
            remarks.append("台帳:予定")
        if r["needs_review"]:
            remarks.append("要確認")
        if r["days_left"] < 0:
            remarks.append(f"期限超過{abs(r['days_left'])}日")
        note = " / ".join(remarks)
        lines.append(
            f"| {i} | {r['name']} | {r['name_kana']} | **{r['insurance_ja']}** | "
            f"{r['care_level'] or '—'} | {fmt(r['last_performed'])} | "
            f"{source_label(r['last_source'])} | **{fmt(r['deadline'])}** | "
            f"{r['days_left']} | {r['main_staff'] or '—'} | {note} |"
        )
    return "\n".join(lines)


def md_list(items: list[dict]) -> str:
    """箇条書きリスト。"""
    lines = []
    for r in items:
        flags = []
        if r["paused"]:
            flags.append("休止")
        if r["needs_review"]:
            flags.append("要確認")
        if r["days_left"] < 0:
            flags.append("超過")
        flag_s = f"（{'・'.join(flags)}）" if flags else ""
        kd = f"／{r['care_level']}" if r["care_level"] else ""
        lines.append(
            f"- **{r['name']}**（{r['name_kana']}）｜区分: **{r['insurance_ja']}**{kd}"
            f"｜最終: {fmt(r['last_performed'])}（{source_label(r['last_source'])}）"
            f"｜期限: **{fmt(r['deadline'])}**｜残{r['days_left']}日{flag_s}"
        )
    return "\n".join(lines)


def write_markdown(rows: list[dict], as_of: date, cutoff: date, path: Path) -> None:
    """期限一覧 Markdown を書き出す。"""
    overdue = [r for r in rows if r["deadline"] < as_of]
    medical = [r for r in rows if r["insurance_type"] == "iryo"]
    selfpay = [r for r in rows if r["insurance_type"] == "jihi"]
    kaigo = [r for r in rows if r["insurance_type"] == "kaigo"]
    unknown = [r for r in rows if r["insurance_type"] == "unknown"]
    paused = [r for r in rows if r["paused"]]
    aug31 = [r for r in rows if r["deadline"] == cutoff]
    kaigo_ok = [r for r in kaigo if r["deadline"] >= as_of]

    lines = [
        f"# 往診期限一覧（〜{cutoff.year}年{cutoff.month}月{cutoff.day}日）",
        "",
        f"> 作成基準日: {fmt(as_of)} ｜ 対象: **{fmt(cutoff)}まで**に往診が必要な方 ｜ 出力元: SQLite正本",
        "",
        "## 適用ルール",
        "",
        "| 区分 | 期限の考え方 |",
        "|---|---|",
        "| **介護** | 最終の往診または受診日の **2ヶ月後の月末** |",
        "| **自費** | 介護と同じ（2ヶ月後の月末） |",
        "| **医療** | 最終の往診または受診日の **ちょうど30日後** |",
        "",
        "最終実施日は DB の `events`（status = completed / needs_review）のみを使用。"
        "未来の予定は含めない。台帳状態が終了の方は除外。未突合は「要確認」として掲載。",
        "",
        "## サマリー",
        "",
        "| 項目 | 人数 |",
        "|---|---:|",
        f"| **期限対象（本リスト）** | **{len(rows)}** |",
        f"|　うち期限超過 | {len(overdue)} |",
        f"|　うち期限がちょうど締切日 | {len(aug31)} |",
        f"| 区分：介護 | {len(kaigo)} |",
        f"| 区分：医療 | {len(medical)} |",
        f"| 区分：自費 | {len(selfpay)} |",
        f"| 区分：不明（要確認） | {len(unknown)} |",
        f"| 休止中 | {len(paused)} |",
        "",
        "---",
        "",
        "## 1. 期限超過（優先対応）",
        "",
        f"**{len(overdue)}名**",
        "",
        md_table(overdue) if overdue else "（該当なし）",
        "",
        "---",
        "",
        "## 2. 医療（30日ルール）",
        "",
        f"**{len(medical)}名**",
        "",
        md_list(medical) if medical else "（該当なし）",
        "",
    ]
    if medical:
        lines += [md_table(medical), ""]
    lines += [
        "---",
        "",
        "## 3. 自費（2ヶ月後月末）",
        "",
        f"**{len(selfpay)}名**",
        "",
        md_list(selfpay) if selfpay else "（該当なし）",
        "",
    ]
    if selfpay:
        lines += [md_table(selfpay), ""]
    lines += [
        "---",
        "",
        "## 4. 介護（2ヶ月後月末）",
        "",
        f"介護全体 **{len(kaigo)}名**（期限内 **{len(kaigo_ok)}名**）",
        "",
        md_list(kaigo_ok) if kaigo_ok else "（該当なし）",
        "",
    ]
    if unknown:
        lines += [
            "---",
            "",
            "## 5. 区分不明・要確認",
            "",
            md_list(unknown),
            "",
            md_table(unknown),
            "",
        ]
    lines += [
        "---",
        "",
        "## 参考：休止中（本リスト内）",
        "",
        f"**{len(paused)}名**",
        "",
    ]
    for r in paused:
        reason = (r["pause_reason"] or "").replace("\n", " ")
        if len(reason) > 90:
            reason = reason[:90] + "…"
        lines.append(
            f"- **{r['name']}**（{r['insurance_ja']}）期限 {fmt(r['deadline'])} — {reason}"
        )
    lines += [
        "",
        "---",
        "",
        "## 全体一覧（期限順）",
        "",
        md_table(rows),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_csv(rows: list[dict], path: Path) -> None:
    """期限一覧 CSV を書き出す。"""
    fields = [
        "patient_id",
        "name",
        "name_kana",
        "insurance_ja",
        "insurance_type",
        "care_level",
        "last_performed",
        "last_source",
        "deadline",
        "days_left",
        "main_staff",
        "patient_status",
        "paused",
        "needs_review",
        "visit_code",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            row = dict(r)
            row["last_performed"] = r["last_performed"].isoformat()
            row["deadline"] = r["deadline"].isoformat()
            row["paused"] = int(r["paused"])
            row["needs_review"] = int(r["needs_review"])
            w.writerow(row)


def main() -> None:
    """エントリポイント。"""
    parser = argparse.ArgumentParser(description="往診期限一覧を出力する")
    parser.add_argument(
        "--as-of",
        default=date.today().isoformat(),
        help="基準日 YYYY-MM-DD（残日数計算用）",
    )
    parser.add_argument(
        "--cutoff",
        default="2026-08-31",
        help="期限の上限 YYYY-MM-DD",
    )
    args = parser.parse_args()
    as_of = date.fromisoformat(args.as_of)
    cutoff = date.fromisoformat(args.cutoff)

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        rows = fetch_deadline_rows(conn, as_of, cutoff)
        md_path = EXPORTS_DIR / f"往診期限一覧_{cutoff.strftime('%Y%m%d')}まで.md"
        csv_path = EXPORTS_DIR / f"往診期限一覧_{cutoff.strftime('%Y%m%d')}まで.csv"
        write_markdown(rows, as_of, cutoff, md_path)
        write_csv(rows, csv_path)
        print(f"rows: {len(rows)}")
        print(f"markdown: {md_path}")
        print(f"csv: {csv_path}")
        by_ins = {}
        for r in rows:
            by_ins[r["insurance_ja"]] = by_ins.get(r["insurance_ja"], 0) + 1
        print("by insurance:", by_ins)
        print("overdue:", sum(1 for r in rows if r["days_left"] < 0))
        print("needs_review:", sum(1 for r in rows if r["needs_review"]))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
