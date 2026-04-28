#!/usr/bin/env bash
set -euo pipefail
# Runs `make pr-check` from repository root (~= frontend-build + backend-static-analysis together).
# Same targets as `make ci` (alias).
# Lighter gate: `scripts/quick-check.sh` (nvmrc + lint-backend only).
# Order: check-nvmrc-align → lint-backend (`scripts/lint-backend.sh`) → test-no-fallback (pytest) → test-frontend-unit → build-frontend.
# Optional args are forwarded to the no-fallback pytest step only, e.g.:
#   bash scripts/pr-check.sh -k memory -x
# If no args are given, existing TEST_ARGS (if set) is preserved.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -f Makefile ]]; then
  echo >&2 "pr-check.sh: missing Makefile at repo root (${ROOT})"
  exit 1
fi
if [ "$#" -gt 0 ]; then
  export TEST_ARGS="$*"
fi
exec make pr-check
