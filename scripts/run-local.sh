#!/usr/bin/env bash
# Start the local API, runtime worker loop, and web dev server.
# Ctrl-C stops only the processes this script started.

set +x
set -euo pipefail

cd "$(dirname "$0")/.."

port_busy() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

busy=0
if port_busy 8000; then
  echo "port 8000 is already in use" >&2
  busy=1
fi
if port_busy 5173; then
  echo "port 5173 is already in use" >&2
  busy=1
fi
if [[ "$busy" -eq 1 ]]; then
  exit 1
fi

if [[ ! -x ./.venv/bin/python ]]; then
  echo "missing ./.venv/bin/python" >&2
  exit 1
fi

if [[ -f ./.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
fi

export PYTHONPATH=src

api_pid=""
worker_pid=""
web_pid=""

stop_pid() {
  local pid="$1"
  local child
  [[ -n "$pid" ]] || return 0
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    stop_pid "$child"
  done
  kill -TERM "$pid" 2>/dev/null || true
}

cleanup() {
  trap - EXIT INT TERM
  stop_pid "$api_pid"
  stop_pid "$worker_pid"
  stop_pid "$web_pid"
  if [[ -n "$api_pid" || -n "$worker_pid" || -n "$web_pid" ]]; then
    wait "$api_pid" "$worker_pid" "$web_pid" 2>/dev/null || true
  fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

./.venv/bin/python -m planes.backend.api \
  --database ./local-run.sqlite3 \
  --host 127.0.0.1 \
  --port 8000 &
api_pid=$!

./.venv/bin/python -m planes.backend.worker \
  --database ./local-run.sqlite3 \
  --engine runtime \
  --loop &
worker_pid=$!

(
  cd apps/web
  pnpm dev
) &
web_pid=$!

printf '%s\n' \
  "api    http://127.0.0.1:8000" \
  "worker runtime --loop" \
  "web    http://127.0.0.1:5173" \
  "sqlite ./local-run.sqlite3"

wait "$api_pid" "$worker_pid" "$web_pid"
