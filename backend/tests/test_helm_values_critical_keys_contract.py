"""Helm values.yaml 顶层须保留运行与发布所需关键块（防误删导致静默降级）。"""

from __future__ import annotations

import pytest

from tests.repo_paths import repo_path

pytestmark = pytest.mark.requires_monorepo

_REQUIRED_TOP_LEVEL = frozenset(
    {
        "containerPort",
        "env",
        "fullnameOverride",
        "horizontalPodAutoscaler",
        "image",
        "ingress",
        "lifecycle",
        "metrics",
        "migrateJob",
        "nameOverride",
        "networkPolicy",
        "podAntiAffinity",
        "podDisruptionBudget",
        "podSecurityContext",
        "probes",
        "replicaCount",
        "resources",
        "secretEnvFrom",
        "securityContext",
        "service",
        "serviceAccount",
        "serviceMonitor",
        "terminationGracePeriodSeconds",
        "topologySpreadConstraints",
        "vmServiceScrape",
    },
)


def _top_level_keys(raw: str) -> set[str]:
    keys: set[str] = set()
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1].isspace():
            continue
        if stripped.startswith("---"):
            continue
        if ":" not in stripped:
            continue
        key = stripped.split(":", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def test_helm_values_env_default_log_format_json_matches_production_structured_logging() -> None:
    """Chart 默认 env.logFormat=json，与 Settings 在生产 debug=false 时要求结构化日志一致。"""
    p = repo_path("deploy/helm/perilla-backend/values.yaml")
    text = p.read_text(encoding="utf-8")
    assert 'logFormat: "json"' in text
    assert "structured" in text.lower() or "LOG_FORMAT" in text


def test_helm_values_preserves_critical_top_level_keys() -> None:
    p = repo_path("deploy/helm/perilla-backend/values.yaml")
    assert p.is_file()
    keys = _top_level_keys(p.read_text(encoding="utf-8"))
    missing = sorted(_REQUIRED_TOP_LEVEL - keys)
    assert not missing, f"values.yaml missing top-level keys: {missing}"
