#!/usr/bin/env bash
set -euo pipefail
# Runs `make pr-check-fast` from repository root (no prod build).
# Same targets as `make ci-fast` (alias).
# Lighter gate: `scripts/quick-check.sh` (nvmrc + lint-backend only).
# Ruff/mypy CI parity: `make install-lint-tools` → `backend/requirements/lint-tools.txt`.
# Order: check-nvmrc-align → i18n-hardcoded-scan → lint-backend (`scripts/lint-backend.sh`) → test-no-fallback（no_fallback + `test_production_readiness_baseline`）→ test-tenant-isolation → helm-deploy-contract-check（`scripts/merge-gate-contract-tests.sh`）→ test-frontend-unit → roadmap-acceptance-unit (unless skipped)。
# Skip roadmap: export SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK=1 or pass --skip-roadmap-acceptance.
# Optional args → TEST_ARGS for pytest (same as pr-check.sh).
# Or:
#   bash scripts/pr-check-fast.sh --with-roadmap-acceptance -k memory -x
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -f Makefile ]]; then
  echo >&2 "pr-check-fast.sh: missing Makefile at repo root (${ROOT})"
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
exec make pr-check-fast
