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
REQUIRE_GO="${ROADMAP_REQUIRE_GO:-0}"
MIN_READINESS_AVG="${ROADMAP_MIN_READINESS_AVG:-}"
MAX_LOWEST_READINESS_SCORE="${ROADMAP_MAX_LOWEST_READINESS_SCORE:-}"

echo "== Roadmap acceptance: unit/integration suite =="
PYTHONPATH=backend pytest \
  backend/tests/test_roadmap_service.py \
  backend/tests/test_system_api_integration.py \
  backend/tests/test_roadmap_acceptance_smoke.py \
  -q -k roadmap

if [[ "${RUN_LIVE_SMOKE}" == "1" ]]; then
  echo "== Roadmap acceptance: live API smoke =="
  SMOKE_ARGS=(--base-url "${BASE_URL}")
  if [[ -n "${API_KEY}" ]]; then
    SMOKE_ARGS+=(--api-key "${API_KEY}")
  fi
  if [[ "${REQUIRE_GO}" == "1" ]]; then
    SMOKE_ARGS+=(--require-go)
  fi
  if [[ -n "${MIN_READINESS_AVG}" ]]; then
    SMOKE_ARGS+=(--min-readiness-avg "${MIN_READINESS_AVG}")
  fi
  if [[ -n "${MAX_LOWEST_READINESS_SCORE}" ]]; then
    SMOKE_ARGS+=(--max-lowest-readiness-score "${MAX_LOWEST_READINESS_SCORE}")
  fi
  python backend/scripts/roadmap_acceptance_smoke.py "${SMOKE_ARGS[@]}"
else
  echo "Skip live smoke (set ROADMAP_RUN_LIVE_SMOKE=1 to enable)."
fi
