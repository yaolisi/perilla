"""Helm NOTES 须保留关键 env 映射提示（防安装后漏配）。"""

from __future__ import annotations

import pytest

from tests.repo_paths import repo_path


@pytest.mark.requires_monorepo
def test_helm_notes_documents_api_rate_limit_trust_x_forwarded_mapping() -> None:
    p = repo_path("deploy/helm/perilla-backend/templates/NOTES.txt")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "apiRateLimitTrustXForwardedFor" in text
    assert "API_RATE_LIMIT_TRUST_X_FORWARDED_FOR" in text


@pytest.mark.requires_monorepo
def test_helm_notes_documents_api_rate_limit_events_path_mapping() -> None:
    p = repo_path("deploy/helm/perilla-backend/templates/NOTES.txt")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "apiRateLimitEventsRequests" in text
    assert "API_RATE_LIMIT_EVENTS_REQUESTS" in text
    assert "apiRateLimitEventsPathPrefix" in text
    assert "API_RATE_LIMIT_EVENTS_PATH_PREFIX" in text


@pytest.mark.requires_monorepo
def test_helm_notes_documents_events_api_guardrails_mapping() -> None:
    p = repo_path("deploy/helm/perilla-backend/templates/NOTES.txt")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "eventsStrictWorkflowBinding" in text
    assert "EVENTS_STRICT_WORKFLOW_BINDING" in text
    assert "eventsApiRequireAuthenticated" in text
    assert "EVENTS_API_REQUIRE_AUTHENTICATED" in text


@pytest.mark.requires_monorepo
def test_helm_notes_documents_rbac_api_keys_production_guardrail() -> None:
    p = repo_path("deploy/helm/perilla-backend/templates/NOTES.txt")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "rbacAdminApiKeys" in text
    assert "validate_production_security_guardrails" in text
    assert "至少" in text
    assert "分段≥12" in text or "分段" in text
    assert "viewer" in text.lower()


@pytest.mark.requires_monorepo
def test_helm_notes_documents_trusted_hosts_mapping() -> None:
    p = repo_path("deploy/helm/perilla-backend/templates/NOTES.txt")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "trustedHosts" in text
    assert "TRUSTED_HOSTS" in text


@pytest.mark.requires_monorepo
def test_helm_notes_documents_trusted_host_exempt_ops_paths_mapping() -> None:
    p = repo_path("deploy/helm/perilla-backend/templates/NOTES.txt")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "trustedHostExemptOpsPaths" in text
    assert "TRUSTED_HOST_EXEMPT_OPS_PATHS" in text


@pytest.mark.requires_monorepo
def test_helm_notes_documents_forwarded_allow_ips_mapping() -> None:
    p = repo_path("deploy/helm/perilla-backend/templates/NOTES.txt")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "forwardedAllowIps" in text
    assert "FORWARDED_ALLOW_IPS" in text


@pytest.mark.requires_monorepo
def test_helm_notes_documents_uvicorn_limit_env_mappings() -> None:
    p = repo_path("deploy/helm/perilla-backend/templates/NOTES.txt")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "uvicornLimitConcurrency" in text
    assert "UVICORN_LIMIT_CONCURRENCY" in text
    assert "uvicornServerHeader" in text
    assert "UVICORN_SERVER_HEADER" in text


@pytest.mark.requires_monorepo
def test_helm_notes_documents_uvicorn_access_log_and_backlog() -> None:
    p = repo_path("deploy/helm/perilla-backend/templates/NOTES.txt")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "uvicornAccessLog" in text
    assert "UVICORN_ACCESS_LOG" in text
    assert "uvicornBacklog" in text
    assert "UVICORN_BACKLOG" in text


@pytest.mark.requires_monorepo
def test_helm_notes_documents_uvicorn_ws_and_jitter_and_date_header() -> None:
    p = repo_path("deploy/helm/perilla-backend/templates/NOTES.txt")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "uvicornWsMaxSize" in text
    assert "UVICORN_WS_MAX_SIZE" in text
    assert "uvicornLimitMaxRequestsJitter" in text
    assert "UVICORN_LIMIT_MAX_REQUESTS_JITTER" in text
    assert "uvicornDateHeader" in text
    assert "UVICORN_DATE_HEADER" in text


@pytest.mark.requires_monorepo
def test_helm_notes_documents_uvicorn_ws_ping_and_worker_healthcheck() -> None:
    p = repo_path("deploy/helm/perilla-backend/templates/NOTES.txt")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "uvicornWsPingIntervalSeconds" in text
    assert "UVICORN_WS_PING_INTERVAL_SECONDS" in text
    assert "uvicornWsPingTimeoutSeconds" in text
    assert "UVICORN_WS_PING_TIMEOUT_SECONDS" in text
    assert "uvicornTimeoutWorkerHealthcheckSeconds" in text
    assert "UVICORN_TIMEOUT_WORKER_HEALTHCHECK_SECONDS" in text


@pytest.mark.requires_monorepo
def test_helm_notes_documents_pool_inference_local_csrf_extended_mappings() -> None:
    """连接池回收、推理缓存总开关、本地模型与 CSRF 扩展项（与 values / deployment 同步）。"""
    p = repo_path("deploy/helm/perilla-backend/templates/NOTES.txt")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    pairs = (
        ("dbPoolRecycleSeconds", "DB_POOL_RECYCLE_SECONDS"),
        ("inferenceCacheEnabled", "INFERENCE_CACHE_ENABLED"),
        ("localModelDirectory", "LOCAL_MODEL_DIRECTORY"),
        ("autoUnloadLocalModelOnSwitch", "AUTO_UNLOAD_LOCAL_MODEL_ON_SWITCH"),
        ("csrfHeaderName", "CSRF_HEADER_NAME"),
        ("csrfCookieName", "CSRF_COOKIE_NAME"),
        ("csrfCookiePath", "CSRF_COOKIE_PATH"),
        ("csrfCookieSamesite", "CSRF_COOKIE_SAMESITE"),
        ("csrfCookieMaxAgeSeconds", "CSRF_COOKIE_MAX_AGE_SECONDS"),
    )
    for camel, upper in pairs:
        assert camel in text, f"missing NOTES mapping key: {camel}"
        assert upper in text, f"missing NOTES env name: {upper}"
