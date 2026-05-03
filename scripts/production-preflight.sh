#!/usr/bin/env bash
# 后端上线前「代码 + Helm + 契约」一键校验（无需运行中的 API）。
# 顺序对齐 CI backend-static-analysis 单 job 全 10 步：quick-check → … → dockerfile-hadolint → security-guardrails-ci。
# security-guardrails-ci 与 CI 同源（scripts/check-security-guardrails-ci.sh）；真实上线 env 另跑 make security-guardrails。
# 不包含：前端 Vitest/build、roadmap（见 make pr-check / pr-check-fast）。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -f Makefile ]]; then
  echo >&2 "production-preflight.sh: missing Makefile at repo root (${ROOT})"
  exit 1
fi

echo "[production-preflight] 1/10 quick-check (nvmrc + lint-backend)"
bash scripts/quick-check.sh

echo "[production-preflight] 2/10 test-no-fallback + production readiness baseline"
bash scripts/test-no-fallback.sh -q

echo "[production-preflight] 3/10 tenant isolation (pytest -m tenant_isolation)"
make test-tenant-isolation

echo "[production-preflight] 4/10 helm-chart-check"
bash scripts/helm-chart-check.sh

echo "[production-preflight] 5/10 merge-gate contract tests"
bash scripts/merge-gate-contract-tests.sh -q

echo "[production-preflight] 6–10/10 compose + monitoring + k8s + hadolint + security-guardrails-ci (make backend-static-analysis-extras)"
make backend-static-analysis-extras

echo "[production-preflight] OK — full backend-static-analysis parity (10 steps)."
echo "[production-preflight] Next: fill production .env (see root .env.example), then: make security-guardrails"
