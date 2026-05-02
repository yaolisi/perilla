#!/usr/bin/env bash
# 后端上线前「代码 + Helm + 契约」一键校验（无需运行中的 API）。
# 顺序对齐 CI backend-static-analysis 主干：quick-check → test-no-fallback → helm-chart-check → merge-gate-contract-tests。
# 不包含：租户隔离 pytest、前端 Vitest/build、roadmap（见 make pr-check / pr-check-fast）。
# 环境变量就绪后另跑：make security-guardrails（见 scripts/check-security-guardrails.sh）。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -f Makefile ]]; then
  echo >&2 "production-preflight.sh: missing Makefile at repo root (${ROOT})"
  exit 1
fi

echo "[production-preflight] 1/4 quick-check (nvmrc + lint-backend)"
bash scripts/quick-check.sh

echo "[production-preflight] 2/4 test-no-fallback + production readiness baseline"
bash scripts/test-no-fallback.sh -q

echo "[production-preflight] 3/4 helm-chart-check"
bash scripts/helm-chart-check.sh

echo "[production-preflight] 4/4 merge-gate contract tests"
bash scripts/merge-gate-contract-tests.sh -q

echo "[production-preflight] OK — code + chart + contracts aligned with backend-static-analysis."
echo "[production-preflight] Next: fill production .env (see root .env.example), then: make security-guardrails"
