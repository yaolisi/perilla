#!/usr/bin/env bash
set -euo pipefail
# Runs `make pr-check` from repository root (~= frontend-build + backend-static-analysis together).
# Same targets as `make ci` (alias).
# Lighter gate: `scripts/quick-check.sh` (nvmrc + lint-backend only).
# Order: check-nvmrc-align → i18n-hardcoded-scan → lint-backend (`scripts/lint-backend.sh`) → test-no-fallback（no_fallback + `test_production_readiness_baseline`）→ test-tenant-isolation → helm-deploy-contract-check（helm-chart-check + `scripts/merge-gate-contract-tests.sh`）→ test-frontend-unit → build-frontend → roadmap-acceptance-unit (unless skipped)。
# Skip roadmap: export SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK=1 or pass --skip-roadmap-acceptance.
# Optional args are forwarded to the no-fallback pytest step only, e.g.:
#   bash scripts/pr-check.sh -k memory -x
# Legacy (forces roadmap on; default since roadmap is always on unless skipped):
#   bash scripts/pr-check.sh --with-roadmap-acceptance -k memory -x
# If no args are given, existing TEST_ARGS (if set) is preserved.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -f Makefile ]]; then
  echo >&2 "pr-check.sh: missing Makefile at repo root (${ROOT})"
  exit 1
fi
if [[ "${1:-}" == "--with-roadmap-acceptance" ]]; then
  export SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK=0
  shift
fi
if [[ "${1:-}" == "--skip-roadmap-acceptance" ]]; then
  export SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK=1
  shift
fi
if [ "$#" -gt 0 ]; then
  export TEST_ARGS="$*"
fi
exec make pr-check
