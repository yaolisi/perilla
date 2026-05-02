"""TenantContextMiddleware：注入非空 tenant_id；可选 tenant_enforcement 对受保护路径强制显式 X-Tenant-Id。"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from config.settings import settings
from middleware.tenant_context import TenantContextMiddleware
from tests.helpers import make_fastapi_app_router_only

pytestmark = pytest.mark.tenant_isolation


@pytest.fixture()
def tenant_probe_app():
    app = make_fastapi_app_router_only()
    app.add_middleware(TenantContextMiddleware)

    @app.get("/_probe/tenant")
    def probe(request: Request):
        tid = getattr(request.state, "tenant_id", None)
        return {"tenant_id": tid, "non_empty": bool(tid and str(tid).strip())}

    return app


def test_tenant_context_missing_header_uses_default(tenant_probe_app, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "tenant_default_id", "default")
    monkeypatch.setattr(settings, "tenant_header_name", "X-Tenant-Id")
    client = TestClient(tenant_probe_app)
    r = client.get("/_probe/tenant")
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == "default"
    assert body["non_empty"] is True


def test_tenant_context_whitespace_header_falls_back_to_default(tenant_probe_app, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "tenant_default_id", "my-default")
    monkeypatch.setattr(settings, "tenant_header_name", "X-Tenant-Id")
    client = TestClient(tenant_probe_app)
    r = client.get("/_probe/tenant", headers={"X-Tenant-Id": "   \t"})
    assert r.status_code == 200
    assert r.json()["tenant_id"] == "my-default"


def test_tenant_context_explicit_header_passthrough(tenant_probe_app, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "tenant_default_id", "default")
    monkeypatch.setattr(settings, "tenant_header_name", "X-Tenant-Id")
    client = TestClient(tenant_probe_app)
    r = client.get("/_probe/tenant", headers={"X-Tenant-Id": " tenant-z "})
    assert r.status_code == 200
    assert r.json()["tenant_id"] == "tenant-z"


def test_tenant_enforcement_returns_400_when_protected_path_missing_explicit_header(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "tenant_enforcement_enabled", True)
    monkeypatch.setattr(settings, "tenant_default_id", "default")
    monkeypatch.setattr(settings, "tenant_header_name", "X-Tenant-Id")

    app = make_fastapi_app_router_only()
    app.add_middleware(TenantContextMiddleware)

    @app.get("/api/v1/workflows/enforce-probe")
    def probe():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/api/v1/workflows/enforce-probe")
    assert r.status_code == 400
    body = r.json()
    assert body.get("detail") == "tenant id required for protected path"
    assert body.get("path") == "/api/v1/workflows/enforce-probe"


def test_tenant_enforcement_allows_protected_path_with_explicit_header(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "tenant_enforcement_enabled", True)
    monkeypatch.setattr(settings, "tenant_default_id", "default")
    monkeypatch.setattr(settings, "tenant_header_name", "X-Tenant-Id")

    app = make_fastapi_app_router_only()
    app.add_middleware(TenantContextMiddleware)

    @app.get("/api/v1/workflows/enforce-probe")
    def probe(request: Request):
        return {"tid": getattr(request.state, "tenant_id", None)}

    client = TestClient(app)
    r = client.get("/api/v1/workflows/enforce-probe", headers={"X-Tenant-Id": "explicit-tenant"})
    assert r.status_code == 200
    assert r.json()["tid"] == "explicit-tenant"


def test_tenant_enforcement_disabled_allows_missing_header_on_protected_path(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "tenant_enforcement_enabled", False)
    monkeypatch.setattr(settings, "tenant_default_id", "fallback-default")
    monkeypatch.setattr(settings, "tenant_header_name", "X-Tenant-Id")

    app = make_fastapi_app_router_only()
    app.add_middleware(TenantContextMiddleware)

    @app.get("/api/v1/workflows/enforce-probe")
    def probe(request: Request):
        return {"tid": getattr(request.state, "tenant_id", None)}

    client = TestClient(app)
    r = client.get("/api/v1/workflows/enforce-probe")
    assert r.status_code == 200
    assert r.json()["tid"] == "fallback-default"
