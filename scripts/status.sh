#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f docker-compose.yml ]]; then
  echo >&2 "status.sh: missing docker-compose.yml at repo root (${ROOT_DIR})"
  exit 1
fi
if [[ ! -f docker-compose.gpu.yml ]] || [[ ! -f docker-compose.prod.yml ]]; then
  echo >&2 "status.sh: missing docker-compose.gpu.yml or docker-compose.prod.yml (${ROOT_DIR})"
  exit 1
fi
if [[ ! -f .env ]]; then
  echo >&2 "status.sh: missing .env (${ROOT_DIR}); copy from .env.example or run make env-init"
  exit 1
fi

echo "== Base profile =="
docker compose --env-file .env -f docker-compose.yml ps || true
echo ""

echo "== GPU profile view =="
docker compose --env-file .env -f docker-compose.yml -f docker-compose.gpu.yml ps || true
echo ""

echo "== Prod profile view =="
docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml ps || true
