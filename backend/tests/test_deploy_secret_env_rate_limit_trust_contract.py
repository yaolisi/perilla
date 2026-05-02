"""Secret 示例须保留 API_RATE_LIMIT_TRUST_X_FORWARDED_FOR 运维提示（防误删）。"""

from __future__ import annotations

import pytest

from tests.repo_paths import repo_path


@pytest.mark.requires_monorepo
def test_secret_env_example_documents_rate_limit_trust_x_forwarded_for() -> None:
    p = repo_path("deploy/k8s/secret-env.example.yaml")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "API_RATE_LIMIT_TRUST_X_FORWARDED_FOR" in text
    assert "X-Forwarded-For" in text


@pytest.mark.requires_monorepo
def test_secret_env_example_documents_api_rate_limit_events_execution_kernel() -> None:
    """secret 示例须保留 /api/events 专用限流变量提示（与 Helm apiRateLimitEvents* 对齐）。"""
    p = repo_path("deploy/k8s/secret-env.example.yaml")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "API_RATE_LIMIT_EVENTS_REQUESTS" in text
    assert "API_RATE_LIMIT_EVENTS_PATH_PREFIX" in text
    assert "/api/events" in text
    assert "EVENTS_API_REQUIRE_AUTHENTICATED" in text
    assert "EVENTS_STRICT_WORKFLOW_BINDING" in text
