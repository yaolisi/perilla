#!/usr/bin/env bash
# Prometheus / Alertmanager 静态校验（promtool / amtool）。使用与 deploy/monitoring/docker-compose.monitoring.yml 对齐的镜像版本。
# 无 Docker 且无本地 promtool/amtool 时 exit 0 跳过。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROM_DIR="${ROOT}/deploy/monitoring/prometheus"
AM_DIR="${ROOT}/deploy/monitoring/alertmanager"
PROM_IMG="${MONITORING_PROM_IMAGE:-prom/prometheus:v2.54.1}"
AM_IMG="${MONITORING_ALERTMANAGER_IMAGE:-prom/alertmanager:v0.28.1}"

need_skip() {
  echo "[monitoring-config-check] $1"
  exit 0
}

if [[ ! -f "${PROM_DIR}/prometheus.yml" ]] || [[ ! -f "${PROM_DIR}/alerts.yml" ]]; then
  need_skip "missing prometheus files under deploy/monitoring/prometheus; skip."
fi
if [[ ! -f "${AM_DIR}/alertmanager.yml" ]]; then
  need_skip "missing deploy/monitoring/alertmanager/alertmanager.yml; skip."
fi

run_docker() {
  docker run --rm "$@"
}

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  run_docker -v "${PROM_DIR}:/etc/prometheus:ro" "${PROM_IMG}" promtool check config /etc/prometheus/prometheus.yml
  echo "[monitoring-config-check] OK: prometheus.yml (promtool)"
  run_docker -v "${PROM_DIR}:/etc/prometheus:ro" "${PROM_IMG}" promtool check rules /etc/prometheus/alerts.yml
  echo "[monitoring-config-check] OK: alerts.yml (promtool rules)"
  run_docker -v "${AM_DIR}:/etc/alertmanager:ro" "${AM_IMG}" amtool check-config /etc/alertmanager/alertmanager.yml
  echo "[monitoring-config-check] OK: alertmanager.yml (amtool)"
  exit 0
fi

if command -v promtool >/dev/null 2>&1 && command -v amtool >/dev/null 2>&1; then
  promtool check config "${PROM_DIR}/prometheus.yml"
  promtool check rules "${PROM_DIR}/alerts.yml"
  amtool check-config "${AM_DIR}/alertmanager.yml"
  echo "[monitoring-config-check] OK (local promtool/amtool)"
  exit 0
fi

need_skip "Docker daemon not running and no promtool/amtool in PATH; skip."
