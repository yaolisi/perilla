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
echo "== Batch 2: audit-related unit tests =="
pytest -q \
  tests/test_enhanced_error_paths.py::test_audit_access_denied_for_non_admin \
  tests/test_production_readiness_baseline.py::test_audit_query_tenant_filter \
  tests/test_runtime_fault_injection.py::test_audit_middleware_degrades_when_db_session_broken \
  tests/test_runtime_fault_injection.py::test_audit_middleware_degrades_when_append_fails
echo ""
echo "Manual: start backend with audit_log_enabled=true and rbac_admin_api_keys set, then:"
echo "  curl -s -H \"X-Api-Key: <admin-key>\" \"http://127.0.0.1:8000/api/v1/audit/logs?limit=5\""
