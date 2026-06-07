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

export DB_USER DB_PASSWORD DB_HOST DB_NAME FRONTEND_SEED_USER FRONTEND_SEED_PASSWORD

PUBLIC_URL_FILE=/tmp/public-url.txt
TUNNEL_LOG=/tmp/tunnel.log
TUNNEL_PID=""

print_public_url_banner() {
  local url="$1"
  local note="${2:-}"
  echo "$url" > "$PUBLIC_URL_FILE"
  echo ""
  echo "=============================================="
  echo " PUBLIC URL: $url"
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
      print_public_url_banner "$url" "Permanent ngrok URL for your account."
      return 0
    fi
    sleep 1
  done
  echo "ngrok started — run: docker exec tms-automation cat /tmp/public-url.txt"
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
python scripts/init_local_db.py

echo "Starting Nginx reverse proxy on http://0.0.0.0:80"
nginx

start_ngrok_tunnel || true

echo "Starting TMS Automation backend on http://127.0.0.1:8000"
echo "Local app: http://localhost:3000"
exec uvicorn main:app --host 127.0.0.1 --port 8000
