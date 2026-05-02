"""GET/POST /api/system/feature-flags 使用 resolve_api_tenant_id，与存储键 featureFlags:<tenant> 一致。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import system as system_api
from config.settings import settings
from tests.helpers import make_fastapi_app_router_only

pytestmark = pytest.mark.tenant_isolation


def _client(state_tenant: str | None) -> TestClient:
    app = make_fastapi_app_router_only(system_api)

    if state_tenant is not None:

        @app.middleware("http")
        async def inject(request, call_next):  # type: ignore[no-untyped-def]
            request.state.tenant_id = state_tenant
            return await call_next(request)

    app.dependency_overrides[system_api.require_authenticated_platform_admin] = lambda: None
    app.dependency_overrides[system_api.require_platform_admin] = lambda: None
    return TestClient(app)


def test_feature_flags_get_uses_resolve_api_tenant_default(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str | None] = []

    def fake_get(tenant_id=None):  # type: ignore[no-untyped-def]
        captured.append(tenant_id)
        return {}

    monkeypatch.setattr(system_api, "get_feature_flags", fake_get)
    client = _client(None)
    r = client.get("/api/system/feature-flags")
    assert r.status_code == 200
    default_tid = str(getattr(settings, "tenant_default_id", "default") or "default").strip() or "default"
    assert captured == [default_tid]
    assert r.json().get("tenant_id") == default_tid


def test_feature_flags_post_uses_resolve_api_tenant_from_state(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str | None] = []

    def fake_set(flags, tenant_id=None):  # type: ignore[no-untyped-def]
        captured.append(tenant_id)
        return {"x": True}

    monkeypatch.setattr(system_api, "set_feature_flags", fake_set)
    client = _client("tenant_ff_acme")
    r = client.post("/api/system/feature-flags", json={"flags": {"x": True}})
    assert r.status_code == 200
    assert captured == ["tenant_ff_acme"]
    assert r.json().get("tenant_id") == "tenant_ff_acme"
