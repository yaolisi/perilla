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
ready_url="http://127.0.0.1:${BACKEND_PORT}/api/health/ready"
if [[ "${HEALTHCHECK_ALLOW_READY_503:-0}" == "1" ]]; then
  # 开启 HEALTH_READY_STRICT_EVENT_BUS 且事件总线降级时 ready 为 503；仅验收「接口可达」时可设本变量为 1
  code="$(curl -s -o /dev/null -w "%{http_code}" "${ready_url}")"
  if [[ "${code}" != "200" && "${code}" != "503" ]]; then
    echo >&2 "  FAIL (HTTP ${code})"
    exit 1
  fi
  echo "  OK (HTTP ${code})"
else
  curl -fsS "${ready_url}" >/dev/null
  echo "  OK"
fi

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
