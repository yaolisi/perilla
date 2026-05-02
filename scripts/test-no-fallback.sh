#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -d backend ]]; then
  echo >&2 "test-no-fallback.sh: missing backend/ (${ROOT})"
  exit 1
fi
if [[ ! -f pytest.ini ]]; then
  echo >&2 "test-no-fallback.sh: missing pytest.ini (${ROOT})"
  exit 1
fi

# CI: `.github/workflows/backend-static-analysis.yml` 在 checkout 之后会先运行 `scripts/check-nvmrc-align.sh`，再 setup-python / ruff / mypy / 本脚本。
# 脚本会 cd 到仓库根再跑 pytest（任意 cwd 可调）。不包含 `.nvmrc` 对齐时可先跑 `bash scripts/check-nvmrc-align.sh`，或用 `make pr-check` / `make pr-check-fast`。
# 阶段 1：`-m no_fallback`（API 不得落入通用 HTTPException 回退路径）。
# 阶段 2：`test_production_readiness_baseline.py`（无该 marker，须单独跑）— 生产启动告警、events/审计、SLO、EventBus 对齐等。
# `--strict-markers` 仅用于阶段 1；阶段 1 所用自定义 marker 须在仓库根 `pytest.ini` 的 `[pytest] markers` 登记。
# Allow passing extra pytest args, e.g.:
#   bash scripts/test-no-fallback.sh -k memory -x
#   make test-no-fallback TEST_ARGS="-k memory -x"
PYTHONPATH=backend pytest \
  backend/tests/test_api_error_no_fallback_smoke.py \
  backend/tests/test_audit_log_events_path_coverage.py \
  backend/tests/test_memory_api_integration.py \
  backend/tests/test_sessions_api_integration.py \
  backend/tests/test_agent_sessions_api_integration.py \
  backend/tests/test_agents_api_kernel_opts_e2e.py \
  backend/tests/test_agents_enabled_skills_meta.py \
  backend/tests/test_workflow_approval_api_integration.py \
  backend/tests/test_knowledge_images_api_integration.py \
  backend/tests/test_runtime_settings_mcp_emit.py \
  -m no_fallback --strict-markers -q "$@"

PYTHONPATH=backend pytest \
  backend/tests/test_production_readiness_baseline.py \
  -q "$@"
