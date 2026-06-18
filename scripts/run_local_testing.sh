#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export ENVIRONMENT="${ENVIRONMENT:-test}"

if [ -d .venv ]; then
  PY=".venv/bin/python"
elif [ -x /opt/venv/bin/python ]; then
  PY="/opt/venv/bin/python"
else
  PY="python3"
fi

echo "=============================================="
echo " TMS local testing (ENVIRONMENT=$ENVIRONMENT)"
echo " No ngrok — backend + frontend on localhost"
echo "=============================================="
echo ""

echo "Initializing database (if needed)..."
"$PY" scripts/init_local_db.py

echo ""
echo "Backend:  http://127.0.0.1:8000"
echo "Frontend: http://localhost:3000  (run: cd frontend && npm start)"
echo ""

exec "$PY" -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
