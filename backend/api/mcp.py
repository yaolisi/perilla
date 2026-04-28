"""
MCP：探测、Server 配置 CRUD、tools 列表、Skill 导入预览。
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

from api.errors import raise_api_error
from core.mcp.persistence import (
    create_mcp_server,
    delete_mcp_server,
    get_mcp_server,
    list_mcp_servers,
    update_mcp_server,
)
from core.mcp.service import (
    import_mcp_tools_as_skills,
    probe_command,
    probe_http_url,
    skill_previews_for_server,
    fetch_tools_for_server_config,
)
from core.security.deps import require_authenticated_platform_admin

router = APIRouter(
    prefix="/api/mcp",
    tags=["mcp"],
    dependencies=[Depends(require_authenticated_platform_admin)],
)


class ProbeBody(BaseModel):
    command: Optional[List[str]] = None
    url: Optional[str] = Field(default=None, max_length=4096)
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    request_timeout: float = Field(default=30.0, ge=5.0, le=120.0)

    @model_validator(mode="after")
    def _stdio_or_http(self) -> "ProbeBody":
        u = (self.url or "").strip()
        c = self.command
        has_u = bool(u)
        has_c = bool(c and len(c) > 0)
        if has_u == has_c:
            raise ValueError("provide exactly one of url (HTTP MCP) or command (stdio MCP)")
        return self


@router.post("/probe")
async def mcp_probe(body: ProbeBody) -> Any:
    """不依赖数据库：stdio 命令或 Streamable HTTP URL，握手 + tools/list。"""
    try:
        u = (body.url or "").strip()
        if u:
            return await probe_http_url(
                u,
                env=body.env,
                request_timeout=body.request_timeout,
            )
        return await probe_command(
            list(body.command or []),
            cwd=body.cwd,
            env=body.env,
            request_timeout=body.request_timeout,
        )
    except Exception as e:
        raise_api_error(
            status_code=502,
            code="mcp_probe_failed",
            message=str(e) or "MCP probe failed",
        )


class CreateMcpServerBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    transport: Literal["stdio", "http"] = "stdio"
    command: List[str] = Field(default_factory=list)
    base_url: Optional[str] = Field(default=None, max_length=4096)
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    enabled: bool = True

    @model_validator(mode="after")
    def _transport_fields(self) -> "CreateMcpServerBody":
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("stdio transport requires non-empty command")
        elif not (self.base_url or "").strip():
            raise ValueError("http transport requires base_url")
        return self


class UpdateMcpServerBody(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    transport: Optional[Literal["stdio", "http"]] = None
    command: Optional[List[str]] = None
    base_url: Optional[str] = Field(default=None, max_length=4096)
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    enabled: Optional[bool] = None


class ImportToolsBody(BaseModel):
    tool_names: Optional[List[str]] = Field(
        default=None,
        description="若省略则导入本次列出的全部工具（已存在 skill id 则跳过）",
    )


@router.get("/servers")
async def mcp_list_servers(enabled_only: bool = False) -> Dict[str, Any]:
    rows = list_mcp_servers(enabled_only=enabled_only)
    return {"object": "list", "data": rows}


@router.post("/servers")
async def mcp_create_server(body: CreateMcpServerBody) -> Dict[str, Any]:
    try:
        return create_mcp_server(
            name=body.name,
            description=body.description,
            transport=body.transport,
            base_url=body.base_url,
            command=list(body.command),
            cwd=body.cwd,
            env=body.env,
            enabled=body.enabled,
        )
    except ValueError as e:
        raise_api_error(status_code=400, code="mcp_invalid_server", message=str(e))


@router.get("/servers/{server_id}")
async def mcp_get_server(server_id: str) -> Dict[str, Any]:
    row = get_mcp_server(server_id)
    if not row:
        raise_api_error(status_code=404, code="mcp_server_not_found", message="MCP server not found")
    return row


@router.put("/servers/{server_id}")
async def mcp_update_server(server_id: str, body: UpdateMcpServerBody) -> Dict[str, Any]:
    try:
        row = update_mcp_server(
            server_id,
            name=body.name,
            description=body.description,
            transport=body.transport,
            base_url=body.base_url,
            command=list(body.command) if body.command is not None else None,
            cwd=body.cwd,
            env=body.env,
            enabled=body.enabled,
        )
    except ValueError as e:
        raise_api_error(status_code=400, code="mcp_invalid_server", message=str(e))
    if not row:
        raise_api_error(status_code=404, code="mcp_server_not_found", message="MCP server not found")
    return row


@router.delete("/servers/{server_id}")
async def mcp_delete_server(server_id: str) -> Dict[str, str]:
    ok = delete_mcp_server(server_id)
    if not ok:
        raise_api_error(status_code=404, code="mcp_server_not_found", message="MCP server not found")
    return {"status": "deleted", "id": server_id}


@router.get("/servers/{server_id}/tools")
async def mcp_server_tools(server_id: str) -> Dict[str, Any]:
    row = get_mcp_server(server_id)
    if not row:
        raise_api_error(status_code=404, code="mcp_server_not_found", message="MCP server not found")
    try:
        tools = await fetch_tools_for_server_config(row)
        return {"server_id": server_id, "tools": tools}
    except ValueError as e:
        raise_api_error(status_code=400, code="mcp_bad_request", message=str(e))
    except Exception as e:
        raise_api_error(
            status_code=502,
            code="mcp_tools_list_failed",
            message=str(e) or "tools/list failed",
        )


@router.get("/servers/{server_id}/skill-previews")
async def mcp_skill_previews(server_id: str) -> Dict[str, Any]:
    try:
        previews = await skill_previews_for_server(server_id)
        return {"server_id": server_id, "skill_previews": previews}
    except KeyError:
        raise_api_error(status_code=404, code="mcp_server_not_found", message="MCP server not found")
    except ValueError as e:
        raise_api_error(status_code=400, code="mcp_server_disabled", message=str(e))
    except Exception as e:
        raise_api_error(
            status_code=502,
            code="mcp_skill_preview_failed",
            message=str(e) or "skill preview failed",
        )


@router.post("/servers/{server_id}/import-tools")
async def mcp_import_tools(server_id: str, body: ImportToolsBody) -> Dict[str, Any]:
    try:
        return await import_mcp_tools_as_skills(server_id, tool_names=body.tool_names)
    except KeyError:
        raise_api_error(status_code=404, code="mcp_server_not_found", message="MCP server not found")
    except ValueError as e:
        raise_api_error(status_code=400, code="mcp_import_invalid", message=str(e))
    except Exception as e:
        raise_api_error(
            status_code=502,
            code="mcp_import_failed",
            message=str(e) or "import tools failed",
        )
