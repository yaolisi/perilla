"""middleware.ops_paths 与 settings 对齐。"""

from __future__ import annotations

import pytest

import middleware.ops_paths as ops_paths


def test_get_prometheus_metrics_path_follows_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ops_paths.settings, "prometheus_metrics_path", "/custom/m")
    assert ops_paths.get_prometheus_metrics_path() == "/custom/m"
    assert ops_paths.is_prometheus_metrics_path("/custom/m")
    assert not ops_paths.is_prometheus_metrics_path("/metrics")


def test_is_ops_probe_or_metrics_path(monkeypatch: pytest.MonkeyPatch):
    assert ops_paths.is_ops_probe_or_metrics_path("/api/health")
    assert ops_paths.is_ops_probe_or_metrics_path("/api/health/ready")
    monkeypatch.setattr(ops_paths.settings, "prometheus_metrics_path", "/z")
    assert ops_paths.is_ops_probe_or_metrics_path("/z")
