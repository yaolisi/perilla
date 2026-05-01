"""
契约：运维面（/api/health*、settings.prometheus_metrics_path）在严格安全中间件栈下
仍应对匿名抓取/探针可用，避免误伤 Kubernetes 与 Prometheus。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.settings import settings
from middleware.api_key_scope import ApiKeyScopeMiddleware
from middleware.csrf_protection import CSRFMiddleware
from middleware.rbac_context import RBACContextMiddleware
from middleware.rbac_enforcement import RBACEnforcementMiddleware
from middleware.sensitive_data_redaction import SensitiveDataRedactionMiddleware
from middleware.tenant_context import TenantContextMiddleware
from middleware.tenant_key_binding import TenantApiKeyBindingMiddleware
from middleware.user_context import UserContextMiddleware


def test_ops_paths_anonymous_under_strict_middleware_stack(monkeypatch):
    """租户强制 + Key 绑定 + RBAC(viewer) + CSRF 下，探针与 metrics 仍 200。"""
    prev_tenant_enf = settings.tenant_enforcement_enabled
    prev_bind = settings.tenant_api_key_binding_enabled
    prev_map = settings.tenant_api_key_tenants_json
    prev_rbac = settings.rbac_enabled
    prev_rbac_enf = settings.rbac_enforcement
    prev_viewer = settings.rbac_viewer_api_keys
    prev_csrf = settings.csrf_enabled
    prev_metrics_path = settings.prometheus_metrics_path
    try:
        settings.tenant_enforcement_enabled = True
        settings.tenant_api_key_binding_enabled = True
        # k-t 绑定 default：便于在无租户头时仍通过 Key 绑定，从而命中租户强制 400
        settings.tenant_api_key_tenants_json = '{"k-t":["default"]}'
        settings.rbac_enabled = True
        settings.rbac_enforcement = True
        settings.rbac_viewer_api_keys = "viewer-k"
        settings.csrf_enabled = True
        settings.prometheus_metrics_path = "/custom/metrics"

        app = FastAPI()
        app.add_middleware(TenantContextMiddleware)
        app.add_middleware(TenantApiKeyBindingMiddleware)
        app.add_middleware(ApiKeyScopeMiddleware)
        app.add_middleware(CSRFMiddleware)
        app.add_middleware(RBACContextMiddleware, api_key_header="X-Api-Key")
        app.add_middleware(UserContextMiddleware)
        app.add_middleware(SensitiveDataRedactionMiddleware)
        app.add_middleware(RBACEnforcementMiddleware)

        @app.get("/api/health")
        def health():
            return {"status": "ok"}

        @app.get("/custom/metrics")
        def metrics_text():
            return "# TYPE x gauge\nx 1\n"

        @app.get("/api/v1/workflows/w1")
        def wf():
            return {"workflow": "w1"}

        client = TestClient(app)

        h = client.get("/api/health")
        assert h.status_code == 200, h.text

        m = client.get("/custom/metrics")
        assert m.status_code == 200, m.text
        assert "x 1" in m.text

        # 受保护控制面：无 Key 时 Key 绑定先于租户头校验 → 403（与 main 中间件顺序一致）
        no_key = client.get("/api/v1/workflows/w1")
        assert no_key.status_code == 403

        # 有 Key 但缺租户头：租户强制仍生效 → 400
        need_tenant = client.get(
            "/api/v1/workflows/w1",
            headers={"X-Api-Key": "k-t"},
        )
        assert need_tenant.status_code == 400

        wrong_tenant = client.get(
            "/api/v1/workflows/w1",
            headers={"X-Api-Key": "k-t", "X-Tenant-Id": "other"},
        )
        assert wrong_tenant.status_code == 403  # 非绑定租户

        # viewer 角色仍可 GET 运维面
        viewer_h = client.get("/api/health", headers={"X-Api-Key": "viewer-k"})
        assert viewer_h.status_code == 200
    finally:
        settings.tenant_enforcement_enabled = prev_tenant_enf
        settings.tenant_api_key_binding_enabled = prev_bind
        settings.tenant_api_key_tenants_json = prev_map
        settings.rbac_enabled = prev_rbac
        settings.rbac_enforcement = prev_rbac_enf
        settings.rbac_viewer_api_keys = prev_viewer
        settings.csrf_enabled = prev_csrf
        settings.prometheus_metrics_path = prev_metrics_path


def test_configure_prometheus_metrics_skips_instrumentation_when_disabled(monkeypatch):
    import main as main_mod

    monkeypatch.setattr(settings, "prometheus_enabled", False)
    app = FastAPI()
    before = len(app.routes)
    main_mod._configure_prometheus_metrics(app)
    assert len(app.routes) == before


def test_audit_should_audit_skips_ops_paths_even_with_broad_prefix(monkeypatch):
    """宽泛前缀 /api 不得审计探针与 metrics。"""
    from middleware.audit_log import AuditLogMiddleware

    prev_enabled = settings.audit_log_enabled
    prev_prefixes = settings.audit_log_path_prefixes
    prev_metrics = settings.prometheus_metrics_path
    try:
        settings.audit_log_enabled = True
        settings.audit_log_path_prefixes = "/api"
        settings.prometheus_metrics_path = "/prom/m"
        mw = AuditLogMiddleware(object())
        assert mw._should_audit("/api/health") is False
        assert mw._should_audit("/api/health/ready") is False
        assert mw._should_audit("/prom/m") is False
        assert mw._should_audit("/api/v1/workflows/w1") is True
    finally:
        settings.audit_log_enabled = prev_enabled
        settings.audit_log_path_prefixes = prev_prefixes
        settings.prometheus_metrics_path = prev_metrics


def test_configure_prometheus_metrics_exposes_custom_path_when_deps_installed(monkeypatch):
    pytest.importorskip("prometheus_fastapi_instrumentator")
    import main as main_mod

    monkeypatch.setattr(settings, "prometheus_enabled", True)
    monkeypatch.setattr(settings, "prometheus_metrics_path", "/z/metrics")
    app = FastAPI()
    main_mod._configure_prometheus_metrics(app)
    paths = []
    for r in app.routes:
        p = getattr(r, "path", None)
        if p:
            paths.append(p)
    assert "/z/metrics" in paths
