"""MCP 控制面路由成功路径应写入 log_structured 审计（契约测试）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api import mcp as mcp_api
from core.security.deps import require_authenticated_platform_admin
from tests.helpers import make_fastapi_app_router_only


def _audit_client() -> TestClient:
    app = make_fastapi_app_router_only(mcp_api)

    @app.middleware("http")
    async def _inject_audit_context(request, call_next):  # type: ignore[no-untyped-def]
        request.state.tenant_id = "tenant_audit_x"
        request.state.trace_id = "trace_audit_1"
        request.state.request_id = "req_audit_1"
        request.state.user_id = "user_audit_1"
        return await call_next(request)

    app.dependency_overrides[require_authenticated_platform_admin] = lambda: None
    return TestClient(app)


def test_mcp_servers_list_emits_structured_audit() -> None:
    with patch("api.mcp.list_mcp_servers", return_value=[]), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.get("/api/mcp/servers", params={"enabled_only": "true"})
    assert resp.status_code == 200
    mock_log.assert_called_once()
    args, kwargs = mock_log.call_args
    assert args[0] == "McpApi"
    assert args[1] == "mcp_api_servers_list"
    assert kwargs["enabled_only"] is True
    assert kwargs["result_count"] == 0
    assert kwargs["tenant_id"] == "tenant_audit_x"
    assert kwargs["trace_id"] == "trace_audit_1"
    assert kwargs["request_id"] == "req_audit_1"
    assert kwargs["user_id"] == "user_audit_1"


def test_mcp_server_get_emits_structured_audit() -> None:
    row = {
        "id": "srv_audit_1",
        "name": "Test",
        "description": "",
        "transport": "stdio",
        "base_url": "",
        "command": ["true"],
        "env": {},
        "cwd": "",
        "enabled": True,
    }
    with patch("api.mcp.get_mcp_server", return_value=row), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.get("/api/mcp/servers/srv_audit_1")
    assert resp.status_code == 200
    mock_log.assert_called_once()
    args, kwargs = mock_log.call_args
    assert args[0] == "McpApi"
    assert args[1] == "mcp_api_server_get"
    assert kwargs["server_id"] == "srv_audit_1"
    assert kwargs["transport"] == "stdio"
    assert kwargs["tenant_id"] == "tenant_audit_x"


def test_mcp_probe_stdio_emits_structured_audit() -> None:
    raw_probe = {"tools": [{"name": "probe_tool", "inputSchema": {"type": "object"}}]}
    with patch("api.mcp.probe_command", new_callable=AsyncMock, return_value=raw_probe), patch(
        "api.mcp.log_structured"
    ) as mock_log:
        client = _audit_client()
        resp = client.post(
            "/api/mcp/probe",
            json={"command": ["echo", "mcp"], "request_timeout": 30.0},
        )
    assert resp.status_code == 200
    mock_log.assert_called_once()
    args, kwargs = mock_log.call_args
    assert args[0] == "McpApi"
    assert args[1] == "mcp_api_probe_ok"
    assert kwargs["transport"] == "stdio"
    assert kwargs["tools_count"] == 1
    assert kwargs["tenant_id"] == "tenant_audit_x"


def test_mcp_probe_http_emits_structured_audit() -> None:
    raw_probe = {"tools": [{"name": "http_tool", "inputSchema": {"type": "object"}}]}
    with patch("api.mcp.probe_http_url", new_callable=AsyncMock, return_value=raw_probe), patch(
        "api.mcp.log_structured"
    ) as mock_log:
        client = _audit_client()
        resp = client.post(
            "/api/mcp/probe",
            json={"url": "http://127.0.0.1:9/mcp", "request_timeout": 30.0},
        )
    assert resp.status_code == 200
    mock_log.assert_called_once()
    args, kwargs = mock_log.call_args
    assert args[1] == "mcp_api_probe_ok"
    assert kwargs["transport"] == "http"
    assert kwargs["tools_count"] == 1
    assert kwargs["tenant_id"] == "tenant_audit_x"


def test_mcp_server_create_emits_structured_audit() -> None:
    created = {
        "id": "srv_new",
        "name": "New",
        "description": "",
        "transport": "stdio",
        "base_url": "",
        "command": ["true"],
        "env": {},
        "cwd": "",
        "enabled": True,
    }
    with patch("api.mcp.create_mcp_server", return_value=created), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.post(
            "/api/mcp/servers",
            json={
                "name": "New",
                "transport": "stdio",
                "command": ["true"],
                "enabled": True,
            },
        )
    assert resp.status_code == 200
    mock_log.assert_called_once()
    args, kwargs = mock_log.call_args
    assert args[1] == "mcp_api_server_create"
    assert kwargs["server_id"] == "srv_new"
    assert kwargs["name"] == "New"
    assert kwargs["transport"] == "stdio"
    assert kwargs["enabled"] is True


def test_mcp_server_update_emits_structured_audit() -> None:
    updated = {
        "id": "srv_u",
        "name": "Renamed",
        "description": "",
        "transport": "stdio",
        "base_url": "",
        "command": ["true"],
        "env": {},
        "cwd": "",
        "enabled": False,
    }
    with patch("api.mcp.update_mcp_server", return_value=updated), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.put("/api/mcp/servers/srv_u", json={"name": "Renamed", "enabled": False})
    assert resp.status_code == 200
    mock_log.assert_called_once()
    args, kwargs = mock_log.call_args
    assert args[1] == "mcp_api_server_update"
    assert kwargs["server_id"] == "srv_u"
    assert kwargs["enabled"] is False


def test_mcp_server_delete_emits_structured_audit() -> None:
    with patch("api.mcp.delete_mcp_server", return_value=True), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.delete("/api/mcp/servers/srv_del")
    assert resp.status_code == 200
    mock_log.assert_called_once()
    args, kwargs = mock_log.call_args
    assert args[1] == "mcp_api_server_delete"
    assert kwargs["server_id"] == "srv_del"


def test_mcp_server_tools_emits_structured_audit() -> None:
    row = {
        "id": "srv_t",
        "name": "T",
        "description": "",
        "transport": "stdio",
        "base_url": "",
        "command": ["true"],
        "env": {},
        "cwd": "",
        "enabled": True,
    }
    tools_raw = [{"name": "alpha", "inputSchema": {"type": "object"}}]
    with patch("api.mcp.get_mcp_server", return_value=row), patch(
        "api.mcp.fetch_tools_for_server_config", new_callable=AsyncMock, return_value=tools_raw
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.get("/api/mcp/servers/srv_t/tools")
    assert resp.status_code == 200
    mock_log.assert_called_once()
    args, kwargs = mock_log.call_args
    assert args[1] == "mcp_api_server_tools_list"
    assert kwargs["server_id"] == "srv_t"
    assert kwargs["tools_count"] == 1


def test_mcp_skill_previews_emits_structured_audit() -> None:
    preview = {
        "id": "mcp.srv.prev.tool_a",
        "name": "tool_a",
        "version": "1.0.0",
        "description": "",
        "type": "tool",
        "definition": {"kind": "mcp_stdio", "server_config_id": "srv_p", "tool_name": "tool_a"},
        "category": ["mcp"],
        "tags": [],
        "visibility": "public",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "enabled": True,
        "composable": True,
        "is_mcp": True,
    }
    with patch(
        "api.mcp.skill_previews_for_server", new_callable=AsyncMock, return_value=[preview]
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.get("/api/mcp/servers/srv_p/skill-previews")
    assert resp.status_code == 200
    mock_log.assert_called_once()
    args, kwargs = mock_log.call_args
    assert args[1] == "mcp_api_server_skill_previews"
    assert kwargs["server_id"] == "srv_p"
    assert kwargs["previews_count"] == 1


def test_mcp_import_tools_emits_structured_audit() -> None:
    raw_imp = {
        "imported": ["skill.imported.a"],
        "skipped_existing": ["skill.skip.b"],
        "errors": [{"tool": "bad", "error": "x"}],
    }
    with patch(
        "api.mcp.import_mcp_tools_as_skills", new_callable=AsyncMock, return_value=raw_imp
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.post("/api/mcp/servers/srv_imp/import-tools", json={"tool_names": ["a"]})
    assert resp.status_code == 200
    mock_log.assert_called_once()
    args, kwargs = mock_log.call_args
    assert args[1] == "mcp_api_server_import_tools"
    assert kwargs["server_id"] == "srv_imp"
    assert kwargs["imported_count"] == 1
    assert kwargs["skipped_count"] == 1
    assert kwargs["errors_count"] == 1
    assert kwargs["filter_tool_names"] is True


def test_mcp_get_server_404_emits_not_found_audit() -> None:
    with patch("api.mcp.get_mcp_server", return_value=None), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.get("/api/mcp/servers/nonexistent_srv")
    assert resp.status_code == 404
    mock_log.assert_called_once()
    args, kwargs = mock_log.call_args
    assert args[1] == "mcp_api_server_not_found"
    assert kwargs["operation"] == "get"
    assert kwargs["server_id"] == "nonexistent_srv"


def test_mcp_delete_server_404_emits_not_found_audit() -> None:
    with patch("api.mcp.delete_mcp_server", return_value=False), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.delete("/api/mcp/servers/gone_srv")
    assert resp.status_code == 404
    mock_log.assert_called_once()
    assert mock_log.call_args[1]["operation"] == "delete"
    assert mock_log.call_args[1]["server_id"] == "gone_srv"


def test_mcp_server_tools_502_emits_tools_failed_audit() -> None:
    row = {
        "id": "srv_up",
        "name": "U",
        "description": "",
        "transport": "stdio",
        "base_url": "",
        "command": ["true"],
        "env": {},
        "cwd": "",
        "enabled": True,
    }
    with patch("api.mcp.get_mcp_server", return_value=row), patch(
        "api.mcp.fetch_tools_for_server_config",
        new_callable=AsyncMock,
        side_effect=RuntimeError("upstream tools/list failed"),
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.get("/api/mcp/servers/srv_up/tools")
    assert resp.status_code == 502
    mock_log.assert_called_once()
    assert mock_log.call_args[0][1] == "mcp_api_server_tools_failed"
    assert mock_log.call_args[1]["api_code"] == "mcp_tools_list_failed"
    assert mock_log.call_args[1]["level"] == "error"


def test_mcp_update_server_404_emits_not_found_audit() -> None:
    with patch("api.mcp.update_mcp_server", return_value=None), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.put("/api/mcp/servers/missing_u", json={"name": "x"})
    assert resp.status_code == 404
    mock_log.assert_called_once()
    assert mock_log.call_args[1]["operation"] == "update"
    assert mock_log.call_args[1]["server_id"] == "missing_u"


def test_mcp_create_server_validation_error_emits_audit() -> None:
    with patch(
        "api.mcp.create_mcp_server",
        side_effect=ValueError("simulated invalid server config"),
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.post(
            "/api/mcp/servers",
            json={"name": "N", "transport": "stdio", "command": ["true"], "enabled": True},
        )
    assert resp.status_code == 400
    mock_log.assert_called_once()
    assert mock_log.call_args[0][1] == "mcp_api_validation_error"
    kwargs = mock_log.call_args[1]
    assert kwargs["context"] == "create_server"
    assert kwargs["api_code"] == "mcp_invalid_server"
    assert "simulated invalid" in (kwargs.get("error_message") or "")


def test_mcp_update_server_validation_error_emits_audit() -> None:
    with patch(
        "api.mcp.update_mcp_server",
        side_effect=ValueError("simulated update validation"),
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.put("/api/mcp/servers/srv_val", json={"name": "Renamed"})
    assert resp.status_code == 400
    mock_log.assert_called_once()
    assert mock_log.call_args[0][1] == "mcp_api_validation_error"
    kwargs = mock_log.call_args[1]
    assert kwargs["context"] == "update_server"
    assert kwargs["api_code"] == "mcp_invalid_server"
    assert kwargs["server_id"] == "srv_val"


def test_mcp_tools_list_404_emits_not_found_audit() -> None:
    with patch("api.mcp.get_mcp_server", return_value=None), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.get("/api/mcp/servers/gone/tools")
    assert resp.status_code == 404
    mock_log.assert_called_once()
    assert mock_log.call_args[1]["operation"] == "tools_list"
    assert mock_log.call_args[1]["server_id"] == "gone"


def test_mcp_tools_list_400_emits_bad_request_audit() -> None:
    row = {
        "id": "srv_br",
        "name": "B",
        "description": "",
        "transport": "stdio",
        "base_url": "",
        "command": ["true"],
        "env": {},
        "cwd": "",
        "enabled": True,
    }
    with patch("api.mcp.get_mcp_server", return_value=row), patch(
        "api.mcp.fetch_tools_for_server_config",
        new_callable=AsyncMock,
        side_effect=ValueError("bad MCP tools payload"),
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.get("/api/mcp/servers/srv_br/tools")
    assert resp.status_code == 400
    mock_log.assert_called_once()
    kwargs = mock_log.call_args[1]
    assert mock_log.call_args[0][1] == "mcp_api_server_tools_failed"
    assert kwargs["api_code"] == "mcp_bad_request"
    assert kwargs.get("level", "warning") == "warning"


def test_mcp_skill_previews_disabled_emits_audit() -> None:
    with patch(
        "api.mcp.skill_previews_for_server",
        new_callable=AsyncMock,
        side_effect=ValueError("MCP server disabled"),
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.get("/api/mcp/servers/srv_dis/skill-previews")
    assert resp.status_code == 400
    mock_log.assert_called_once()
    kwargs = mock_log.call_args[1]
    assert mock_log.call_args[0][1] == "mcp_api_skill_previews_failed"
    assert kwargs["api_code"] == "mcp_server_disabled"


def test_mcp_skill_previews_keyerror_emits_not_found_audit() -> None:
    with patch(
        "api.mcp.skill_previews_for_server",
        new_callable=AsyncMock,
        side_effect=KeyError("missing"),
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.get("/api/mcp/servers/srv_k/skill-previews")
    assert resp.status_code == 404
    mock_log.assert_called_once()
    assert mock_log.call_args[1]["operation"] == "skill_previews"


def test_mcp_skill_previews_502_emits_audit() -> None:
    with patch(
        "api.mcp.skill_previews_for_server",
        new_callable=AsyncMock,
        side_effect=RuntimeError("upstream preview"),
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.get("/api/mcp/servers/srv_502/skill-previews")
    assert resp.status_code == 502
    kwargs = mock_log.call_args[1]
    assert mock_log.call_args[0][1] == "mcp_api_skill_previews_failed"
    assert kwargs["api_code"] == "mcp_skill_preview_failed"
    assert kwargs["level"] == "error"


def test_mcp_import_tools_keyerror_emits_not_found_audit() -> None:
    with patch(
        "api.mcp.import_mcp_tools_as_skills",
        new_callable=AsyncMock,
        side_effect=KeyError("server not found"),
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.post("/api/mcp/servers/srv_miss/import-tools", json={})
    assert resp.status_code == 404
    mock_log.assert_called_once()
    assert mock_log.call_args[1]["operation"] == "import_tools"


def test_mcp_import_tools_valueerror_emits_audit() -> None:
    with patch(
        "api.mcp.import_mcp_tools_as_skills",
        new_callable=AsyncMock,
        side_effect=ValueError("invalid import"),
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.post("/api/mcp/servers/srv_iv/import-tools", json={})
    assert resp.status_code == 400
    kwargs = mock_log.call_args[1]
    assert mock_log.call_args[0][1] == "mcp_api_import_tools_failed"
    assert kwargs["api_code"] == "mcp_import_invalid"


def test_mcp_import_tools_502_emits_audit() -> None:
    with patch(
        "api.mcp.import_mcp_tools_as_skills",
        new_callable=AsyncMock,
        side_effect=RuntimeError("store failed"),
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.post("/api/mcp/servers/srv_imp502/import-tools", json={})
    assert resp.status_code == 502
    kwargs = mock_log.call_args[1]
    assert mock_log.call_args[0][1] == "mcp_api_import_tools_failed"
    assert kwargs["api_code"] == "mcp_import_failed"
    assert kwargs["level"] == "error"


def test_mcp_probe_failure_emits_probe_failed_audit() -> None:
    with patch(
        "api.mcp.probe_command",
        new_callable=AsyncMock,
        side_effect=RuntimeError("probe simulated failure"),
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.post(
            "/api/mcp/probe",
            json={"command": ["false"], "request_timeout": 30.0},
        )
    assert resp.status_code == 502
    mock_log.assert_called_once()
    assert mock_log.call_args[0][1] == "mcp_api_probe_failed"
    assert mock_log.call_args[1]["transport"] == "stdio"
    assert mock_log.call_args[1]["error_type"] == "RuntimeError"


def test_mcp_probe_http_failure_emits_probe_failed_audit() -> None:
    with patch(
        "api.mcp.probe_http_url",
        new_callable=AsyncMock,
        side_effect=OSError("http probe simulated failure"),
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.post(
            "/api/mcp/probe",
            json={"url": "http://127.0.0.1:9/mcp", "request_timeout": 30.0},
        )
    assert resp.status_code == 502
    mock_log.assert_called_once()
    assert mock_log.call_args[0][1] == "mcp_api_probe_failed"
    assert mock_log.call_args[1]["transport"] == "http"
    assert mock_log.call_args[1]["error_type"] == "OSError"


def test_mcp_import_tools_emits_audit_import_all_no_name_filter() -> None:
    raw_imp = {"imported": [], "skipped_existing": [], "errors": []}
    with patch(
        "api.mcp.import_mcp_tools_as_skills", new_callable=AsyncMock, return_value=raw_imp
    ), patch("api.mcp.log_structured") as mock_log:
        client = _audit_client()
        resp = client.post("/api/mcp/servers/srv_imp2/import-tools", json={})
    assert resp.status_code == 200
    mock_log.assert_called_once()
    assert mock_log.call_args[1]["filter_tool_names"] is False
