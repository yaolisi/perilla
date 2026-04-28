#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
if [[ ! -d backend ]]; then
  echo >&2 "run_security_regression.sh: missing backend/ (${ROOT})"
  exit 1
fi

SUMMARY_PATH="${SECURITY_SUMMARY_PATH:-test-reports/security-regression-summary.md}"
SLOW_THRESHOLD_SECONDS="${SECURITY_SLOW_THRESHOLD_SECONDS:-30}"
mkdir -p "$(dirname "$SUMMARY_PATH")"

{
  echo "# Security Regression Summary"
  echo ""
  echo "- started_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo ""
  echo "| Batch | Status | Duration(s) | Script |"
  echo "|---|---|---:|---|"
} > "$SUMMARY_PATH"

overall_status=0
failed_batches=()
slow_batches=()

run_batch() {
  local label="$1"
  local cmd="$2"
  local script_ref="$3"
  local started
  local ended
  local duration
  local status
  local duration_mark
  local status_text

  echo "== ${label} =="
  started=$(date +%s)
  set +e
  eval "$cmd"
  status=$?
  set -e
  ended=$(date +%s)
  duration=$((ended - started))
  duration_mark="${duration}"
  if [[ ${duration} -gt ${SLOW_THRESHOLD_SECONDS} ]]; then
    duration_mark="${duration} ⚠️"
    slow_batches+=("${label} (${duration}s) -> ${script_ref}")
  fi

  if [[ $status -eq 0 ]]; then
    status_text="✅ passed"
    if [[ ${duration} -gt ${SLOW_THRESHOLD_SECONDS} ]]; then
      status_text="✅ passed (slow)"
    fi
    echo "| ${label} | ${status_text} | ${duration_mark} | \`${script_ref}\` |" >> "$SUMMARY_PATH"
  else
    status_text="❌ **failed(${status})**"
    if [[ ${duration} -gt ${SLOW_THRESHOLD_SECONDS} ]]; then
      status_text="❌ **failed(${status}) + slow**"
    fi
    echo "| ${label} | ${status_text} | ${duration_mark} | \`${script_ref}\` |" >> "$SUMMARY_PATH"
    failed_batches+=("${label} -> ${script_ref}")
    overall_status=$status
  fi
  echo ""
}

set -e
run_batch "Batch 1 (RBAC)" "scripts/acceptance/run_batch1_rbac.sh" "scripts/acceptance/run_batch1_rbac.sh"
run_batch "Batch 2 (Audit)" "scripts/acceptance/run_batch2_audit.sh" "scripts/acceptance/run_batch2_audit.sh"
run_batch "Batch 3 (Trace)" "scripts/acceptance/run_batch3_trace.sh" "scripts/acceptance/run_batch3_trace.sh"
run_batch "Batch 5 (Web Security: CSRF + XSS baseline)" "scripts/acceptance/run_batch5_web_security.sh" "scripts/acceptance/run_batch5_web_security.sh"

{
  echo ""
  echo "- finished_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  if [[ $overall_status -eq 0 ]]; then
    echo "- result: passed"
  else
    echo "- result: failed (${overall_status})"
    echo ""
    echo "## Failed Batches"
    for item in "${failed_batches[@]}"; do
      echo "- ${item}"
    done
  fi
  if [[ ${#slow_batches[@]} -gt 0 ]]; then
    echo ""
    echo "## Slow Batches (>${SLOW_THRESHOLD_SECONDS}s)"
    for item in "${slow_batches[@]}"; do
      echo "- ${item}"
    done
  fi
  echo ""
  echo "## Local Reproduce"
  echo '```bash'
  echo "scripts/acceptance/run_security_regression.sh"
  echo '```'
} >> "$SUMMARY_PATH"

if [[ $overall_status -eq 0 ]]; then
  echo "Security regression suite completed."
else
  echo "Security regression suite completed with failures."
fi

exit $overall_status
