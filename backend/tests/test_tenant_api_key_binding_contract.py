"""
TenantApiKeyBindingMiddleware：受保护路径上校验 API Key 与租户；外层先于 TenantContext 时须能从 X-Tenant-Id 回落。

与 main.py 注册顺序一致：先 TenantContextMiddleware，后 TenantApiKeyBindingMiddleware
→ 请求进入时 Starlette 先执行后注册的外层，故绑定中间件运行时 state.tenant_id 可能尚未注入。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from config.settings import settings
from middleware.tenant_context import TenantContextMiddleware
from middleware.tenant_key_binding import TenantApiKeyBindingMiddleware
from tests.helpers import make_fastapi_app_router_only

pytestmark = pytest.mark.tenant_isolation


def _protected_route(app: FastAPI) -> None:
    @app.get("/api/v1/workflows/ping")
    def ping():
        return {"ok": True}


@pytest.fixture()
def key_binding_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "tenant_api_key_binding_enabled", True)
    monkeypatch.setattr(settings, "tenant_api_key_tenants_json", '{"k-a":["tenant-a"], "k-star":["*"]}')
    monkeypatch.setattr(settings, "tenant_default_id", "default")
    monkeypatch.setattr(settings, "tenant_header_name", "X-Tenant-Id")
    monkeypatch.setattr(settings, "api_rate_limit_api_key_header", "X-Api-Key")


def test_binding_reads_tenant_from_header_without_tenant_context_middleware(
    key_binding_settings,
):
    """仅挂载 TenantApiKeyBinding：尚无 state 注入，tenant_id 须来自头（与 dispatch 回落分支一致）。"""
    app = make_fastapi_app_router_only()
    app.add_middleware(TenantApiKeyBindingMiddleware)
    _protected_route(app)
    client = TestClient(app)
    r = client.get(
        "/api/v1/workflows/ping",
        headers={"X-Api-Key": "k-a", "X-Tenant-Id": "tenant-a"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_binding_same_as_main_middleware_stack_order(key_binding_settings):
    """与 main.py 相同：先 TenantContext 再 TenantApiKeyBinding（后注册者先执行）。"""
    app = make_fastapi_app_router_only()
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(TenantApiKeyBindingMiddleware)
    _protected_route(app)
    client = TestClient(app)
    r = client.get(
        "/api/v1/workflows/ping",
        headers={"X-Api-Key": "k-a", "X-Tenant-Id": "tenant-a"},
    )
    assert r.status_code == 200


def test_binding_rejects_tenant_not_allowed_for_key(key_binding_settings):
    app = make_fastapi_app_router_only()
    app.add_middleware(TenantApiKeyBindingMiddleware)
    _protected_route(app)
    client = TestClient(app)
    r = client.get(
        "/api/v1/workflows/ping",
        headers={"X-Api-Key": "k-a", "X-Tenant-Id": "tenant-b"},
    )
    assert r.status_code == 403


def test_binding_star_mapping_accepts_any_tenant(key_binding_settings):
    app = make_fastapi_app_router_only()
    app.add_middleware(TenantApiKeyBindingMiddleware)
    _protected_route(app)
    client = TestClient(app)
    r = client.get(
        "/api/v1/workflows/ping",
        headers={"X-Api-Key": "k-star", "X-Tenant-Id": "arbitrary-tenant-99"},
    )
    assert r.status_code == 200


def test_binding_requires_api_key_on_protected_path(key_binding_settings):
    app = make_fastapi_app_router_only()
    app.add_middleware(TenantApiKeyBindingMiddleware)
    _protected_route(app)
    client = TestClient(app)
    r = client.get("/api/v1/workflows/ping", headers={"X-Tenant-Id": "tenant-a"})
    assert r.status_code == 403
    assert "api key" in str(r.json().get("detail", "")).lower()


def test_binding_skips_when_path_not_in_tenant_enforcement_list(key_binding_settings):
    """非 tenant_paths 受控前缀：不强制 API Key（与 is_tenant_enforcement_protected_path 一致）。"""
    app = make_fastapi_app_router_only()
    app.add_middleware(TenantApiKeyBindingMiddleware)

    @app.get("/api/unlisted/ping")
    def unlisted():
        return {"free": True}

    client = TestClient(app)
    r = client.get("/api/unlisted/ping")
    assert r.status_code == 200
    assert r.json() == {"free": True}


def test_binding_rejects_unknown_api_key(key_binding_settings):
    app = make_fastapi_app_router_only()
    app.add_middleware(TenantApiKeyBindingMiddleware)
    _protected_route(app)
    client = TestClient(app)
    r = client.get(
        "/api/v1/workflows/ping",
        headers={"X-Api-Key": "no-such-key", "X-Tenant-Id": "tenant-a"},
    )
    assert r.status_code == 403
    assert "tenant-bound" in str(r.json().get("detail", "")).lower()


def test_main_stack_order_state_tenant_matches_header_after_both_middlewares(
    key_binding_settings,
):
    """与 main 一致：先 TenantContext 再 TenantApiKeyBinding；通过后路由可见 state.tenant_id。"""
    app = make_fastapi_app_router_only()
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(TenantApiKeyBindingMiddleware)

    @app.get("/api/v1/workflows/stack-state")
    def stack_state(request: Request):
        return {"tid": getattr(request.state, "tenant_id", None)}

    client = TestClient(app)
    r = client.get(
        "/api/v1/workflows/stack-state",
        headers={"X-Api-Key": "k-a", "X-Tenant-Id": "tenant-a"},
    )
    assert r.status_code == 200
    assert r.json()["tid"] == "tenant-a"
