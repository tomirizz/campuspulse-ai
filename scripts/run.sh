#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.11 .venv
    uv pip sync --python .venv/bin/python requirements.lock
  else
    python3 -c 'import sys; assert sys.version_info >= (3,11), "Install Python 3.11+ or uv first"'
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.lock
  fi
fi
if [ ! -f .env ]; then cp .env.example .env; fi
if [ "${1:-}" = "--local-ai" ]; then exec .venv/bin/python scripts/local_start.py; fi
echo "CampusPulse: http://127.0.0.1:${PORT:-8765}"
exec .venv/bin/python -m uvicorn campuspulse.server:app --host 127.0.0.1 --port "${PORT:-8765}"
