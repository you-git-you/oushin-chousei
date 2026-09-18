#!/usr/bin/env python3
"""往診リスト編集用ローカル API（schedule.sqlite + 静的 HTML）。

  python3 scripts/schedule_server.py
  open http://127.0.0.1:8765/

エンドポイント:
  GET  /api/health
  GET  /api/schedule/{period_key}
  PUT  /api/schedule/{period_key}?regenerate=1
  POST /api/schedule/{period_key}/regenerate
"""

from __future__ import annotations

import json
import mimetypes
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
EXPORTS = ROOT / "exports"
DEFAULT_HTML = EXPORTS / "8月往診リスト_2026.html"
HOST = "127.0.0.1"
DEFAULT_PORT = 8765

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from schedule.config import DEFAULT_PERIOD_KEY  # noqa: E402
from schedule.repository import overrides_document_to_routes, routes_to_overrides_document  # noqa: E402
from schedule.sqlite_store import SqliteScheduleRepository, init_db  # noqa: E402

GENERATE = SCRIPTS / "generate_august_schedule.py"
BUILD_HTML = SCRIPTS / "build_august_schedule_html.py"
OVERRIDES_JSON = EXPORTS / "schedule_overrides.json"


def run_regenerate() -> tuple[bool, str]:
    for script in (GENERATE, BUILD_HTML):
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "unknown error")[-3000:]
            return False, detail
    return True, "ok"


class ScheduleAPIHandler(BaseHTTPRequestHandler):
    server_version = "OusehinScheduleAPI/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            self._json(200, {"ok": True, "period": DEFAULT_PERIOD_KEY})
            return

        prefix = "/api/schedule/"
        if path.startswith(prefix):
            period_key = unquote(path[len(prefix) :].strip("/"))
            if not period_key or "/" in period_key:
                self._json(400, {"error": "invalid period_key"})
                return
            store = SqliteScheduleRepository()
            if not store.has_routes(period_key):
                self._json(404, {"error": "not_found", "period_key": period_key})
                return
            self._json(200, store.export_overrides_document(period_key))
            return

        self._serve_static(path)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        prefix = "/api/schedule/"
        if not path.startswith(prefix):
            self._json(404, {"error": "not_found"})
            return
        period_key = unquote(path[len(prefix) :].strip("/"))
        if not period_key or "/" in period_key:
            self._json(400, {"error": "invalid period_key"})
            return

        data = self._read_json_body()
        if not data:
            self._json(400, {"error": "invalid_json"})
            return
        routes = overrides_document_to_routes(data)
        if not routes:
            self._json(400, {"error": "empty_routes"})
            return

        init_db()
        store = SqliteScheduleRepository()
        store.replace_routes(
            period_key,
            routes,
            source="html_api",
            note="schedule_server PUT",
        )
        mirror = routes_to_overrides_document(period_key, routes)
        OVERRIDES_JSON.write_text(
            json.dumps(mirror, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        visits = sum(len(ids) for dr in routes.values() for ids in dr.values())
        out = {
            "ok": True,
            "period_key": period_key,
            "days": len(routes),
            "visits": visits,
            "regenerated": False,
        }

        qs = parse_qs(parsed.query)
        regen = qs.get("regenerate", ["1"])[0] not in ("0", "false", "no")
        if regen:
            ok, detail = run_regenerate()
            out["regenerated"] = ok
            if not ok:
                self._json(422, {"error": "regenerate_failed", "detail": detail, **out})
                return

        self._json(200, out)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        suffix = "/regenerate"
        prefix = "/api/schedule/"
        if not path.startswith(prefix) or not path.endswith(suffix):
            self._json(404, {"error": "not_found"})
            return
        middle = path[len(prefix) : -len(suffix)].strip("/")
        period_key = unquote(middle)
        if not period_key:
            self._json(400, {"error": "invalid period_key"})
            return
        ok, detail = run_regenerate()
        if not ok:
            self._json(422, {"error": "regenerate_failed", "detail": detail})
            return
        self._json(200, {"ok": True, "period_key": period_key, "regenerated": True})

    def _serve_static(self, path: str) -> None:
        if path in ("", "/"):
            file_path = DEFAULT_HTML
        else:
            rel = unquote(path.lstrip("/"))
            file_path = (EXPORTS / rel).resolve()
            try:
                file_path.relative_to(EXPORTS.resolve())
            except ValueError:
                self.send_error(403)
                return
        if not file_path.is_file():
            self.send_error(404)
            return
        content = file_path.read_bytes()
        ctype, _ = mimetypes.guess_type(str(file_path))
        if not ctype:
            ctype = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(content)))
        self._send_cors()
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="往診リスト ローカル API")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    init_db()
    server = ThreadingHTTPServer((args.host, args.port), ScheduleAPIHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Serving {EXPORTS} at {url}")
    print(f"Schedule API period default: {DEFAULT_PERIOD_KEY}")
    print("Stop with Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
