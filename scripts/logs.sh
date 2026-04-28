#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f docker-compose.yml ]]; then
  echo >&2 "logs.sh: missing docker-compose.yml at repo root (${ROOT_DIR})"
  exit 1
fi
if [[ ! -f .env ]]; then
  echo >&2 "logs.sh: missing .env (${ROOT_DIR}); copy from .env.example or run make env-init"
  exit 1
fi

docker compose --env-file .env logs -f --tail=200
