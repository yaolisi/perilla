#!/usr/bin/env bash
# 后端上线前「代码 + Helm + 契约」一键校验（无需运行中的 API）。
# 顺序对齐 CI backend-static-analysis 单 job 前 9 步：quick-check → … → dockerfile-hadolint-check。
# CI 在同 workflow 末尾另有第 10 步 scripts/check-security-guardrails.sh（注入合成 env）；本地仍应用真实 .env 跑 make security-guardrails。
# 不包含：前端 Vitest/build、roadmap（见 make pr-check / pr-check-fast）。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -f Makefile ]]; then
  echo >&2 "production-preflight.sh: missing Makefile at repo root (${ROOT})"
  exit 1
fi

echo "[production-preflight] 1/9 quick-check (nvmrc + lint-backend)"
bash scripts/quick-check.sh

echo "[production-preflight] 2/9 test-no-fallback + production readiness baseline"
bash scripts/test-no-fallback.sh -q

echo "[production-preflight] 3/9 tenant isolation (pytest -m tenant_isolation)"
make test-tenant-isolation

echo "[production-preflight] 4/9 helm-chart-check"
bash scripts/helm-chart-check.sh

echo "[production-preflight] 5/9 merge-gate contract tests"
bash scripts/merge-gate-contract-tests.sh -q

echo "[production-preflight] 6/9 docker compose merge (docker-compose.yml + docker-compose.prod.yml)"
bash scripts/compose-config-check.sh

echo "[production-preflight] 7/9 Prometheus / Alertmanager config (promtool / amtool)"
bash scripts/monitoring-config-check.sh

echo "[production-preflight] 8/9 K8s example manifests (kubeconform)"
bash scripts/k8s-manifest-check.sh

echo "[production-preflight] 9/9 Dockerfiles (hadolint)"
bash scripts/dockerfile-hadolint-check.sh

echo "[production-preflight] OK — CI steps 1–9 (backend); step 10 security-guardrails runs only in GitHub Actions with synthetic env."
echo "[production-preflight] Next: fill production .env (see root .env.example), then: make security-guardrails"
