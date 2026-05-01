#!/usr/bin/env bash
# helm lint + helm template smoke checks（未安装 helm 时退出 0，便于本地/CI 可选运行）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHART="${HELM_CHART_DIR:-$ROOT/deploy/helm/perilla-backend}"

if ! command -v helm >/dev/null 2>&1; then
  echo "[helm-chart-check] helm CLI not found; skip."
  exit 0
fi

helm lint "$CHART"

helm template perilla-chart-check "$CHART" >/dev/null

helm template perilla-chart-check "$CHART" --set ingress.enabled=true >/dev/null

helm template perilla-chart-check "$CHART" --set serviceMonitor.enabled=true >/dev/null

helm template perilla-chart-check "$CHART" --set vmServiceScrape.enabled=true >/dev/null

helm template perilla-chart-check "$CHART" --set podDisruptionBudget.enabled=true >/dev/null

helm template perilla-chart-check "$CHART" --set horizontalPodAutoscaler.enabled=true >/dev/null

helm template perilla-chart-check "$CHART" --set serviceAccount.create=true >/dev/null

helm template perilla-chart-check "$CHART" \
  --set networkPolicy.ingress.enabled=true \
  --set networkPolicy.egress.enabled=true >/dev/null

helm template perilla-chart-check "$CHART" --set lifecycle.preStopSleepSeconds=5 >/dev/null

helm template perilla-chart-check "$CHART" \
  --set env.httpMaxRequestBodyBytes=52428800 \
  --set env.securityHeadersEnabled=true >/dev/null

helm template perilla-chart-check "$CHART" --set env.uvicornTimeoutKeepAliveSeconds=75 >/dev/null

helm template perilla-chart-check "$CHART" --set env.uvicornTimeoutGracefulShutdownSeconds=55 >/dev/null

helm template perilla-chart-check "$CHART" \
  --set env.executionKernelDbUrl=postgresql+asyncpg://postgres:5432/ek >/dev/null

helm template perilla-chart-check "$CHART" \
  --set env.securityHeadersEnabled=true \
  --set env.securityHeadersXFrameOptions=SAMEORIGIN >/dev/null

helm template perilla-chart-check "$CHART" --set env.logFormat=json >/dev/null

helm template perilla-chart-check "$CHART" --set env.logLevel=INFO >/dev/null

helm template perilla-chart-check "$CHART" \
  --set env.apiRateLimitRedisUrl=redis://redis:6379/14 >/dev/null

helm template perilla-chart-check "$CHART" \
  --set env.apiRateLimitTrustXForwardedFor=false >/dev/null

helm template perilla-chart-check "$CHART" \
  --set env.trustedHosts=api.example.com >/dev/null

helm template perilla-chart-check "$CHART" \
  --set env.trustedHosts=api.example.com \
  --set env.trustedHostExemptOpsPaths=false >/dev/null

helm template perilla-chart-check "$CHART" \
  --set env.forwardedAllowIps=10.0.0.0/8 >/dev/null

helm template perilla-chart-check "$CHART" \
  --set env.uvicornLimitConcurrency=4096 \
  --set env.uvicornServerHeader=false >/dev/null

helm template perilla-chart-check "$CHART" \
  --set env.uvicornAccessLog=false \
  --set env.uvicornBacklog=4096 >/dev/null

helm template perilla-chart-check "$CHART" \
  --set env.uvicornWsMaxSize=4194304 \
  --set env.uvicornLimitMaxRequestsJitter=500 >/dev/null

helm template perilla-chart-check "$CHART" \
  --set env.uvicornWsPingIntervalSeconds=30 \
  --set env.uvicornWsPingTimeoutSeconds=30 >/dev/null

helm template perilla-chart-check "$CHART" \
  --set env.apiRateLimitRedisFailClosed=true >/dev/null

# DB 连接池回收、推理缓存开关、本地模型目录、CSRF Cookie 细节（与 Settings / deployment 模板对齐）
helm template perilla-chart-check "$CHART" \
  --set env.dbPoolRecycleSeconds=1800 \
  --set env.inferenceCacheEnabled=true \
  --set env.localModelDirectory=/models \
  --set env.autoUnloadLocalModelOnSwitch=false \
  --set env.csrfHeaderName=X-CSRF-Token \
  --set env.csrfCookieName=csrf_token \
  --set env.csrfCookiePath=/api \
  --set env.csrfCookieSamesite=lax \
  --set env.csrfCookieMaxAgeSeconds=7200 >/dev/null

echo "[helm-chart-check] OK: $CHART"
