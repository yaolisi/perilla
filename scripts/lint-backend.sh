#!/usr/bin/env bash
set -euo pipefail
# Ruff E9 + targeted mypy. Entry points: make lint-backend / make lint, npm run lint-backend / npm run lint; CI backend-static-analysis.
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
(command -v ruff >/dev/null || pip install -q ruff mypy)
ruff check --select=E9 .
mypy --config-file mypy.ini --follow-imports=skip core/data/base.py execution_kernel/persistence/db.py
