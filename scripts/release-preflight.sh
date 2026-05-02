#!/usr/bin/env bash
# 发布前「后端 CI + 前端 CI」一键校验（无需运行中的 API）。
# - 后端：与 backend-static-analysis + merge-gate 对齐（见 scripts/production-preflight.sh）
# - 前端：与 frontend-build workflow 对齐（i18n 硬编码扫描 + Vitest + vue-tsc/vite prod build）
# 不含：roadmap-acceptance-unit（可选单独 make roadmap-acceptance-unit）、security-guardrails（需生产 .env）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -f Makefile ]]; then
  echo >&2 "release-preflight.sh: missing Makefile at repo root (${ROOT})"
  exit 1
fi

bash scripts/production-preflight.sh

echo "[release-preflight] frontend i18n hardcoded scan"
bash scripts/check-frontend-i18n-hardcoded.sh

echo "[release-preflight] frontend unit tests (Vitest)"
make test-frontend-unit

echo "[release-preflight] frontend production build"
make build-frontend

echo "[release-preflight] OK — backend-static-analysis + frontend-build parity (no roadmap)."
echo "[release-preflight] Optional: make roadmap-acceptance-unit && make security-guardrails"
