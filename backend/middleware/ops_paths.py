"""
运维相关 HTTP 路径（与 settings.prometheus_metrics_path 对齐），供中间件共用以防分叉。
"""

from __future__ import annotations

from config.settings import settings

_FALLBACK_METRICS_PATH = "/metrics"


def get_prometheus_metrics_path() -> str:
    raw = getattr(settings, "prometheus_metrics_path", _FALLBACK_METRICS_PATH)
    return str(raw or _FALLBACK_METRICS_PATH).strip() or _FALLBACK_METRICS_PATH


def is_prometheus_metrics_path(path: str) -> bool:
    return (path or "") == get_prometheus_metrics_path()


def is_api_health_path(path: str) -> bool:
    return (path or "").startswith("/api/health")


def is_ops_probe_or_metrics_path(path: str) -> bool:
    """健康探针或 Prometheus 抓取路径（限流豁免、低噪声日志、跳过 gzip 等）。"""
    return is_api_health_path(path) or is_prometheus_metrics_path(path)
