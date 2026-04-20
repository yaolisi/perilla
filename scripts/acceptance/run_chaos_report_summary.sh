#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/backend"

REPORT_DIR="${1:-data/chaos-reports}"
OUT_FILE="${2:-}"
OUT_FORMAT="${3:-json}"
TOP_FAILURES="${4:-5}"
FAIL_RATE_WARN="${5:-0.05}"
P95_WARN_MS="${6:-800}"
NET_ERR_WARN="${7:-1}"

echo "== Chaos 报告汇总 =="
echo "report_dir=$REPORT_DIR"

export PYTHONPATH=.
ARGS=(--report-dir "$REPORT_DIR")
if [[ -n "$OUT_FILE" ]]; then
  ARGS+=(--output-file "$OUT_FILE")
fi
ARGS+=(--format "$OUT_FORMAT")
ARGS+=(--top-failures "$TOP_FAILURES")
ARGS+=(--fail-rate-warn "$FAIL_RATE_WARN")
ARGS+=(--p95-warn-ms "$P95_WARN_MS")
ARGS+=(--net-err-warn "$NET_ERR_WARN")
python scripts/chaos_report_summary.py "${ARGS[@]}"
