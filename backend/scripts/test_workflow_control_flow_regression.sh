#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

REPORT_DIR="backend/test-reports"
JUNIT_PATH="${JUNIT_XML_PATH:-$REPORT_DIR/workflow-control-flow-regression.xml}"
SUMMARY_PATH="${WORKFLOW_CONTROL_FLOW_SUMMARY_PATH:-$REPORT_DIR/workflow-control-flow-summary.md}"

mkdir -p "$REPORT_DIR"

PYTHONPATH=backend pytest \
  backend/tests/test_workflow_control_flow_regression.py \
  --junitxml "$JUNIT_PATH"

{
  echo "## Workflow Control-Flow Regression"
  echo "- suite: \`backend/tests/test_workflow_control_flow_regression.py\`"
  echo "- junit: \`$JUNIT_PATH\`"
  echo "- status: passed"
} > "$SUMMARY_PATH"
