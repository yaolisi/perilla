"""根目录 docker-compose 须保留生产对齐提示（与 K8s Secret 示例一致）。"""

from __future__ import annotations

import pytest

from tests.repo_paths import repo_path

pytestmark = pytest.mark.requires_monorepo


def test_docker_compose_prod_override_documents_security_defaults() -> None:
    """docker-compose.prod.yml 须保留生产护栏默认（与 base compose / K8s 示例一致）。"""
    p = repo_path("docker-compose.prod.yml")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert 'DEBUG: "false"' in text
    assert "CSRF_COOKIE_SECURE" in text
    assert "HTTP_MAX_REQUEST_BODY_BYTES" in text
    assert "validate_production_security_guardrails" in text
    assert "SECURITY_GUARDRAILS_STRICT" in text
    assert "backend:" in text
    assert "ports: []" in text


def test_docker_compose_documents_production_database_and_trust_xff_hints() -> None:
    p = repo_path("docker-compose.yml")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "DATABASE_URL" in text
    assert "postgresql" in text
    assert "API_RATE_LIMIT_TRUST_X_FORWARDED_FOR" in text
    assert "TRUSTED_HOSTS" in text
    assert "TRUSTED_HOST_EXEMPT_OPS_PATHS" in text
    assert "FORWARDED_ALLOW_IPS" in text
    assert "UVICORN_SERVER_HEADER" in text
    assert "UVICORN_ACCESS_LOG" in text
    assert "UVICORN_BACKLOG" in text
    assert "UVICORN_WS_MAX_SIZE" in text
    assert "UVICORN_WS_PING_INTERVAL_SECONDS" in text
    assert "validate_production_security_guardrails" in text
