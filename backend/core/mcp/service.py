"""MCP 异步业务：tools 拉取、缓存、导入 Skill。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from log import logger

from core.mcp.adapter import mcp_tool_dict_to_skill_definition
from core.mcp.client import MCPStdioClient
from core.mcp.http_client import create_mcp_http_client
from core.mcp.persistence import get_mcp_server
from core.mcp.server_manager import probe_http_server, probe_stdio_server
from core.mcp.tools_cache import get_cached_tools, set_cached_tools
from core.system.runtime_settings import get_mcp_http_emit_server_push_events
from core.skills.discovery import get_discovery_engine
from core.skills.registry import SkillRegistry
from core.skills.store import get_skill_store


async def fetch_tools_for_server_config(server: Dict[str, Any]) -> List[Dict[str, Any]]:
    """使用持久化配置连接 MCP 并 tools/list（带缓存）。"""
    if not server.get("enabled", True):
        raise ValueError("server is disabled")
    sid = server["id"]
    cached = get_cached_tools(sid)
    if cached is not None:
        return cached
    transport = (server.get("transport") or "stdio").strip().lower()
    env = server.get("env") or {}
    if transport == "http":
        base_url = (server.get("base_url") or "").strip()
        if not base_url:
            raise ValueError("http server missing base_url")
        client = await create_mcp_http_client(
            base_url,
            headers=env if env else None,
            request_timeout=60.0,
            emit_server_push_events=get_mcp_http_emit_server_push_events(),
        )
        try:
            result = await client.list_tools()
            tools = result.get("tools") if isinstance(result, dict) else []
            if not isinstance(tools, list):
                tools = []
            set_cached_tools(sid, tools)
            return tools
        finally:
            await client.close()
    command = server.get("command") or []
    if not command:
        raise ValueError("server command empty")
    cwd = (server.get("cwd") or "").strip() or None
    client = MCPStdioClient(
        command,
        cwd=cwd,
        env=env if env else None,
        request_timeout=60.0,
    )
    try:
        await client.connect()
        result = await client.list_tools()
        tools = result.get("tools") if isinstance(result, dict) else []
        if not isinstance(tools, list):
            tools = []
        set_cached_tools(sid, tools)
        return tools
    finally:
        await client.close()


async def skill_previews_for_server(server_id: str) -> List[Dict[str, Any]]:
    """SkillDefinition.to_dict() 列表（不落库）。"""
    row = get_mcp_server(server_id)
    if not row:
        raise KeyError("server not found")
    if not row.get("enabled", True):
        raise ValueError("server disabled")
    tools = await fetch_tools_for_server_config(row)
    out: List[Dict[str, Any]] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        try:
            sd = mcp_tool_dict_to_skill_definition(server_id, t)
            out.append(sd.to_dict())
        except Exception as e:
            logger.warning("[MCP] skip invalid tool row: %s", e)
    return out


async def import_mcp_tools_as_skills(
    server_id: str,
    *,
    tool_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    将 tools/list 中的工具注册为平台 Skill（ORM + SkillRegistry），跳过已存在 id。

    返回 { "imported": [...], "skipped_existing": [...], "errors": [...] }
    """
    row = get_mcp_server(server_id)
    if not row:
        raise KeyError("server not found")
    tools = await fetch_tools_for_server_config(row)
    want = {str(x).strip() for x in tool_names} if tool_names else None
    store = get_skill_store()
    imported: List[str] = []
    skipped: List[str] = []
    errors: List[Dict[str, str]] = []

    for t in tools:
        if not isinstance(t, dict):
            continue
        tn = str(t.get("name") or "").strip()
        if not tn:
            continue
        if want is not None and tn not in want:
            continue
        try:
            sd = mcp_tool_dict_to_skill_definition(server_id, t)
        except Exception as e:
            errors.append({"tool": tn, "error": str(e)})
            continue
        if store.get(sd.id):
            skipped.append(sd.id)
            continue
        try:
            skill = store.create(
                name=sd.name,
                description=sd.description,
                category="mcp",
                type="tool",
                definition=sd.definition,
                input_schema=sd.input_schema,
                enabled=sd.enabled,
                skill_id=sd.id,
            )
            SkillRegistry.register(skill.to_v2())
            try:
                eng = get_discovery_engine()
                eng.refresh_skill(sd.id)
            except Exception:
                pass
            imported.append(sd.id)
        except Exception as e:
            errors.append({"tool": tn, "error": str(e)})

    return {
        "imported": imported,
        "skipped_existing": skipped,
        "errors": errors,
    }


async def probe_command(
    command: List[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    request_timeout: float = 30.0,
) -> Dict[str, Any]:
    """无持久化：探测命令是否可握手并列出工具。"""
    return await probe_stdio_server(
        command,
        cwd=cwd.strip() if cwd else None,
        env=env,
        request_timeout=request_timeout,
    )


async def probe_http_url(
    url: str,
    *,
    env: Optional[Dict[str, str]] = None,
    request_timeout: float = 30.0,
) -> Dict[str, Any]:
    """无持久化：探测 Streamable HTTP MCP endpoint。"""
    return await probe_http_server(
        url.strip(),
        env=env,
        request_timeout=request_timeout,
    )
