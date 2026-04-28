"""
MCP：stdio 客户端、适配、缓存、持久化与导入 Skill。
"""
from core.mcp.adapter import mcp_tool_dict_to_skill_definition
from core.mcp.client import MCPStdioClient
from core.mcp.http_client import MCPHttpClient, MCPHttpLegacySseClient, create_mcp_http_client
from core.mcp.protocol import (
    DEFAULT_PROTOCOL_VERSION,
    MCPJsonRpcError,
    build_notification,
    build_request,
    encode_message,
)
from core.mcp.server_manager import healthcheck_stdio, probe_stdio_server

__all__ = [
    "MCPStdioClient",
    "MCPHttpClient",
    "MCPHttpLegacySseClient",
    "create_mcp_http_client",
    "MCPJsonRpcError",
    "DEFAULT_PROTOCOL_VERSION",
    "build_request",
    "build_notification",
    "encode_message",
    "probe_stdio_server",
    "healthcheck_stdio",
    "mcp_tool_dict_to_skill_definition",
]
