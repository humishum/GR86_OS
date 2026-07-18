#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  local status=$?
  trap - EXIT INT TERM

  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill -TERM -- "-$pid" 2>/dev/null || true
    fi
  done

  [[ -n "$FRONTEND_PID" ]] && wait "$FRONTEND_PID" 2>/dev/null || true
  [[ -n "$BACKEND_PID" ]] && wait "$BACKEND_PID" 2>/dev/null || true
  exit "$status"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ ! -x "$ROOT_DIR/.venv/bin/race-review" ]]; then
  printf 'Missing Python environment. Run: cd %q && uv sync --extra dev\n' "$ROOT_DIR" >&2
  exit 1
fi

if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  printf 'Missing frontend dependencies. Run: cd %q && npm install\n' "$ROOT_DIR/frontend" >&2
  exit 1
fi

export RACE_REVIEW_MEDIA_ROOTS="${RACE_REVIEW_MEDIA_ROOTS:-$ROOT_DIR/../data}"

(
  cd "$ROOT_DIR"
  exec setsid .venv/bin/race-review serve
) &
BACKEND_PID=$!

(
  cd "$ROOT_DIR/frontend"
  exec setsid npm run dev -- --host 127.0.0.1 --port 5173
) &
FRONTEND_PID=$!

printf 'Race Review: http://127.0.0.1:5173/\nAPI:         http://127.0.0.1:8000/\n'
printf 'Press Ctrl+C to stop both servers.\n'

set +e
wait -n "$BACKEND_PID" "$FRONTEND_PID"
status=$?
set -e

printf 'A development server exited (status %d); stopping both.\n' "$status" >&2
exit "$status"
