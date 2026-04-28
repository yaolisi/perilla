"""MCP HTTP 客户端：请求头与 close 时 DELETE（无网络）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.mcp.http_client import MCPHttpClient, _endpoint_label, _summarize_rpc_for_event_bus
from core.mcp.protocol import DEFAULT_PROTOCOL_VERSION


def test_merge_headers_includes_protocol_version() -> None:
    c = MCPHttpClient("http://127.0.0.1:9/mcp")
    h = c._merge_headers()
    assert h["MCP-Protocol-Version"] == DEFAULT_PROTOCOL_VERSION
    assert "application/json" in h["Accept"]


def test_merge_headers_session_and_extra() -> None:
    c = MCPHttpClient(
        "http://127.0.0.1:9/mcp",
        headers={"Authorization": "Bearer t"},
    )
    c._session_id = "sid-1"
    c._mcp_protocol_version_header = "2025-03-26"
    h = c._merge_headers()
    assert h["Mcp-Session-Id"] == "sid-1"
    assert h["MCP-Protocol-Version"] == "2025-03-26"
    assert h["Authorization"] == "Bearer t"


@pytest.mark.asyncio
async def test_close_delete_best_effort_with_session() -> None:
    c = MCPHttpClient("http://127.0.0.1:9/mcp")
    c._session_id = "sess"
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    delete_mock = AsyncMock(return_value=mock_resp)
    c._client = MagicMock()
    c._client.delete = delete_mock
    c._client.aclose = AsyncMock()
    await c.close()
    delete_mock.assert_awaited_once()
    args, kwargs = delete_mock.call_args
    assert args[0] == "http://127.0.0.1:9/mcp"
    assert kwargs["headers"]["Mcp-Session-Id"] == "sess"
    assert kwargs["headers"]["MCP-Protocol-Version"] == DEFAULT_PROTOCOL_VERSION
    c._client.aclose.assert_awaited_once()


def test_endpoint_label_truncates_path() -> None:
    assert "example.com" in _endpoint_label("https://example.com/mcp/foo")


def test_summarize_rpc_params_keys_only() -> None:
    s = _summarize_rpc_for_event_bus({"method": "x", "params": {"a": 1, "b": 2}})
    assert set(s.get("params_keys") or []) == {"a", "b"}


@pytest.mark.asyncio
async def test_emit_server_push_publishes_event_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict, str]] = []

    async def publish(event_type: str, payload: dict, source: str = "system") -> None:
        calls.append((event_type, payload, source))

    fake = MagicMock()
    fake.publish = AsyncMock(side_effect=publish)
    monkeypatch.setattr("core.events.get_event_bus", lambda: fake)

    c = MCPHttpClient("https://example.com/mcp", emit_server_push_events=True)
    await c._emit_server_push_to_event_bus({"method": "notifications/progress", "params": {"x": 1}})
    assert len(calls) == 1
    et, payload, src = calls[0]
    assert et == "mcp.streamable.server_rpc"
    assert src == "mcp_http_client"
    assert payload["method"] == "notifications/progress"
    assert payload["endpoint_label"].startswith("example.com")
    assert payload["rpc_summary"].get("params_keys") == ["x"]  # single-key dict


@pytest.mark.asyncio
async def test_emit_server_push_respects_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = MagicMock()
    fake.publish = AsyncMock()
    monkeypatch.setattr("core.events.get_event_bus", lambda: fake)
    c = MCPHttpClient("http://x", emit_server_push_events=False)
    await c._emit_server_push_to_event_bus({"method": "ping"})
    fake.publish.assert_not_called()


@pytest.mark.asyncio
async def test_close_skips_delete_without_session() -> None:
    c = MCPHttpClient("http://127.0.0.1:9/mcp")
    c._client = MagicMock()
    c._client.delete = AsyncMock()
    c._client.aclose = AsyncMock()
    await c.close()
    c._client.delete.assert_not_called()
    c._client.aclose.assert_awaited_once()
