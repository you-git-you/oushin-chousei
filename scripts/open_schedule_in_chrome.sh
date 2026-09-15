#!/bin/bash
# ローカル API を起動し、ブラウザで往診リストを開く
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${OUSEHIN_PORT:-8765}"
URL="http://127.0.0.1:${PORT}/"

if ! curl -sf "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
  echo "Starting schedule_server on ${URL}"
  python3 "$ROOT/scripts/schedule_server.py" --port "$PORT" &
  SERVER_PID=$!
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -sf "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
      break
    fi
    sleep 0.3
  done
  if ! curl -sf "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    echo "サーバー起動に失敗しました" >&2
    kill "$SERVER_PID" 2>/dev/null || true
    exit 1
  fi
  echo "PID $SERVER_PID (Ctrl+C で停止する場合は kill $SERVER_PID)"
fi

open -a "Google Chrome" "$URL" 2>/dev/null || open "$URL"
