"""deploy/k8s 示例清单须与 Helm values 默认值对齐（端口、探针路径），避免文档与 Chart 分叉。"""

from __future__ import annotations

import re

import pytest

from tests.repo_paths import repo_path

pytestmark = pytest.mark.requires_monorepo

_EXPECTED_PROBE_PATHS = (
    ("startupProbe", "/api/health"),
    ("livenessProbe", "/api/health"),
    ("readinessProbe", "/api/health/ready"),
)


def test_backend_deployment_example_port_and_probes() -> None:
    raw = repo_path("deploy/k8s/backend-deployment.example.yaml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^\s+containerPort:\s+8000\s*$", raw), (
        "backend-deployment.example.yaml must use containerPort 8000"
    )
    assert re.search(
        r"(?ms)^\s+- name: PORT\s*$\n\s+value:\s+\"8000\"\s*$",
        raw,
    ), "backend-deployment.example.yaml must set PORT=8000 for the backend container"

    for probe, path in _EXPECTED_PROBE_PATHS:
        pat = rf"(?ms)^\s+{probe}:\s*\n\s+httpGet:\s*\n\s+path:\s+{re.escape(path)}\s*\n\s+port:\s+http\s*$"
        assert re.search(pat, raw), f"{probe} path must be {path!r} in backend-deployment.example.yaml"


def test_backend_service_example_port() -> None:
    raw = repo_path("deploy/k8s/service-backend.example.yaml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^\s+port:\s+8000\s*$", raw), "service-backend.example.yaml port must be 8000"
    assert "targetPort: http" in raw or re.search(r"(?m)^\s+targetPort:\s+http\s*$", raw)


def test_backend_deployment_example_security_context_matches_helm_defaults() -> None:
    """Pod + 容器 securityContext 须与 Helm values / Dockerfile（UID/GID 1000）一致。"""
    raw = repo_path("deploy/k8s/backend-deployment.example.yaml").read_text(encoding="utf-8")
    assert raw.count("runAsUser: 1000") >= 2
    assert raw.count("runAsNonRoot: true") >= 2
    assert "runAsGroup: 1000" in raw
    assert "fsGroup: 1000" in raw
    assert "allowPrivilegeEscalation: false" in raw
    assert "capabilities:" in raw and "drop:" in raw and "- ALL" in raw
