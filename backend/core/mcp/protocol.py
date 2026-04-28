"""
MCP JSON-RPC 帧与常量（stdio：一行一条 UTF-8 JSON，不得含未转义换行）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

# 与多数 MCP Server 兼容；握手时可由服务端协商更新
DEFAULT_PROTOCOL_VERSION = "2024-11-05"

CLIENT_NAME = "openvitamin-mcp"
CLIENT_VERSION = "1.0.0"


def encode_message(obj: Dict[str, Any]) -> bytes:
    """单行 JSON-RPC，末尾换行。"""
    line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if "\n" in line or "\r" in line:
        raise ValueError("MCP JSON-RPC payload must not contain raw newlines")
    return (line + "\n").encode("utf-8")


def decode_message_line(line: bytes) -> Dict[str, Any]:
    s = line.decode("utf-8", errors="replace").strip()
    if not s:
        return {}
    return json.loads(s)


def build_request(
    msg_id: int,
    method: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": method,
    }
    if params is not None:
        out["params"] = params
    return out


def build_notification(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        out["params"] = params
    return out


def initialize_params(
    protocol_version: str = DEFAULT_PROTOCOL_VERSION,
    capabilities: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "protocolVersion": protocol_version,
        "capabilities": capabilities or {},
        "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
    }


class MCPJsonRpcError(Exception):
    """JSON-RPC error object。"""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def raise_if_error_payload(payload: Dict[str, Any]) -> None:
    err = payload.get("error")
    if not err:
        return
    if isinstance(err, dict):
        code = int(err.get("code", -32603))
        message = str(err.get("message", "unknown error"))
        data = err.get("data")
        raise MCPJsonRpcError(code, message, data)
    raise MCPJsonRpcError(-32603, str(err))
