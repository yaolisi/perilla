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

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Running doctor checks..."
bash scripts/doctor.sh

echo "Building images (gpu profile)..."
docker compose --env-file .env -f docker-compose.yml -f docker-compose.gpu.yml build

echo "Starting services (gpu profile)..."
docker compose --env-file .env -f docker-compose.yml -f docker-compose.gpu.yml up -d

echo ""
echo "OpenVitamin Docker GPU profile is ready."
echo "Frontend: http://localhost:${FRONTEND_PORT:-5173}"
echo "Backend:  http://localhost:${BACKEND_PORT:-8000}"
echo ""
echo "Use these commands:"
echo "  bash scripts/logs.sh"
echo "  bash scripts/healthcheck.sh"
echo "  bash scripts/down.sh"
