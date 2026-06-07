#!/usr/bin/env bash
set -euo pipefail

: "${PGDATA:=/var/lib/postgresql/data}"
: "${DB_USER:=pk}"
: "${DB_PASSWORD:=pk}"
: "${DB_HOST:=127.0.0.1}"
: "${DB_NAME:=stock}"
: "${FRONTEND_SEED_USER:=admin}"
: "${FRONTEND_SEED_PASSWORD:=admin}"
: "${CLOUDFLARED_TOKEN:=}"
: "${CLOUDFLARED_QUICK_TUNNEL:=true}"

export DB_USER DB_PASSWORD DB_HOST DB_NAME FRONTEND_SEED_USER FRONTEND_SEED_PASSWORD

mkdir -p "$PGDATA"
chown -R postgres:postgres "$PGDATA"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "Initializing bundled PostgreSQL database..."
  gosu postgres initdb -D "$PGDATA" --username="$DB_USER"
fi

echo "Starting bundled PostgreSQL..."
gosu postgres pg_ctl -D "$PGDATA" -o "-c listen_addresses='127.0.0.1'" -w start

cleanup() {
  if [ -n "${CLOUDFLARED_PID:-}" ]; then
    kill "$CLOUDFLARED_PID" >/dev/null 2>&1 || true
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

if [ -n "$CLOUDFLARED_TOKEN" ]; then
  echo "Starting Cloudflare named tunnel from CLOUDFLARED_TOKEN..."
  cloudflared tunnel --no-autoupdate run --token "$CLOUDFLARED_TOKEN" &
  CLOUDFLARED_PID="$!"
elif [ "$CLOUDFLARED_QUICK_TUNNEL" = "true" ]; then
  echo "Starting Cloudflare Quick Tunnel for http://127.0.0.1:80..."
  echo "This URL is temporary. For the same URL every time, set CLOUDFLARED_TOKEN."
  cloudflared tunnel --url http://127.0.0.1:80 &
  CLOUDFLARED_PID="$!"
else
  echo "Cloudflare tunnel disabled. Set CLOUDFLARED_QUICK_TUNNEL=true or CLOUDFLARED_TOKEN."
fi

echo "Starting TMS Automation backend on http://127.0.0.1:8000"
exec uvicorn main:app --host 127.0.0.1 --port 8000
