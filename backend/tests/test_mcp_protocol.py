"""MCP 协议单元测试（无子进程）。"""
import pytest

from core.mcp.protocol import (
    build_notification,
    build_request,
    decode_message_line,
    encode_message,
    raise_if_error_payload,
    MCPJsonRpcError,
)


def test_encode_decode_roundtrip() -> None:
    msg = build_request(1, "tools/list", {})
    raw = encode_message(msg)
    back = decode_message_line(raw.strip())
    assert back["method"] == "tools/list"
    assert back["id"] == 1


def test_notification_no_id() -> None:
    n = build_notification("notifications/initialized", {})
    raw = encode_message(n)
    back = decode_message_line(raw.strip())
    assert "id" not in back
    assert back["method"] == "notifications/initialized"


def test_raise_if_error_payload() -> None:
    with pytest.raises(MCPJsonRpcError):
        raise_if_error_payload({"error": {"code": -32601, "message": "not found"}})
