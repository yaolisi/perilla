from fastapi.testclient import TestClient

from config.settings import settings
from middleware.api_key_scope import ApiKeyScopeMiddleware
from tests.helpers import make_fastapi_app_router_only


def _make_app():
    app = make_fastapi_app_router_only()
    app.add_middleware(ApiKeyScopeMiddleware)

    @app.get("/api/agents/{agent_id}")
    def get_agent(agent_id: str):
        return {"agent_id": agent_id}

    @app.post("/api/agents/{agent_id}/run")
    def run_agent(agent_id: str):
        return {"agent_id": agent_id, "ok": True}

    @app.get("/api/knowledge-bases/{kb_id}")
    def get_kb(kb_id: str):
        return {"kb_id": kb_id}

    return app


def test_api_key_scope_denies_missing_scope():
    prev_scopes = settings.api_key_scopes_json
    prev_keys = settings.api_keys_json
    prev_revoked = settings.api_key_revoked_list
    try:
        settings.api_key_scopes_json = '{"k-read":["agent:read"]}'
        settings.api_keys_json = "{}"
        settings.api_key_revoked_list = ""
        app = _make_app()
        client = TestClient(app)

        denied = client.post(
            "/api/agents/a-1/run",
            headers={"X-Api-Key": "k-read"},
        )
        assert denied.status_code == 403
        assert denied.json().get("required_scope") == "agent:write"
    finally:
        settings.api_key_scopes_json = prev_scopes
        settings.api_keys_json = prev_keys
        settings.api_key_revoked_list = prev_revoked


def test_api_key_expired_denied():
    prev_scopes = settings.api_key_scopes_json
    prev_keys = settings.api_keys_json
    prev_revoked = settings.api_key_revoked_list
    try:
        settings.api_key_scopes_json = "{}"
        settings.api_keys_json = (
            '{"k-expired":{"scopes":["agent:read"],"expires_at":"2000-01-01T00:00:00Z"}}'
        )
        settings.api_key_revoked_list = ""
        app = _make_app()
        client = TestClient(app)

        denied = client.get(
            "/api/agents/a-1",
            headers={"X-Api-Key": "k-expired"},
        )
        assert denied.status_code == 401
        assert denied.json().get("detail") == "api key expired"
    finally:
        settings.api_key_scopes_json = prev_scopes
        settings.api_keys_json = prev_keys
        settings.api_key_revoked_list = prev_revoked


def test_api_key_resource_level_agent_allow_and_deny():
    prev_scopes = settings.api_key_scopes_json
    prev_keys = settings.api_keys_json
    prev_revoked = settings.api_key_revoked_list
    try:
        settings.api_key_scopes_json = "{}"
        settings.api_keys_json = (
            '{"k-agent":{"scopes":["agent:read"],"resources":{"agent_ids":["agent-a"]}}}'
        )
        settings.api_key_revoked_list = ""
        app = _make_app()
        client = TestClient(app)

        ok = client.get(
            "/api/agents/agent-a",
            headers={"X-Api-Key": "k-agent"},
        )
        assert ok.status_code == 200

        denied = client.get(
            "/api/agents/agent-b",
            headers={"X-Api-Key": "k-agent"},
        )
        assert denied.status_code == 403
        assert denied.json().get("detail") == "resource access denied"
    finally:
        settings.api_key_scopes_json = prev_scopes
        settings.api_keys_json = prev_keys
        settings.api_key_revoked_list = prev_revoked


def test_api_key_revoked_list_blocks_access():
    prev_scopes = settings.api_key_scopes_json
    prev_keys = settings.api_keys_json
    prev_revoked = settings.api_key_revoked_list
    try:
        settings.api_key_scopes_json = '{"k-revoked":["agent:read"]}'
        settings.api_keys_json = "{}"
        settings.api_key_revoked_list = "k-revoked"
        app = _make_app()
        client = TestClient(app)

        denied = client.get(
            "/api/agents/a-1",
            headers={"X-Api-Key": "k-revoked"},
        )
        assert denied.status_code == 403
        assert denied.json().get("detail") == "api key revoked"
    finally:
        settings.api_key_scopes_json = prev_scopes
        settings.api_keys_json = prev_keys
        settings.api_key_revoked_list = prev_revoked
