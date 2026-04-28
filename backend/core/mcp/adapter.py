"""
MCP Tool 元数据 → SkillDefinition（含执行锚点 definition.kind=mcp_stdio）。

执行路由（Planner / SkillExecutor 调用 MCP）可在后续 Phase 接线。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict

from core.skills.models import SkillDefinition


def sanitize_segment(name: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-zA-Z0-9_.-]", "_", (name or "").strip())
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "tool"
    return s[:max_len]


def make_mcp_skill_id(server_id: str, tool_name: str) -> str:
    """稳定、可作为 Skill ORM 主键的 id。"""
    safe_srv = sanitize_segment(server_id, 40)
    safe_tool = sanitize_segment(tool_name, 56)
    base = f"{safe_srv}_{safe_tool}"
    if len(base) <= 128:
        return base
    h = hashlib.sha256(f"{server_id}:{tool_name}".encode("utf-8")).hexdigest()[:16]
    return f"{safe_srv}_t_{h}"


_DEFAULT_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "MCP tools/call result envelope",
    "additionalProperties": True,
}


def mcp_tool_dict_to_skill_definition(
    server_id: str,
    tool: Dict[str, Any],
    *,
    version: str = "1.0.0",
) -> SkillDefinition:
    """
    将 MCP tools/list 单项转为 SkillDefinition。

    definition:
      kind: mcp_stdio
      server_config_id: 持久化 MCP Server 主键（用于运行时解析 command/cwd/env）
      tool_name: MCP 工具名
    """
    name = str(tool.get("name") or "").strip()
    if not name:
        raise ValueError("mcp tool missing name")
    title = str(tool.get("title") or "").strip()
    desc = str(tool.get("description") or "").strip()
    display_name = title or name
    skill_id = make_mcp_skill_id(server_id, name)
    raw_schema = tool.get("inputSchema") or tool.get("input_schema")
    if not isinstance(raw_schema, dict):
        raw_schema = {"type": "object", "properties": {}, "additionalProperties": True}

    return SkillDefinition(
        id=skill_id,
        name=display_name[:200],
        version=version,
        description=(desc or f"MCP tool `{name}` from server `{server_id}`")[:4000],
        input_schema=raw_schema,
        output_schema=_DEFAULT_OUTPUT_SCHEMA,
        type="tool",
        definition={
            "kind": "mcp_stdio",
            "server_config_id": server_id,
            "tool_name": name,
        },
        category=["mcp"],
        tags=["mcp", sanitize_segment(server_id, 24)],
        visibility="public",
        enabled=True,
        composable=True,
    )
