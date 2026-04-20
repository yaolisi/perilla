#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/backend"
export PYTHONPATH=.
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
pytest -q \
  tests/test_production_readiness_baseline.py \
  tests/test_chaos_report_summary.py \
  tests/test_chaos_semi_integration.py \
  tests/test_system_chaos_injection.py \
  tests/test_runtime_fault_injection.py \
  tests/test_enhanced_error_paths.py \
  tests/test_enhanced_rbac_audit.py \
  tests/test_enhanced_middlewares.py \
  tests/test_frontend_xss_baseline.py \
  tests/test_vector_search.py
