#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
cd "$BACKEND_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN=python
fi

if [ ! -d .venv ]; then
  "$PYTHON_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

export APP_ENV="${APP_ENV:-development}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///./epic.db}"
export SECRET_KEY="${SECRET_KEY:-local-development-secret-change-before-production}"
export AUTO_CREATE_SCHEMA="false"
export ENFORCE_AUTHORIZATION="${ENFORCE_AUTHORIZATION:-false}"
export ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-[\"http://127.0.0.1:8000\",\"http://localhost:8000\"]}"
export TRUSTED_HOSTS="${TRUSTED_HOSTS:-[\"127.0.0.1\",\"localhost\",\"testserver\"]}"

alembic upgrade head
printf '\nEPIC is starting at http://127.0.0.1:8000\n'
printf 'Press Ctrl+C to stop it.\n\n'
exec uvicorn app.main:app --host 127.0.0.1 --port 8000
