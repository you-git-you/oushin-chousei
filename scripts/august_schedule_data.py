# -*- coding: utf-8 -*-
"""8月往診リスト MD から患者と予定日を抽出する。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from common import ROOT, normalize_chart_id

AUG_MD = ROOT / "exports" / "8月往診リスト_2026.md"
OUT_JSON = ROOT / "records" / "data" / "august_2026_schedule.json"


def load_august_schedule_from_md() -> dict[str, dict]:
    """patient_id -> {name, august_dates, last_planned}"""
    text = AUG_MD.read_text(encoding="utf-8")
    current_iso: str | None = None
    by_pid: dict[str, dict] = {}
    in_schedule_day = False

    for line in text.splitlines():
        day_m = re.match(r"^## 8/(\d+)\(", line)
        if day_m:
            current_iso = f"2026-08-{int(day_m.group(1)):02d}"
            in_schedule_day = True
            continue
        if line.startswith("## ") and not day_m:
            if not re.match(r"^## 8/\d+\(", line):
                in_schedule_day = False
                current_iso = None
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
        pid: str | None = None
        name: str | None = None
        for i, c in enumerate(cells):
            if not re.fullmatch(r"b\d+", c):
                continue
            pid = c
            if i > 0:
                prev = cells[i - 1]
                if prev and not re.fullmatch(r"b\d+", prev) and not prev.isdigit():
                    name = prev.replace(" ", "")
            break
        if not pid:
            continue
        eta = cells[7] if len(cells) > 7 else ""
        if eta.strip() == "キャンセル":
            continue
        entry = by_pid.setdefault(
            pid,
            {"patient_id": pid, "name": name or "", "august_dates": []},
        )
        if name and not entry["name"]:
            entry["name"] = name
        if current_iso not in entry["august_dates"]:
            entry["august_dates"].append(current_iso)

    for entry in by_pid.values():
        entry["august_dates"].sort()
        entry["last_planned"] = entry["august_dates"][-1] if entry["august_dates"] else None
    return by_pid


def main() -> None:
    by_pid = load_august_schedule_from_md()
    payload = {
        "version": 1,
        "source": str(AUG_MD.relative_to(ROOT)),
        "note": "8月往診リスト掲載者（実施見込み高）。期限計算は最終予定日を参照可。",
        "patients": sorted(by_pid.values(), key=lambda x: x["patient_id"]),
    }
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT_JSON} ({len(by_pid)} patients)")


if __name__ == "__main__":
    main()
