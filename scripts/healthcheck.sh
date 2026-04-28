#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f docker-compose.yml ]]; then
  echo >&2 "healthcheck.sh: missing docker-compose.yml at repo root (${ROOT_DIR})"
  exit 1
fi
if [[ ! -f .env ]]; then
  echo >&2 "healthcheck.sh: missing .env (${ROOT_DIR}); copy from .env.example or run make env-init"
  exit 1
fi

FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

echo "[1/5] Compose service status"
docker compose --env-file .env ps

echo "[2/5] Backend /api/health"
curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/health" >/dev/null
echo "  OK"

echo "[3/5] Backend /api/health/ready"
curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/health/ready" >/dev/null
echo "  OK"

echo "[4/5] Frontend root page"
curl -fsS "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null
echo "  OK"

echo "[5/5] CSRF write-path check (expects 403 without token)"
status="$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://127.0.0.1:${BACKEND_PORT}/api/system/config" -H "Content-Type: application/json" -d '{}')"
if [[ "${status}" == "403" ]]; then
  echo "  OK (got expected 403)"
else
  echo "  WARNING: expected 403, got ${status}"
fi

echo "Healthcheck completed."
