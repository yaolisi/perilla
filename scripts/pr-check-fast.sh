#!/usr/bin/env bash
set -euo pipefail
# Runs `make pr-check-fast` from repository root (no prod build).
# Same targets as `make ci-fast` (alias).
# Lighter gate: `scripts/quick-check.sh` (nvmrc + lint-backend only).
# Order: check-nvmrc-align → lint-backend (`scripts/lint-backend.sh`) → test-no-fallback → test-frontend-unit.
# Optional args → TEST_ARGS for pytest (same as pr-check.sh).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -f Makefile ]]; then
  echo >&2 "pr-check-fast.sh: missing Makefile at repo root (${ROOT})"
  exit 1
fi
if [ "$#" -gt 0 ]; then
  export TEST_ARGS="$*"
fi
exec make pr-check-fast
