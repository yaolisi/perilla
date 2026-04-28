#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f docker-compose.yml ]] || [[ ! -f docker-compose.prod.yml ]]; then
  echo >&2 "up-prod.sh: missing docker-compose.yml or docker-compose.prod.yml (${ROOT_DIR})"
  exit 1
fi
if [[ ! -f .env ]]; then
  echo >&2 "up-prod.sh: missing .env (${ROOT_DIR}); copy from .env.example or run make env-init"
  exit 1
fi

docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml ps
