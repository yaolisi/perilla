#!/usr/bin/env bash
# 校验 Docker Compose 合并 YAML（docker compose config）；不上传镜像、不启动容器。
# 无 compose 子命令时 exit 0 跳过；daemon 不可连时 skip（本地未开 Docker Desktop 等）。
# YAML/合并错误时 exit 1。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
else
  echo "[compose-config-check] docker compose not found; skip."
  exit 0
fi

daemon_skip_ok() {
  local msg="$1"
  # macOS/Linux 常见文案（不完全穷尽；未知失败仍会打印 stderr）
  if echo "$msg" | grep -qiE 'cannot connect to the docker daemon|docker daemon is not running|Is the docker daemon running'; then
    echo "[compose-config-check] Docker daemon not reachable; skip."
    exit 0
  fi
}

run_merge() {
  local label="$1"
  shift
  local out ec
  set +e
  out="$("$@" 2>&1)"
  ec=$?
  set -e
  if [[ "$ec" -ne 0 ]]; then
    daemon_skip_ok "$out"
    echo >&2 "$out"
    exit 1
  fi
  echo "[compose-config-check] OK: ${label}"
}

run_merge "docker-compose.yml" "${DC[@]}" -f docker-compose.yml config
run_merge "docker-compose.yml + docker-compose.prod.yml" "${DC[@]}" -f docker-compose.yml -f docker-compose.prod.yml config
