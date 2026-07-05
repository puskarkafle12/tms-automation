#!/usr/bin/env bash
set -euo pipefail

: "${PGDATA:=/var/lib/postgresql/data}"
: "${DB_USER:=pk}"
: "${DB_PASSWORD:=pk}"
: "${DB_HOST:=127.0.0.1}"
: "${DB_NAME:=stock}"
: "${FRONTEND_SEED_USER:=admin}"
: "${FRONTEND_SEED_PASSWORD:=admin}"
: "${NGROK_AUTHTOKEN:=}"
: "${NGROK_DOMAIN:=}"
: "${ZROK_ENV_TOKEN:=}"
: "${ZROK_API_ENDPOINT:=https://api-v2.zrok.io}"
: "${ZROK_SHARE_LABEL:=TMS Automation zrok}"
: "${ZROK_RESERVED_NAME:=tmsautomationlive}"
: "${ENVIRONMENT:=test}"

export DB_USER DB_PASSWORD DB_HOST DB_NAME FRONTEND_SEED_USER FRONTEND_SEED_PASSWORD ENVIRONMENT

PUBLIC_URL_FILE=/tmp/public-url.txt
PUBLIC_URLS_FILE=/tmp/public-urls.txt
TUNNEL_LOG=/tmp/tunnel.log
TUNNEL_PID=""
ZROK_LOG=/tmp/zrok.log
ZROK_PID=""
NGROK_WAIT_PID=""
ZROK_WAIT_PID=""

touch_public_urls_file() {
  : > "$PUBLIC_URLS_FILE"
}

append_public_url() {
  local label="$1"
  local url="$2"
  local note="${3:-}"
  {
    echo "$label|$url|$note"
  } >> "$PUBLIC_URLS_FILE"
}

print_public_url_banner() {
  local label="${1:-URL}"
  local url="${2:-}"
  local note="${3:-}"
  echo "$url" > "$PUBLIC_URL_FILE"
  append_public_url "$label" "$url" "$note"
  echo ""
  echo "=============================================="
  echo " $label: $url"
  if [ -n "$note" ]; then
    echo " NOTE: $note"
  fi
  echo "=============================================="
  echo ""
}

wait_for_ngrok_url() {
  local url=""
  for _ in $(seq 1 60); do
    url="$(curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null \
      | python3 -c "import json,sys; data=json.load(sys.stdin); tunnels=data.get('tunnels') or []; print(next((t['public_url'] for t in tunnels if t.get('public_url','').startswith('https')), ''))" 2>/dev/null \
      || true)"
    if [ -n "$url" ]; then
      print_public_url_banner "ngrok" "$url" "Permanent ngrok URL for your account."
      return 0
    fi
    sleep 1
  done
  if [ -n "${NGROK_DOMAIN:-}" ]; then
    domain="${NGROK_DOMAIN#https://}"
    domain="${domain#http://}"
    print_public_url_banner "https://$domain" "Configured ngrok domain."
    return 0
  fi
  echo "ngrok started — run: docker exec tms-automation cat /tmp/public-url.txt"
  return 1
}

start_ngrok_tunnel() {
  if [ -z "$NGROK_AUTHTOKEN" ]; then
    echo "NGROK_AUTHTOKEN is missing."
    return 1
  fi

  mkdir -p "$(dirname "$TUNNEL_LOG")"
  : > "$TUNNEL_LOG"
  rm -f "$PUBLIC_URL_FILE"

  ngrok config add-authtoken "$NGROK_AUTHTOKEN" >/dev/null

  if [ -n "$NGROK_DOMAIN" ]; then
    domain="${NGROK_DOMAIN#https://}"
    domain="${domain#http://}"
    echo "Starting ngrok on https://$domain ..."
    ngrok http 80 --url="https://$domain" --log=stdout >>"$TUNNEL_LOG" 2>&1 &
  else
    echo "Starting ngrok permanent tunnel..."
    ngrok http 80 --log=stdout >>"$TUNNEL_LOG" 2>&1 &
  fi

  TUNNEL_PID="$!"
  wait_for_ngrok_url
}

wait_for_zrok_url() {
  local url=""
  for _ in $(seq 1 60); do
    url="$(grep -Eo 'https://[^[:space:]]+|[-a-z0-9]+\\.shares\\.zrok\\.io' "$ZROK_LOG" 2>/dev/null | tail -1 || true)"
    if [ -n "$url" ]; then
      if [[ "$url" != https://* ]]; then
        url="https://$url"
      fi
      print_public_url_banner "$ZROK_SHARE_LABEL" "$url" "zrok public share."
      return 0
    fi
    sleep 1
  done
  echo "zrok started — run: docker exec tms-automation cat /tmp/public-urls.txt"
  return 1
}

get_zrok_share_binding() {
  local ZROK_BIN="${1:-}"
  "$ZROK_BIN" list shares --json 2>/dev/null | python3 -c '
import json
import os
import sys

target_name = os.environ.get("ZROK_RESERVED_NAME", "")
target_endpoint = f"{target_name}.shares.zrok.io"
try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for share in payload.get("shares") or []:
    endpoints = share.get("frontendEndpoints") or []
    if target_endpoint in endpoints:
        token = share.get("shareToken") or ""
        env_zid = share.get("envZId") or ""
        if token and env_zid:
            print(f"{token}|{env_zid}")
            break
'
}

zrok_environment_enabled() {
  local ZROK_BIN="${1:-}"
  "$ZROK_BIN" status 2>/dev/null | grep -q 'EnvZId'
}

select_zrok_binary() {
  if [[ "$ZROK_API_ENDPOINT" == *api-v2* ]]; then
    command -v zrok2 2>/dev/null || command -v zrok 2>/dev/null || true
  else
    command -v zrok 2>/dev/null || command -v zrok2 2>/dev/null || true
  fi
}

ensure_zrok_reserved_name() {
  local ZROK_BIN="${1:-}"
  if "$ZROK_BIN" list names -n public 2>/dev/null | grep -Fq "$ZROK_RESERVED_NAME"; then
    echo "Reusing existing zrok reserved name '$ZROK_RESERVED_NAME'."
    return 0
  fi
  echo "Creating zrok reserved name '$ZROK_RESERVED_NAME' in namespace public..."
  if ! "$ZROK_BIN" create name -n public "$ZROK_RESERVED_NAME" >>"$ZROK_LOG" 2>&1; then
    if grep -q '409\|shareNameConflict' "$ZROK_LOG" 2>/dev/null; then
      echo "Reserved name '$ZROK_RESERVED_NAME' already exists; continuing."
      return 0
    fi
    return 1
  fi
}

get_existing_zrok_share_url() {
  local ZROK_BIN="${1:-}"
  "$ZROK_BIN" list shares --json 2>/dev/null | python3 -c '
import json
import sys

TARGET = "http://127.0.0.1:80"
try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for share in payload.get("shares") or []:
    if (share.get("target") or "").strip() != TARGET:
        continue
    endpoints = share.get("frontendEndpoints") or []
    if endpoints:
        print(endpoints[0])
        break
'
}

repair_zrok_share_binding() {
  local ZROK_BIN="${1:-}"
  local binding token env_zid
  binding="$(get_zrok_share_binding "$ZROK_BIN" || true)"
  if [ -z "$binding" ]; then
    return 0
  fi
  token="${binding%%|*}"
  env_zid="${binding#*|}"
  echo "Removing stale zrok share '$token' ..."
  "$ZROK_BIN" delete share "$token" --envzid "$env_zid" >>"$ZROK_LOG" 2>&1 || true
}

start_zrok_tunnel() {
  if [ -z "$ZROK_ENV_TOKEN" ]; then
    echo "ZROK_ENV_TOKEN is missing."
    return 1
  fi

  mkdir -p "$(dirname "$ZROK_LOG")"
  : > "$ZROK_LOG"
  touch_public_urls_file

  ZROK_BIN="$(select_zrok_binary)"
  if [ -z "$ZROK_BIN" ]; then
    echo "zrok binary is not installed."
    return 1
  fi

  echo "Setting zrok apiEndpoint to '$ZROK_API_ENDPOINT' ..."
  "$ZROK_BIN" config set apiEndpoint "$ZROK_API_ENDPOINT" >/dev/null 2>&1 || {
    echo "Unable to set zrok apiEndpoint to '$ZROK_API_ENDPOINT'."
    return 1
  }

  echo "Ensuring zrok environment is enabled..."
  if ! "$ZROK_BIN" enable --headless "$ZROK_ENV_TOKEN" >>"$ZROK_LOG" 2>&1; then
    if zrok_environment_enabled "$ZROK_BIN"; then
      echo "zrok environment already enabled; reusing existing state."
    else
      echo "zrok enable failed."
      return 1
    fi
  fi

  if ensure_zrok_reserved_name "$ZROK_BIN"; then
    repair_zrok_share_binding "$ZROK_BIN"
    echo "Starting zrok reserved share '$ZROK_SHARE_LABEL' as 'public:$ZROK_RESERVED_NAME' ..."
    "$ZROK_BIN" share public http://127.0.0.1:80 -n "public:$ZROK_RESERVED_NAME" --headless >>"$ZROK_LOG" 2>&1 &
    ZROK_PID="$!"
    for _ in $(seq 1 30); do
      if grep -q 'shareConflict' "$ZROK_LOG" 2>/dev/null; then
        kill "$ZROK_PID" >/dev/null 2>&1 || true
        echo "Reserved zrok share failed; falling back to public share."
        break
      fi
      local_url="$(grep -Eo 'https://[^[:space:]]+|[-a-z0-9]+\\.shares\\.zrok\\.io' "$ZROK_LOG" 2>/dev/null | tail -1 || true)"
      if [ -n "$local_url" ]; then
        if [[ "$local_url" != https://* ]]; then
          local_url="https://$local_url"
        fi
        print_public_url_banner "$ZROK_SHARE_LABEL" "$local_url" "zrok public share."
        return 0
      fi
      sleep 1
    done
    if kill -0 "$ZROK_PID" >/dev/null 2>&1; then
      wait_for_zrok_url
      return $?
    fi
  else
    echo "zrok reserved name setup failed; falling back to public share."
  fi

  echo "Starting zrok public share '$ZROK_SHARE_LABEL' on http://127.0.0.1:80 ..."
  "$ZROK_BIN" share public http://127.0.0.1:80 --headless >>"$ZROK_LOG" 2>&1 &
  ZROK_PID="$!"
  wait_for_zrok_url
}

mkdir -p "$PGDATA"
chown -R postgres:postgres "$PGDATA"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "Initializing bundled PostgreSQL database..."
  gosu postgres initdb -D "$PGDATA" --username="$DB_USER"
fi

echo "Starting bundled PostgreSQL..."
gosu postgres pg_ctl -D "$PGDATA" -o "-c listen_addresses='127.0.0.1'" -w start

cleanup() {
  if [ -n "${TUNNEL_PID:-}" ]; then
    kill "$TUNNEL_PID" >/dev/null 2>&1 || true
  fi
  if [ -n "${ZROK_PID:-}" ]; then
    kill "$ZROK_PID" >/dev/null 2>&1 || true
  fi
  if [ -n "${NGROK_WAIT_PID:-}" ]; then
    kill "$NGROK_WAIT_PID" >/dev/null 2>&1 || true
  fi
  if [ -n "${ZROK_WAIT_PID:-}" ]; then
    kill "$ZROK_WAIT_PID" >/dev/null 2>&1 || true
  fi
  nginx -s quit >/dev/null 2>&1 || true
  gosu postgres pg_ctl -D "$PGDATA" -m fast -w stop
}
trap cleanup EXIT

echo "Ensuring database user and database exist..."
ADMIN_USER="$DB_USER"
if ! psql -v ON_ERROR_STOP=1 --username "$ADMIN_USER" --dbname postgres -c "SELECT 1" >/dev/null 2>&1; then
  ADMIN_USER="postgres"
fi

psql -v ON_ERROR_STOP=1 --username "$ADMIN_USER" --dbname postgres <<SQL
DO
\$do\$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${DB_USER}') THEN
      CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
   ELSE
      ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';
   END IF;
END
\$do\$;
SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')\\gexec
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
SQL

echo "Creating application tables and default frontend login..."
/opt/venv/bin/python scripts/init_local_db.py

echo "Starting Nginx reverse proxy on http://0.0.0.0:80"
nginx

if [ "$ENVIRONMENT" = "production" ] || [ "$ENVIRONMENT" = "prod" ]; then
  start_ngrok_tunnel >/tmp/ngrok-start.log 2>&1 &
  NGROK_WAIT_PID="$!"
  start_zrok_tunnel >/tmp/zrok-start.log 2>&1 &
  ZROK_WAIT_PID="$!"
else
  echo "ENVIRONMENT=$ENVIRONMENT — ngrok disabled (local/test mode)."
  print_public_url_banner "local" "http://localhost:3000" "Open this URL on your machine. Set ENVIRONMENT=prod in .env to enable tunnels."
fi

echo "Starting TMS Automation backend on http://127.0.0.1:8000"
echo "Local app: http://localhost:3000"
exec uvicorn main:app --host 127.0.0.1 --port 8000
