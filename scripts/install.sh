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

if [[ ! -f docker-compose.yml ]]; then
  echo >&2 "install.sh: missing docker-compose.yml at repo root (${ROOT_DIR})"
  exit 1
fi

if [[ ! -f .env ]]; then
  if [[ ! -f .env.example ]]; then
    echo >&2 "install.sh: need .env.example when .env is absent (${ROOT_DIR})"
    exit 1
  fi
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Running doctor checks..."
bash scripts/doctor.sh

echo "Building images..."
docker compose --env-file .env build

echo "Starting services..."
docker compose --env-file .env up -d

echo ""
echo "OpenVitamin Docker deployment is ready."
echo "Frontend: http://localhost:${FRONTEND_PORT:-5173}"
echo "Backend:  http://localhost:${BACKEND_PORT:-8000}"
echo ""
echo "Use these commands:"
echo "  bash scripts/logs.sh"
echo "  bash scripts/down.sh"
