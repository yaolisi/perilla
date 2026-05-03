#!/usr/bin/env bash
# 后端上线前「代码 + Helm + 契约」一键校验（无需运行中的 API）。
# 顺序对齐 CI backend-static-analysis 单 job：quick-check → test-no-fallback → tenant-isolation → helm-chart-check → merge-gate-contract-tests → compose-config-check → monitoring-config-check → k8s-manifest-check → dockerfile-hadolint-check。
# 不包含：前端 Vitest/build、roadmap（见 make pr-check / pr-check-fast）。
# 环境变量就绪后另跑：make security-guardrails（见 scripts/check-security-guardrails.sh）。
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

echo "[production-preflight] OK — backend-static-analysis parity (backend steps only)."
echo "[production-preflight] Next: fill production .env (see root .env.example), then: make security-guardrails"
