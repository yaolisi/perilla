#!/usr/bin/env bash
set -euo pipefail
# Minimal gate: `.nvmrc` alignment + backend ruff/mypy (subset of `make pr-check-fast`).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -f package.json ]]; then
  echo >&2 "quick-check.sh: missing package.json at repo root (${ROOT})"
  exit 1
fi
bash scripts/check-nvmrc-align.sh
bash scripts/lint-backend.sh
echo "quick-check: OK"
