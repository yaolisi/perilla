#!/usr/bin/env bash
# Dockerfile 最佳实践静态检查（hadolint）。默认仅对 severity ≥ error 失败（可通过 HADOLINT_FAILURE_THRESHOLD 改为 warning）。
# 无 Docker 且无本地 hadolint 时 exit 0 跳过。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMG="${HADOLINT_IMAGE:-hadolint/hadolint:v2.12.0-alpine}"
THRESHOLD="${HADOLINT_FAILURE_THRESHOLD:-error}"

FILES=(
  docker/backend.Dockerfile
  docker/frontend.Dockerfile
)

use_docker=false
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  use_docker=true
elif ! command -v hadolint >/dev/null 2>&1; then
  echo "[dockerfile-hadolint-check] Docker daemon/hadolint unavailable; skip."
  exit 0
fi

for rel in "${FILES[@]}"; do
  abs="${ROOT}/${rel}"
  if [[ ! -f "$abs" ]]; then
    echo "[dockerfile-hadolint-check] skip missing: ${rel}"
    continue
  fi
  echo "[dockerfile-hadolint-check] ${rel}"
  if [[ "$use_docker" == true ]]; then
    # 镜像 ENTRYPOINT 即为 hadolint
    docker run --rm -v "${abs}:/Dockerfile:ro" "${IMG}" \
      --failure-threshold "${THRESHOLD}" --no-color /Dockerfile
  else
    hadolint --failure-threshold "${THRESHOLD}" --no-color "${abs}"
  fi
done

echo "[dockerfile-hadolint-check] OK"
