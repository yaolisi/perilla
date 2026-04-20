#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "== Base profile =="
docker compose --env-file .env -f docker-compose.yml ps || true
echo ""

echo "== GPU profile view =="
docker compose --env-file .env -f docker-compose.yml -f docker-compose.gpu.yml ps || true
echo ""

echo "== Prod profile view =="
docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml ps || true
