#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ ! -d "${ROOT}/backend" ]]; then
  echo >&2 "$(basename "$0"): missing backend/ (${ROOT})"
  exit 1
fi
cd "$ROOT/backend"

BASE_URL="${1:-http://127.0.0.1:8000}"
USER_ID="${2:-chaos-user}"
TOTAL="${3:-40}"
CONCURRENCY="${4:-10}"
REPORT_PATH="${5:-}"

echo "== 半集成混沌测试（需后端已启动） =="
echo "base_url=$BASE_URL user_id=$USER_ID total=$TOTAL concurrency=$CONCURRENCY"
echo ""
echo "失败判定标准："
echo "1) /api/health 非 200 -> FAIL"
echo "2) Trace 污染输入未回退 request_id -> FAIL"
echo "3) 并发 workflow 写入出现网络异常或 5xx -> FAIL"
echo "4) workflow debug(not-found) 非 404 -> FAIL"
echo ""

export PYTHONPATH=.
ARGS=(
  --base-url "$BASE_URL"
  --user-id "$USER_ID"
  --total-requests "$TOTAL"
  --concurrency "$CONCURRENCY"
)
if [[ -n "$REPORT_PATH" ]]; then
  ARGS+=(--report-file "$REPORT_PATH")
fi

python scripts/chaos_semi_integration.py \
  "${ARGS[@]}"
