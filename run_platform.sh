#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cleanup() { kill 0; }
trap cleanup EXIT INT TERM
: "${BACKEND_PORT:=8001}"
: "${VITE_API_BASE_URL:=http://127.0.0.1:${BACKEND_PORT}/api}"
export BACKEND_PORT VITE_API_BASE_URL
PYTHON="python"
if [ ! -x "$ROOT/backend/venv/bin/python" ]; then python -m venv "$ROOT/backend/venv"; fi
PYTHON="$ROOT/backend/venv/bin/python"
"$PYTHON" -c 'import fastapi, uvicorn, rapidfuzz' >/dev/null 2>&1 || "$PYTHON" -m pip install -r "$ROOT/backend/requirements.txt"
[ -d "$ROOT/frontend/node_modules" ] || npm --prefix "$ROOT/frontend" ci
: "${DEPARTMENT_API_PORT:=9101}"
(cd "$ROOT/backend" && "$PYTHON" -m alembic upgrade head)
(cd "$ROOT/backend" && "$PYTHON" -m uvicorn app.department_api.main:app --port "$DEPARTMENT_API_PORT") &
(cd "$ROOT/backend" && "$PYTHON" -m uvicorn main:app --reload --port "$BACKEND_PORT") &
(cd "$ROOT/frontend" && npm run dev -- --host 127.0.0.1 --port 5173) &
wait
