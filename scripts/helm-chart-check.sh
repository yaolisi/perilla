#!/usr/bin/env bash
# helm lint + helm template smoke checks。
# 优先级：本地 helm → Docker（alpine/helm，默认与 CI Helm 3.14 对齐）→ 无则 exit 0 跳过（与旧行为一致）。
# 覆盖环境：HELM_DOCKER_IMAGE（默认 alpine/helm:3.14.4，与 .github/workflows 中 setup-helm v3.14.4 一致）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHART="${HELM_CHART_DIR:-$ROOT/deploy/helm/perilla-backend}"
HELM_DOCKER_IMAGE="${HELM_DOCKER_IMAGE:-alpine/helm:3.14.4}"

use_docker=false
if command -v helm >/dev/null 2>&1; then
  :
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  use_docker=true
  echo "[helm-chart-check] no local helm; using Docker image ${HELM_DOCKER_IMAGE}"
else
  echo "[helm-chart-check] helm CLI not found (and Docker unavailable or daemon not running); skip."
  exit 0
fi

run_helm() {
  if [[ "$use_docker" == true ]]; then
    docker run --rm \
      -v "$ROOT:$ROOT" \
      -w "$ROOT" \
      "$HELM_DOCKER_IMAGE" \
      "$@"
  else
    helm "$@"
  fi
}

run_helm lint "$CHART"

run_helm template perilla-chart-check "$CHART" >/dev/null

run_helm template perilla-chart-check "$CHART" --set ingress.enabled=true >/dev/null

run_helm template perilla-chart-check "$CHART" --set serviceMonitor.enabled=true >/dev/null

run_helm template perilla-chart-check "$CHART" --set vmServiceScrape.enabled=true >/dev/null

run_helm template perilla-chart-check "$CHART" --set podDisruptionBudget.enabled=true >/dev/null

run_helm template perilla-chart-check "$CHART" --set horizontalPodAutoscaler.enabled=true >/dev/null

run_helm template perilla-chart-check "$CHART" --set serviceAccount.create=true >/dev/null

run_helm template perilla-chart-check "$CHART" \
  --set networkPolicy.ingress.enabled=true \
  --set networkPolicy.egress.enabled=true >/dev/null

run_helm template perilla-chart-check "$CHART" --set lifecycle.preStopSleepSeconds=5 >/dev/null

run_helm template perilla-chart-check "$CHART" \
  --set env.httpMaxRequestBodyBytes=52428800 \
  --set env.securityHeadersEnabled=true >/dev/null

run_helm template perilla-chart-check "$CHART" --set env.uvicornTimeoutKeepAliveSeconds=75 >/dev/null

run_helm template perilla-chart-check "$CHART" --set env.uvicornTimeoutGracefulShutdownSeconds=55 >/dev/null

run_helm template perilla-chart-check "$CHART" \
  --set env.executionKernelDbUrl=postgresql+asyncpg://postgres:5432/ek >/dev/null

run_helm template perilla-chart-check "$CHART" \
  --set env.securityHeadersEnabled=true \
  --set env.securityHeadersXFrameOptions=SAMEORIGIN >/dev/null

run_helm template perilla-chart-check "$CHART" --set env.logFormat=json >/dev/null

run_helm template perilla-chart-check "$CHART" --set env.logLevel=INFO >/dev/null

run_helm template perilla-chart-check "$CHART" \
  --set env.apiRateLimitRedisUrl=redis://redis:6379/14 >/dev/null

run_helm template perilla-chart-check "$CHART" \
  --set env.apiRateLimitTrustXForwardedFor=false >/dev/null

run_helm template perilla-chart-check "$CHART" \
  --set env.trustedHosts=api.example.com >/dev/null

run_helm template perilla-chart-check "$CHART" \
  --set env.trustedHosts=api.example.com \
  --set env.trustedHostExemptOpsPaths=false >/dev/null

run_helm template perilla-chart-check "$CHART" \
  --set env.forwardedAllowIps=10.0.0.0/8 >/dev/null

run_helm template perilla-chart-check "$CHART" \
  --set env.uvicornLimitConcurrency=4096 \
  --set env.uvicornServerHeader=false >/dev/null

run_helm template perilla-chart-check "$CHART" \
  --set env.uvicornAccessLog=false \
  --set env.uvicornBacklog=4096 >/dev/null

run_helm template perilla-chart-check "$CHART" \
  --set env.uvicornWsMaxSize=4194304 \
  --set env.uvicornLimitMaxRequestsJitter=500 >/dev/null

run_helm template perilla-chart-check "$CHART" \
  --set env.uvicornWsPingIntervalSeconds=30 \
  --set env.uvicornWsPingTimeoutSeconds=30 >/dev/null

run_helm template perilla-chart-check "$CHART" \
  --set env.apiRateLimitRedisFailClosed=true >/dev/null

# DB 连接池回收、推理缓存开关、本地模型目录、CSRF Cookie 细节（与 Settings / deployment 模板对齐）
run_helm template perilla-chart-check "$CHART" \
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
