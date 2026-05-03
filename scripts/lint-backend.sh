#!/usr/bin/env bash
set -euo pipefail
# Ruff E9 (entire tree) + Ruff check + format --check (PR_CHECK_CONTRACT_RUFF_TARGETS) + targeted mypy.
# Entry points: make lint-backend / make lint, npm run lint-backend / npm run lint; CI backend-static-analysis.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -d "${ROOT}/backend" ]]; then
  echo >&2 "lint-backend.sh: missing backend/ at ${ROOT}"
  exit 1
fi
if [[ ! -f "${ROOT}/backend/mypy.ini" ]]; then
  echo >&2 "lint-backend.sh: missing backend/mypy.ini (${ROOT})"
  exit 1
fi
cd "${ROOT}/backend"
if ! (command -v ruff >/dev/null && command -v mypy >/dev/null); then
  pip install -q -r requirements/lint-tools.txt
fi
ruff check --select=E9 .
# 体量小、与 merge-gate pytest 列表同源（tests/test_pr_check_contract_*.py）；路径只维护一处。
PR_CHECK_CONTRACT_RUFF_TARGETS=(
  tests/pr_check_contract
  tests/test_pr_check_contract_*.py
)
ruff check "${PR_CHECK_CONTRACT_RUFF_TARGETS[@]}"
ruff format --check "${PR_CHECK_CONTRACT_RUFF_TARGETS[@]}"
# Mypy merge gate: only append targets below after `mypy --config-file mypy.ini --follow-imports=skip <path>` is clean.
# Use per-module sections in backend/mypy.ini for targeted suppressions; do not relax global [mypy].
mypy --config-file mypy.ini --follow-imports=skip \
  core/data/base.py \
  execution_kernel/persistence/db.py \
  core/plan_contract \
  core/idempotency \
  core/events
