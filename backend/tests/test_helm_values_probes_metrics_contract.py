"""Helm 默认 probes / metrics 路径须与网关健康检查与 Prometheus 抓取路径一致（deploy/k8s 示例与 NOTES 亦对齐）。"""

from __future__ import annotations

import re

import pytest

from tests.repo_paths import repo_path

pytestmark = pytest.mark.requires_monorepo

# 与 backend main 注册的 /api/health、/api/health/ready、默认 Prometheus 路径一致
_PROBE_PATHS = (
    ("startup", "/api/health"),
    ("liveness", "/api/health"),
    ("readiness", "/api/health/ready"),
)

_METRICS_PATH_RE = re.compile(r"(?m)^metrics:\s*\n\s+path:\s+/metrics\s*$")


def test_helm_values_default_probe_paths() -> None:
    raw = repo_path("deploy/helm/perilla-backend/values.yaml").read_text(encoding="utf-8")
    for kind, expected in _PROBE_PATHS:
        pat = rf"(?m)^\s+{re.escape(kind)}:\s*\n\s+path:\s+{re.escape(expected)}\s*$"
        assert re.search(pat, raw), f"values.yaml probes.{kind}.path must be {expected!r}"


def test_helm_values_default_metrics_path() -> None:
    raw = repo_path("deploy/helm/perilla-backend/values.yaml").read_text(encoding="utf-8")
    assert _METRICS_PATH_RE.search(raw), "values.yaml metrics.path must default to /metrics"
