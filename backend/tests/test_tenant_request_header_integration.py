"""
集成：state.tenant_id 未设置时可读 X-Tenant-Id；已设置但为空串/仅空白时二者均回落 default、不读头。
resolve_api_tenant_id 在无有效 state 时亦永不读头。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from config.settings import settings
from core.utils.tenant_request import get_effective_tenant_id, resolve_api_tenant_id

pytestmark = pytest.mark.tenant_isolation


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/probe/effective")
    def probe_effective(request: Request):
        return {"tenant_id": get_effective_tenant_id(request)}

    @app.get("/probe/api")
    def probe_api(request: Request):
        return {"tenant_id": resolve_api_tenant_id(request)}

    return app


def test_header_only_affects_effective_not_resolve_api():
    hdr = getattr(settings, "tenant_header_name", "X-Tenant-Id")
    default_tid = str(getattr(settings, "tenant_default_id", "default") or "default").strip() or "default"
    client = TestClient(_make_app())
    r_eff = client.get("/probe/effective", headers={hdr: "from-header-tenant"})
    r_api = client.get("/probe/api", headers={hdr: "from-header-tenant"})
    assert r_eff.status_code == 200
    assert r_api.status_code == 200
    assert r_eff.json()["tenant_id"] == "from-header-tenant"
    assert r_api.json()["tenant_id"] == default_tid


def test_middleware_state_wins_for_both_when_set():
    hdr = getattr(settings, "tenant_header_name", "X-Tenant-Id")
    app = _make_app()

    @app.middleware("http")
    async def inject_state(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.tenant_id = "gateway-tenant"
        return await call_next(request)

    client = TestClient(app)
    r_eff = client.get("/probe/effective", headers={hdr: "should-not-win"})
    r_api = client.get("/probe/api", headers={hdr: "should-not-win"})
    assert r_eff.json()["tenant_id"] == "gateway-tenant"
    assert r_api.json()["tenant_id"] == "gateway-tenant"


def test_empty_string_state_both_resolvers_ignore_header_use_default():
    """state.tenant_id == \"\"：与 resolve 一致，不信任客户端头。"""
    hdr = getattr(settings, "tenant_header_name", "X-Tenant-Id")
    default_tid = str(getattr(settings, "tenant_default_id", "default") or "default").strip() or "default"
    app = _make_app()

    @app.middleware("http")
    async def inject_empty_state(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.tenant_id = ""
        return await call_next(request)

    client = TestClient(app)
    r_eff = client.get("/probe/effective", headers={hdr: "header-tenant-x"})
    r_api = client.get("/probe/api", headers={hdr: "header-tenant-x"})
    assert r_eff.json()["tenant_id"] == default_tid
    assert r_api.json()["tenant_id"] == default_tid


def test_whitespace_only_state_both_resolvers_ignore_header_use_default():
    """state 仅为空白：effective 与 resolve_api 均回落 default，不读头。"""
    hdr = getattr(settings, "tenant_header_name", "X-Tenant-Id")
    default_tid = str(getattr(settings, "tenant_default_id", "default") or "default").strip() or "default"
    app = _make_app()

    @app.middleware("http")
    async def inject_ws_state(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.tenant_id = "  \t\n"
        return await call_next(request)

    client = TestClient(app)
    r_eff = client.get("/probe/effective", headers={hdr: "hdr-after-ws"})
    r_api = client.get("/probe/api", headers={hdr: "hdr-after-ws"})
    assert r_eff.json()["tenant_id"] == default_tid
    assert r_api.json()["tenant_id"] == default_tid

