"""MCP Server ORM CRUD。"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, cast

from core.data.base import db_session
from core.data.models.mcp_server import McpServer as McpServerORM
from core.mcp.tools_cache import invalidate_tools_cache


def _eff_tid(tenant_id: Optional[str]) -> str:
    if tenant_id is None:
        return "default"
    return (str(tenant_id).strip() or "default")


def normalize_mcp_tenant_id(tenant_id: Optional[str]) -> str:
    """MCP ORM 使用的租户键（与 list/create 等一致；缺省/空 -> default）。"""
    return _eff_tid(tenant_id)


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
    row_tid = str(getattr(row, "tenant_id", None) or "").strip() or "default"
    return {
        "id": row.id,
        "tenant_id": row_tid,
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
    tenant_id: Optional[str] = None,
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
    tid = _eff_tid(tenant_id)
    with db_session() as db:
        row = McpServerORM(
            id=sid,
            tenant_id=tid,
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
    out = get_mcp_server(sid, tenant_id=tid)
    assert out is not None
    return out


def list_mcp_servers(*, enabled_only: bool = False, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    tid = _eff_tid(tenant_id)
    with db_session() as db:
        q = db.query(McpServerORM).filter(McpServerORM.tenant_id == tid)
        if enabled_only:
            q = q.filter(McpServerORM.enabled == 1)
        rows = q.order_by(McpServerORM.updated_at.desc()).all()
        return [_row_to_dict(r) for r in rows]


def get_mcp_server(server_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """按 server id + 租户查询；tenant_id 缺省按 default 命名空间（不再允许跨租户按 id 命中首行）。"""
    tid = _eff_tid(tenant_id)
    with db_session() as db:
        row = (
            db.query(McpServerORM)
            .filter(McpServerORM.id == server_id)
            .filter(McpServerORM.tenant_id == tid)
            .first()
        )
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
    tenant_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    tid = _eff_tid(tenant_id)
    with db_session() as db:
        row = (
            db.query(McpServerORM)
            .filter(McpServerORM.id == server_id)
            .filter(McpServerORM.tenant_id == tid)
            .first()
        )
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
            invalidate_tools_cache(server_id, tenant_id=tid)
        if base_url is not None:
            orm.base_url = base_url.strip() or None
            invalidate_tools_cache(server_id, tenant_id=tid)
        if command is not None:
            cur_tr = str(getattr(orm, "transport", "stdio") or "stdio").strip().lower()
            if cur_tr == "stdio":
                if not command:
                    raise ValueError("command must be non-empty")
                orm.command_json = json.dumps(command, ensure_ascii=False)
            else:
                orm.command_json = json.dumps([], ensure_ascii=False)
            invalidate_tools_cache(server_id, tenant_id=tid)
        if cwd is not None:
            orm.cwd = cwd.strip() or None
            invalidate_tools_cache(server_id, tenant_id=tid)
        if env is not None:
            orm.env_json = json.dumps(env, ensure_ascii=False) if env else None
            invalidate_tools_cache(server_id, tenant_id=tid)
        if enabled is not None:
            orm.enabled = 1 if enabled else 0
            invalidate_tools_cache(server_id, tenant_id=tid)
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
    return get_mcp_server(server_id, tenant_id=tid)


def delete_mcp_server(server_id: str, tenant_id: Optional[str] = None) -> bool:
    tid = _eff_tid(tenant_id)
    with db_session() as db:
        row = (
            db.query(McpServerORM)
            .filter(McpServerORM.id == server_id)
            .filter(McpServerORM.tenant_id == tid)
            .first()
        )
        if row:
            db.delete(row)
            invalidate_tools_cache(server_id, tenant_id=tid)
            return True
    return False
