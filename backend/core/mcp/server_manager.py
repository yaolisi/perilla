"""
MCP Server 进程生命周期辅助：健康检查与短时间探测。

不负责持久化配置（见后续 Phase：ORM 存储 server 定义）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from log import logger

from core.mcp.client import MCPStdioClient
from core.system.runtime_settings import get_mcp_http_emit_server_push_events


async def probe_http_server(
    url: str,
    *,
    env: Optional[Dict[str, str]] = None,
    request_timeout: float = 30.0,
) -> Dict[str, Any]:
    """连接 Streamable HTTP MCP endpoint：握手并 tools/list。"""
    from core.mcp.http_client import create_mcp_http_client

    client = await create_mcp_http_client(
        url.strip(),
        headers=env or {},
        request_timeout=request_timeout,
        emit_server_push_events=get_mcp_http_emit_server_push_events(),
    )
    try:
        result = await client.list_tools()
        tools = result.get("tools") if isinstance(result, dict) else []
        if not isinstance(tools, list):
            tools = []
        n = len(tools)
        logger.info("[MCP] HTTP probe ok url=%s tools=%s", url[:96], n)
        return {
            "ok": True,
            "tools": tools,
            "negotiated_protocol_version": client.negotiated_protocol_version,
        }
    finally:
        await client.close()


async def probe_stdio_server(
    command: List[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    request_timeout: float = 30.0,
) -> Dict[str, Any]:
    """
    启动 stdio MCP、握手并执行 tools/list。

    Returns:
        {"ok": True, "tools": [...], "negotiated_protocol_version": str|None}
        失败则抛异常（进程/协议/超时）。
    """
    client = MCPStdioClient(
        command,
        cwd=cwd,
        env=env,
        request_timeout=request_timeout,
    )
    try:
        await client.connect()
        result = await client.list_tools()
        tools = result.get("tools") if isinstance(result, dict) else []
        n = len(tools) if isinstance(tools, list) else 0
        logger.info("[MCP] probe ok command=%s tools=%s", command[0] if command else "", n)
        return {
            "ok": True,
            "tools": tools,
            "negotiated_protocol_version": client.negotiated_protocol_version,
        }
    finally:
        await client.close()


async def healthcheck_stdio(
    command: List[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    request_timeout: float = 20.0,
) -> bool:
    """成功列出工具（含 0 个工具）则 True；异常则记录并返回 False。"""
    try:
        await probe_stdio_server(command, cwd=cwd, env=env, request_timeout=request_timeout)
        return True
    except Exception as e:
        logger.warning("[MCP] healthcheck_stdio failed: %s", e)
        return False
