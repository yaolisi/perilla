"""MCP Server ORM CRUD。"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, cast

from core.data.base import db_session
from core.data.models.mcp_server import McpServer as McpServerORM
from core.mcp.tools_cache import invalidate_tools_cache


def _row_to_dict(row: Any) -> Dict[str, Any]:
    env: Dict[str, str] = {}
    if getattr(row, "env_json", None):
        try:
            raw = json.loads(row.env_json)
            if isinstance(raw, dict):
                env = {str(k): str(v) for k, v in raw.items()}
        except json.JSONDecodeError:
            env = {}
    cmd: List[str]
    try:
        cmd = json.loads(row.command_json)
        if not isinstance(cmd, list):
            cmd = []
        cmd = [str(x) for x in cmd]
    except json.JSONDecodeError:
        cmd = []
    tr = getattr(row, "transport", None)
    transport = (str(tr).strip().lower() if tr else "") or "stdio"
    if transport not in ("stdio", "http"):
        transport = "stdio"
    bu = getattr(row, "base_url", None)
    base_url = (bu or "").strip() if bu else ""
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description or "",
        "transport": transport,
        "base_url": base_url,
        "command": cmd,
        "env": env,
        "cwd": (row.cwd or "").strip(),
        "enabled": bool(row.enabled),
    }


def create_mcp_server(
    *,
    name: str,
    command: List[str],
    description: str = "",
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    enabled: bool = True,
    server_id: Optional[str] = None,
    transport: str = "stdio",
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    tr = (transport or "stdio").strip().lower()
    if tr not in ("stdio", "http"):
        raise ValueError("transport must be stdio or http")
    bu = (base_url or "").strip() or None
    if tr == "stdio":
        if not command:
            raise ValueError("command must be non-empty")
        cmd_store = command
        bu_store = None
    else:
        if not bu:
            raise ValueError("base_url required for http transport")
        cmd_store = []
        bu_store = bu
    sid = server_id or f"mcp_srv_{uuid.uuid4().hex[:12]}"
    env = env or {}
    with db_session() as db:
        row = McpServerORM(
            id=sid,
            name=name.strip(),
            description=description.strip(),
            transport=tr,
            base_url=bu_store,
            command_json=json.dumps(cmd_store, ensure_ascii=False),
            env_json=json.dumps(env, ensure_ascii=False) if env else None,
            cwd=cwd.strip() if cwd else None,
            enabled=1 if enabled else 0,
        )
        db.add(row)
    out = get_mcp_server(sid)
    assert out is not None
    return out


def list_mcp_servers(*, enabled_only: bool = False) -> List[Dict[str, Any]]:
    with db_session() as db:
        q = db.query(McpServerORM)
        if enabled_only:
            q = q.filter(McpServerORM.enabled == 1)
        rows = q.order_by(McpServerORM.updated_at.desc()).all()
        return [_row_to_dict(r) for r in rows]


def get_mcp_server(server_id: str) -> Optional[Dict[str, Any]]:
    with db_session() as db:
        row = db.query(McpServerORM).filter(McpServerORM.id == server_id).first()
        if row:
            return _row_to_dict(row)
    return None


def update_mcp_server(
    server_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    transport: Optional[str] = None,
    base_url: Optional[str] = None,
    command: Optional[List[str]] = None,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    enabled: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    with db_session() as db:
        row = db.query(McpServerORM).filter(McpServerORM.id == server_id).first()
        if not row:
            return None
        orm = cast(Any, row)
        if name is not None:
            orm.name = name.strip()
        if description is not None:
            orm.description = description.strip()
        if transport is not None:
            tr = transport.strip().lower()
            if tr not in ("stdio", "http"):
                raise ValueError("transport must be stdio or http")
            orm.transport = tr
            invalidate_tools_cache(server_id)
        if base_url is not None:
            orm.base_url = base_url.strip() or None
            invalidate_tools_cache(server_id)
        if command is not None:
            cur_tr = str(getattr(orm, "transport", "stdio") or "stdio").strip().lower()
            if cur_tr == "stdio":
                if not command:
                    raise ValueError("command must be non-empty")
                orm.command_json = json.dumps(command, ensure_ascii=False)
            else:
                orm.command_json = json.dumps([], ensure_ascii=False)
            invalidate_tools_cache(server_id)
        if cwd is not None:
            orm.cwd = cwd.strip() or None
            invalidate_tools_cache(server_id)
        if env is not None:
            orm.env_json = json.dumps(env, ensure_ascii=False) if env else None
            invalidate_tools_cache(server_id)
        if enabled is not None:
            orm.enabled = 1 if enabled else 0
        try:
            cmd_list = json.loads(orm.command_json) if orm.command_json else []
        except json.JSONDecodeError:
            cmd_list = []
        if not isinstance(cmd_list, list):
            cmd_list = []
        tr_final = str(getattr(orm, "transport", "stdio") or "stdio").strip().lower()
        bu_final = (getattr(orm, "base_url", None) or "").strip()
        if tr_final == "http":
            if not bu_final:
                raise ValueError("http transport requires base_url")
        elif not cmd_list:
            raise ValueError("stdio requires non-empty command")
    return get_mcp_server(server_id)


def delete_mcp_server(server_id: str) -> bool:
    with db_session() as db:
        row = db.query(McpServerORM).filter(McpServerORM.id == server_id).first()
        if row:
            db.delete(row)
            invalidate_tools_cache(server_id)
            return True
    return False
