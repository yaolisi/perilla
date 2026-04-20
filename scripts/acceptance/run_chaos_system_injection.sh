#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/backend"

export PYTHONPATH=.
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

echo "== 系统级混沌注入测试 =="
echo ""
echo "失败判定标准："
echo "1) SQLite 锁冲突/超时时，db_session 未回滚或未抛出 OperationalError -> FAIL"
echo "2) workflow debug 事件源为空时未返回 [] -> FAIL"
echo "3) workflow debug 事件源损坏时未降级为 _error 结构 -> FAIL"
echo "4) trace header 污染输入未被拒绝且未回退 request_id -> FAIL"
echo "5) 任一测试用例失败 -> FAIL"
echo ""

pytest -q \
  tests/test_system_chaos_injection.py \
  tests/test_enhanced_error_paths.py

echo ""
echo "PASS: 系统级混沌注入测试通过。"
