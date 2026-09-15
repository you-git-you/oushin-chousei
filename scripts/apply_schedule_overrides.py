#!/usr/bin/env python3
"""HTMLで保存した schedule_overrides.json を DB に反映し、MD/HTMLを再生成する。

使い方:
  python3 scripts/apply_schedule_overrides.py
  python3 scripts/apply_schedule_overrides.py ~/Downloads/schedule_overrides.json
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from schedule.config import DEFAULT_PERIOD_KEY
from schedule.repository import overrides_document_to_routes, routes_to_overrides_document
from schedule.sqlite_store import SqliteScheduleRepository, init_db

OVERRIDES = ROOT / "exports/schedule_overrides.json"


def main() -> None:
    if len(sys.argv) > 1:
        src = Path(sys.argv[1]).expanduser().resolve()
        if not src.exists():
            raise SystemExit(f"not found: {src}")
        data = json.loads(src.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("routes"):
            raise SystemExit("JSON に routes がありません")
        OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
        if src != OVERRIDES.resolve():
            shutil.copy2(src, OVERRIDES)
            print(f"Copied {src} -> {OVERRIDES}")
        else:
            print(f"Using {OVERRIDES}")
    elif not OVERRIDES.exists():
        raise SystemExit(
            f"{OVERRIDES} がありません。HTMLの「正本に保存（JSON）」でダウンロードし、"
            "このパスに置くか引数で指定してください。"
        )
    else:
        print(f"Using {OVERRIDES}")

    data = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    routes = overrides_document_to_routes(data)
    if not routes:
        raise SystemExit(
            f"{OVERRIDES} の routes が空です。HTMLで並び替え後に「正本に保存（JSON）」し、"
            "そのファイルを exports/ に置いてから再実行してください。"
        )

    period_key = str(data.get("period_key") or DEFAULT_PERIOD_KEY)
    init_db()
    store = SqliteScheduleRepository()
    store.replace_routes(
        period_key,
        routes,
        source="html_json",
        note=str(OVERRIDES.name),
    )
    print(f"Saved routes to db/schedule.sqlite ({period_key})")

    mirror = routes_to_overrides_document(period_key, routes)
    OVERRIDES.write_text(json.dumps(mirror, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    gen = ROOT / "scripts/generate_august_schedule.py"
    build = ROOT / "scripts/build_august_schedule_html.py"
    subprocess.check_call([sys.executable, str(gen)], cwd=str(ROOT))
    subprocess.check_call([sys.executable, str(build)], cwd=str(ROOT))
    print("Done: schedule DB + MD + HTML updated.")


if __name__ == "__main__":
    main()
