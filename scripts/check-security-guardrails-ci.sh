#!/usr/bin/env bash
# CI / Makefile：用合成占位 env 跑 validate_production_security_guardrails（不进密钥仓库）。
# 默认值与 .github/workflows/backend-static-analysis.yml 同源；外层已 export 的变量优先。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS:-https://ci.invalid}"
export TRUSTED_HOSTS="${TRUSTED_HOSTS:-api.ci.invalid}"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg2://ci:Xk9mPq2vLw8nRZ42CiDb@127.0.0.1:5432/ci_guard}"
export LOG_FORMAT="${LOG_FORMAT:-json}"
export FILE_READ_ALLOWED_ROOTS="${FILE_READ_ALLOWED_ROOTS:-/tmp,/var/lib/perilla/data}"
export RBAC_DEFAULT_ROLE="${RBAC_DEFAULT_ROLE:-viewer}"
export RBAC_ADMIN_API_KEYS="${RBAC_ADMIN_API_KEYS:-ci-rbac-admin-key-segment-01}"

exec bash scripts/check-security-guardrails.sh
