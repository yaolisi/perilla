#!/usr/bin/env bash
# 使用 kubeconform 离线校验 deploy/k8s/*.yaml（无需集群）。CRD（ServiceMonitor、VMServiceScrape 等）使用 -ignore-missing-schemas。
# 无 Docker 且无本地 kubeconform 可执行文件时 exit 0 跳过。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
K8S="${ROOT}/deploy/k8s"
IMG="${KUBECONFORM_IMAGE:-ghcr.io/yannh/kubeconform:v0.6.7}"
K8S_VER="${KUBECONFORM_K8S_VERSION:-1.31.0}"

if [[ ! -d "$K8S" ]]; then
  echo >&2 "[k8s-manifest-check] missing ${K8S}"
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "[k8s-manifest-check] using ${IMG} (K8s OpenAPI ${K8S_VER})"
  docker run --rm -v "${K8S}:/manifests:ro" "${IMG}" \
    -kubernetes-version "${K8S_VER}" \
    -strict \
    -ignore-missing-schemas \
    -summary \
    /manifests
  echo "[k8s-manifest-check] OK"
  exit 0
fi

if command -v kubeconform >/dev/null 2>&1; then
  kubeconform -kubernetes-version "${K8S_VER}" -strict -ignore-missing-schemas -summary "${K8S}"
  echo "[k8s-manifest-check] OK (local kubeconform)"
  exit 0
fi

echo "[k8s-manifest-check] Docker/kubeconform unavailable; skip."
exit 0
