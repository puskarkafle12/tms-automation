#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo ""
echo "=========================================="
echo " ngrok — start container & show URL"
echo "=========================================="
echo ""
echo "ngrok authtoken is baked into the Docker image."
echo "Just build and run — no .env or extra setup required."
echo ""

docker compose up -d --build

echo ""
echo "Waiting for permanent public URL..."
for _ in $(seq 1 90); do
  if url="$(./scripts/show-public-url.sh 2>/dev/null || true)" && [[ "$url" == https://* ]]; then
    echo ""
    echo "=========================================="
    echo " SUCCESS — Permanent public URL:"
    echo " $url"
    echo "=========================================="
    echo ""
    echo "Local URL:  http://localhost:3000"
    echo "Show again: ./scripts/show-public-url.sh"
    exit 0
  fi
  sleep 2
done

echo ""
echo "Container is starting. Check URL in a moment:"
echo "  ./scripts/show-public-url.sh"
echo "  docker logs tms-automation | tail -30"
