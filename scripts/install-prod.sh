#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is not installed." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Error: docker compose plugin is not available." >&2
  exit 1
fi

if [[ ! -f docker-compose.yml ]] || [[ ! -f docker-compose.prod.yml ]]; then
  echo >&2 "install-prod.sh: missing docker-compose.yml or docker-compose.prod.yml (${ROOT_DIR})"
  exit 1
fi

if [[ ! -f .env ]]; then
  if [[ ! -f .env.example ]]; then
    echo >&2 "install-prod.sh: need .env.example when .env is absent (${ROOT_DIR})"
    exit 1
  fi
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Running doctor checks..."
DOCTOR_STRICT_WARNINGS="${DOCTOR_STRICT_WARNINGS:-1}" bash scripts/doctor.sh

echo "Building images (prod profile)..."
docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml build

echo "Starting services (prod profile)..."
docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml up -d

echo ""
echo "OpenVitamin Docker production profile is ready."
echo "Frontend: http://localhost:${FRONTEND_PORT:-80}"
echo "Backend (internal): http://backend:8000"
echo ""
echo "Use these commands:"
echo "  bash scripts/logs.sh"
echo "  bash scripts/healthcheck.sh"
echo "  bash scripts/down.sh"
