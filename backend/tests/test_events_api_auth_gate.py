"""可选强制鉴权：/api/events 须 API Key + admin（与 system/mcp 对齐）。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from api import events as events_api
from tests.helpers import make_fastapi_app_router_only

pytestmark = pytest.mark.no_fallback


def test_events_api_auth_gate_skips_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events_api, "get_events_api_require_authenticated", lambda: False)
    spy = MagicMock()
    monkeypatch.setattr(events_api, "require_authenticated_platform_admin", spy)
    req = MagicMock(spec=Request)
    events_api._enforce_events_api_authentication(req)
    spy.assert_not_called()


def test_events_api_auth_gate_calls_admin_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events_api, "get_events_api_require_authenticated", lambda: True)
    spy = MagicMock()
    monkeypatch.setattr(events_api, "require_authenticated_platform_admin", spy)
    req = MagicMock(spec=Request)
    events_api._enforce_events_api_authentication(req)
    spy.assert_called_once_with(req)


def test_events_api_returns_401_when_auth_required_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events_api, "get_events_api_require_authenticated", lambda: True)

    app = make_fastapi_app_router_only(events_api)

    @app.middleware("http")
    async def _tenant(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.tenant_id = "default"
        return await call_next(request)

    client = TestClient(app)
    r = client.get("/api/events/instance/gi-not-found-test")
    assert r.status_code == 401
