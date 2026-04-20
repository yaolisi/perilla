#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/backend"
export PYTHONPATH=.
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
echo "== Batch 3: trace headers / traceparent =="
pytest -q \
  tests/test_enhanced_rbac_audit.py::test_traceparent_parses_trace_id \
  tests/test_enhanced_error_paths.py::test_traceparent_invalid_fallback_to_request_id \
  tests/test_enhanced_error_paths.py::test_trace_header_pollution_is_rejected_and_fallback \
  tests/test_enhanced_middlewares.py::test_request_trace_injects_headers \
  tests/test_enhanced_middlewares.py::test_request_trace_reuses_incoming_request_id \
  tests/test_enhanced_middlewares.py::test_request_trace_invalid_request_id_fallback_to_uuid
echo ""
echo "Manual: curl -sI \"http://127.0.0.1:8000/api/health\" | grep -i X-Trace-Id"
