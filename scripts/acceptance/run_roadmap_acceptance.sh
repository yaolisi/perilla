#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ ! -d backend ]]; then
  echo >&2 "run_roadmap_acceptance.sh: missing backend/ (${ROOT})"
  exit 1
fi

BASE_URL="${ROADMAP_BASE_URL:-http://127.0.0.1:8000}"
API_KEY="${ROADMAP_API_KEY:-}"
RUN_LIVE_SMOKE="${ROADMAP_RUN_LIVE_SMOKE:-0}"

echo "== Roadmap acceptance: unit/integration suite =="
PYTHONPATH=backend pytest \
  backend/tests/test_roadmap_service.py \
  backend/tests/test_system_api_integration.py \
  backend/tests/test_roadmap_acceptance_smoke.py \
  -q -k roadmap

if [[ "${RUN_LIVE_SMOKE}" == "1" ]]; then
  echo "== Roadmap acceptance: live API smoke =="
  if [[ -n "${API_KEY}" ]]; then
    python backend/scripts/roadmap_acceptance_smoke.py --base-url "${BASE_URL}" --api-key "${API_KEY}"
  else
    python backend/scripts/roadmap_acceptance_smoke.py --base-url "${BASE_URL}"
  fi
else
  echo "Skip live smoke (set ROADMAP_RUN_LIVE_SMOKE=1 to enable)."
fi
