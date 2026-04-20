#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/backend"
export PYTHONPATH=.
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
echo "== Batch 5: web security regression (CSRF + XSS baseline) =="
pytest -q \
  tests/test_enhanced_middlewares.py \
  tests/test_frontend_xss_baseline.py
