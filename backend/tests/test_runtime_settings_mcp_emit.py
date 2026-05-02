"""Runtime settings + system config: MCP HTTP server-push → event bus toggle."""

from fastapi.testclient import TestClient
import pytest

from api import system as system_api
from core.system import runtime_settings as rs

from tests.helpers import make_fastapi_app_router_only


class _StoreNone:
    def get_setting(self, key: str):
        return None


class _StoreFalse:
    def get_setting(self, key: str):
        if key == "mcpHttpEmitServerPushEvents":
            return False
        return None


class _StoreTrue:
    def get_setting(self, key: str):
        if key == "mcpHttpEmitServerPushEvents":
            return True
        return None


def _build_client() -> TestClient:
    app = make_fastapi_app_router_only(system_api)

    @app.middleware("http")
    async def _inject_test_user(request, call_next):  # type: ignore[no-untyped-def]
        request.state.user_id = request.headers.get("X-User-Id")
        return await call_next(request)

    app.dependency_overrides[system_api.require_authenticated_platform_admin] = lambda: None
    app.dependency_overrides[system_api.require_platform_admin] = lambda: None
    return TestClient(app)


@pytest.mark.no_fallback
def test_get_mcp_http_emit_falls_back_to_env_settings(monkeypatch):
    monkeypatch.setattr(rs, "get_system_settings_store", lambda: _StoreNone())
    monkeypatch.setattr(rs.settings, "mcp_http_emit_server_push_events", False)
    assert rs.get_mcp_http_emit_server_push_events() is False

    monkeypatch.setattr(rs.settings, "mcp_http_emit_server_push_events", True)
    assert rs.get_mcp_http_emit_server_push_events() is True


@pytest.mark.no_fallback
def test_get_mcp_http_emit_store_overrides_env(monkeypatch):
    monkeypatch.setattr(rs.settings, "mcp_http_emit_server_push_events", True)
    monkeypatch.setattr(rs, "get_system_settings_store", lambda: _StoreFalse())
    assert rs.get_mcp_http_emit_server_push_events() is False

    monkeypatch.setattr(rs.settings, "mcp_http_emit_server_push_events", False)
    monkeypatch.setattr(rs, "get_system_settings_store", lambda: _StoreTrue())
    assert rs.get_mcp_http_emit_server_push_events() is True


@pytest.mark.no_fallback
def test_get_mcp_http_emit_truthy_non_bool(monkeypatch):
    """DB JSON may deserialize to truthy scalars; bool() applies."""

    class _StoreOne:
        def get_setting(self, key: str):
            return 1 if key == "mcpHttpEmitServerPushEvents" else None

    monkeypatch.setattr(rs, "get_system_settings_store", lambda: _StoreOne())
    monkeypatch.setattr(rs.settings, "mcp_http_emit_server_push_events", False)
    assert rs.get_mcp_http_emit_server_push_events() is True


@pytest.mark.no_fallback
def test_get_config_includes_mcp_emit_effective(monkeypatch):
    client = _build_client()

    class _FakeStore:
        def get_all_settings(self):
            return {}

    monkeypatch.setattr(system_api, "get_system_settings_store", lambda: _FakeStore())
    monkeypatch.setattr(system_api, "get_mcp_http_emit_server_push_events", lambda: False)
    r = client.get("/api/system/config")
    assert r.status_code == 200
    body = r.json()
    assert body.get("mcp_http_emit_server_push_events_effective") is False
    assert isinstance(body.get("api_rate_limit_enabled_effective"), bool)
    assert isinstance(body.get("api_rate_limit_requests_effective"), int)
    assert isinstance(body.get("api_rate_limit_window_seconds_effective"), int)
    assert isinstance(body.get("api_rate_limit_events_requests_effective"), int)
    assert isinstance(body.get("api_rate_limit_events_path_prefix_effective"), str)


@pytest.mark.no_fallback
def test_update_config_accepts_mcp_http_emit_server_push_events(monkeypatch):
    client = _build_client()
    captured: dict[str, object] = {}

    class _FakeStore:
        def set_setting(self, key, value):
            captured[key] = value

    monkeypatch.setattr(system_api, "get_system_settings_store", lambda: _FakeStore())
    off = client.post("/api/system/config", json={"mcpHttpEmitServerPushEvents": False})
    assert off.status_code == 200
    assert captured.get("mcpHttpEmitServerPushEvents") is False
    on = client.post("/api/system/config", json={"mcpHttpEmitServerPushEvents": True})
    assert on.status_code == 200
    assert captured.get("mcpHttpEmitServerPushEvents") is True
