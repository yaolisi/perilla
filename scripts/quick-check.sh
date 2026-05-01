#!/usr/bin/env bash
set -euo pipefail
# Minimal gate: `.nvmrc` alignment + backend ruff/mypy（不含 test-no-fallback / Helm / merge-gate-contract-tests）。
# 完整静态分析与 Helm 契约：`bash scripts/merge-gate-contract-tests.sh` 或 `make helm-deploy-contract-check`（见 CI backend-static-analysis）。
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -f package.json ]]; then
  echo >&2 "quick-check.sh: missing package.json at repo root (${ROOT})"
  exit 1
fi
bash scripts/check-nvmrc-align.sh
bash scripts/lint-backend.sh
echo "quick-check: OK"
echo "quick-check: next — merge gate pytest only: make merge-gate-contract-tests (or npm run merge-gate-contract-tests)"
echo "quick-check: next — helm lint + merge gate: make helm-deploy-contract-check (CI backend-static-analysis parity)"
