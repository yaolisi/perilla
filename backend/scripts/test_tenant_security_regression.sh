#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${BACKEND_ROOT}"

SUMMARY_PATH="${TENANT_SECURITY_SUMMARY_PATH:-test-reports/tenant-security-summary.md}"
SLOW_THRESHOLD_SECONDS="${TENANT_SECURITY_SLOW_THRESHOLD_SECONDS:-30}"
mkdir -p "$(dirname "$SUMMARY_PATH")"

{
  echo "# Tenant Security Regression Summary"
  echo ""
  echo "- started_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo ""
  echo "## Suite"
  echo "- tests/test_workflow_tenant_api_isolation.py"
  echo "- tests/test_workflow_tenant_guard.py"
  echo "- tests/test_production_readiness_baseline.py::test_tenant_enforcement_protected_path"
  echo "- tests/test_production_readiness_baseline.py::test_apply_production_security_defaults_in_non_debug"
} > "$SUMMARY_PATH"

echo "[tenant-security] running tenant isolation regression suite..."
PYTEST_ARGS=(-q)
if [[ -n "${JUNIT_XML_PATH:-}" ]]; then
  PYTEST_ARGS+=("--junitxml=${JUNIT_XML_PATH}")
fi

started=$(date +%s)
set +e
PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest "${PYTEST_ARGS[@]}" \
  tests/test_workflow_tenant_api_isolation.py \
  tests/test_workflow_tenant_guard.py \
  tests/test_production_readiness_baseline.py::test_tenant_enforcement_protected_path \
  tests/test_production_readiness_baseline.py::test_apply_production_security_defaults_in_non_debug
status=$?
set -e
ended=$(date +%s)
duration=$((ended - started))
duration_mark="${duration}"
slow_mark=""
if [[ ${duration} -gt ${SLOW_THRESHOLD_SECONDS} ]]; then
  duration_mark="${duration} ⚠️"
  slow_mark=" (slow)"
fi

{
  echo "- duration_seconds: ${duration_mark}"
  if [[ $status -eq 0 ]]; then
    echo "- result: passed${slow_mark}"
  else
    echo "- result: **failed (${status})**${slow_mark}"
  fi
  echo "- finished_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  if [[ ${duration} -gt ${SLOW_THRESHOLD_SECONDS} ]]; then
    echo "- performance_warning: exceeded ${SLOW_THRESHOLD_SECONDS}s threshold"
  fi
  echo ""
  echo "## Local Reproduce"
  echo '```bash'
  echo "backend/scripts/test_tenant_security_regression.sh"
  echo '```'
} >> "$SUMMARY_PATH"

if [[ $status -eq 0 ]]; then
  echo "[tenant-security] regression suite passed."
else
  echo "[tenant-security] regression suite failed."
fi

exit $status
