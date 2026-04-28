#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ ! -d "${ROOT}/backend" ]]; then
  echo >&2 "$(basename "$0"): missing backend/ (${ROOT})"
  exit 1
fi
cd "$ROOT/backend"
export PYTHONPATH=.
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
echo "== Batch 1: RBAC unit tests =="
pytest -q tests/test_enhanced_rbac_audit.py
