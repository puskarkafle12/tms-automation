#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${1:-tms-automation}"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "Container '$CONTAINER' is not running." >&2
  exit 1
fi

if url="$(docker exec "$CONTAINER" cat /tmp/public-url.txt 2>/dev/null)" && [ -n "$url" ]; then
  echo "$url"
  exit 0
fi

docker logs "$CONTAINER" 2>&1 | grep -Eo 'https://[-a-z0-9A-Z./]+\.(ngrok-free\.app|ngrok-free\.dev|ngrok\.io|ngrok\.app)' | tail -1
