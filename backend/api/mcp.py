"""
MCP：探测、Server 配置 CRUD、tools 列表、Skill 导入预览。
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, RootModel, model_validator

from api.errors import raise_api_error
from log import log_structured
from core.utils.tenant_request import resolve_api_tenant_id
from api.skill_discovery import SkillDefinitionDiscoveryRecord
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

MSG_MCP_SERVER_NOT_FOUND = "MCP server not found"

router = APIRouter(
    prefix="/api/mcp",
    tags=["mcp"],
    dependencies=[Depends(require_authenticated_platform_admin)],
)


def _mcp_audit_kwargs(request: Request, tenant_id: str) -> Dict[str, Any]:
    """控制面审计公共字段（不落敏感配置）。"""
    return {
        "tenant_id": tenant_id,
        "trace_id": getattr(request.state, "trace_id", None),
        "request_id": getattr(request.state, "request_id", None),
        "user_id": getattr(request.state, "user_id", None),
    }


def _mcp_failure_log(
    request: Request,
    tenant_id: str,
    event: str,
    *,
    level: str = "warning",
    **extra: Any,
) -> None:
    """失败路径审计（message 类字段调用方已截断）。"""
    log_structured("McpApi", event, level=level, **_mcp_audit_kwargs(request, tenant_id), **extra)


class McpJsonMap(BaseModel):
    """MCP 工具 inputSchema / 配置中的自由 JSON 对象。"""

    model_config = ConfigDict(extra="allow")


class McpImportErrorRow(RootModel[Dict[str, str]]):
    """导入工具时的错误条目（如 tool / error 等字符串键值）。"""


class McpEnvMap(RootModel[Dict[str, str]]):
    """stdio 探测与服务配置中的环境变量键值。"""


def _optional_env_dict(env: Optional[McpEnvMap]) -> Optional[Dict[str, str]]:
    if env is None:
        return None
    return env.model_dump()


class McpToolDescriptor(BaseModel):
    """MCP `tools/list` 单项（兼容 inputSchema / input_schema，额外字段保留）。"""

    model_config = ConfigDict(extra="allow")

    name: str
    title: Optional[str] = None
    description: Optional[str] = None
    input_schema: Optional[McpJsonMap] = Field(
        default=None,
        validation_alias=AliasChoices("inputSchema", "input_schema"),
        serialization_alias="inputSchema",
    )


class McpProbeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: Literal[True] = True
    tools: List[McpToolDescriptor]
    negotiated_protocol_version: Optional[str] = None


class McpServerRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    tenant_id: str = "default"
    name: str
    description: str
    transport: Literal["stdio", "http"]
    base_url: str
    command: List[str]
    env: McpEnvMap
    cwd: str
    enabled: bool


class McpServerListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object: Literal["list"] = "list"
    data: List[McpServerRecord]


class McpServerDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["deleted"] = "deleted"
    id: str


class McpServerToolsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    tools: List[McpToolDescriptor]


class McpSkillPreviewsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    skill_previews: List[SkillDefinitionDiscoveryRecord]


class McpImportToolsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    imported: List[str]
    skipped_existing: List[str]
    errors: List[McpImportErrorRow]


class ProbeBody(BaseModel):
    command: Optional[List[str]] = None
    url: Optional[str] = Field(default=None, max_length=4096)
    cwd: Optional[str] = None
    env: Optional[McpEnvMap] = None
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
async def mcp_probe(request: Request, body: ProbeBody) -> McpProbeResponse:
    """不依赖数据库：stdio 命令或 Streamable HTTP URL，握手 + tools/list。"""
    tid = resolve_api_tenant_id(request)
    u0 = (body.url or "").strip()
    transport_hint = "http" if u0 else "stdio"
    try:
        u = u0
        if u:
            raw = await probe_http_url(
                u,
                env=_optional_env_dict(body.env),
                request_timeout=body.request_timeout,
            )
            transport = "http"
        else:
            raw = await probe_command(
                list(body.command or []),
                cwd=body.cwd,
                env=_optional_env_dict(body.env),
                request_timeout=body.request_timeout,
            )
            transport = "stdio"
        tools_n = len(raw.get("tools") or []) if isinstance(raw, dict) else 0
        log_structured(
            "McpApi",
            "mcp_api_probe_ok",
            transport=transport,
            tools_count=tools_n,
            **_mcp_audit_kwargs(request, tid),
        )
        return McpProbeResponse.model_validate(raw)
    except Exception as e:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_probe_failed",
            transport=transport_hint,
            error_type=type(e).__name__,
            error_message=(str(e) or "")[:500],
        )
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
    env: Optional[McpEnvMap] = None
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
    env: Optional[McpEnvMap] = None
    enabled: Optional[bool] = None


class ImportToolsBody(BaseModel):
    tool_names: Optional[List[str]] = Field(
        default=None,
        description="若省略则导入本次列出的全部工具（已存在 skill id 则跳过）",
    )


@router.get("/servers")
async def mcp_list_servers(
    request: Request,
    enabled_only: bool = False,
) -> McpServerListResponse:
    tid = resolve_api_tenant_id(request)
    rows = list_mcp_servers(enabled_only=enabled_only, tenant_id=tid)
    log_structured(
        "McpApi",
        "mcp_api_servers_list",
        enabled_only=enabled_only,
        result_count=len(rows),
        **_mcp_audit_kwargs(request, tid),
    )
    return McpServerListResponse(data=[McpServerRecord.model_validate(r) for r in rows])


@router.post("/servers")
async def mcp_create_server(request: Request, body: CreateMcpServerBody) -> McpServerRecord:
    tid = resolve_api_tenant_id(request)
    try:
        row = create_mcp_server(
            name=body.name,
            description=body.description,
            transport=body.transport,
            base_url=body.base_url,
            command=list(body.command),
            cwd=body.cwd,
            env=_optional_env_dict(body.env),
            enabled=body.enabled,
            tenant_id=tid,
        )
        log_structured(
            "McpApi",
            "mcp_api_server_create",
            server_id=row.get("id"),
            name=row.get("name"),
            transport=row.get("transport"),
            enabled=bool(row.get("enabled", True)),
            **_mcp_audit_kwargs(request, tid),
        )
        return McpServerRecord.model_validate(row)
    except ValueError as e:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_validation_error",
            context="create_server",
            api_code="mcp_invalid_server",
            error_message=(str(e) or "")[:500],
        )
        raise_api_error(status_code=400, code="mcp_invalid_server", message=str(e))


@router.get("/servers/{server_id}")
async def mcp_get_server(request: Request, server_id: str) -> McpServerRecord:
    tid = resolve_api_tenant_id(request)
    row = get_mcp_server(server_id, tenant_id=tid)
    if not row:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_server_not_found",
            operation="get",
            server_id=server_id,
        )
        raise_api_error(status_code=404, code="mcp_server_not_found", message=MSG_MCP_SERVER_NOT_FOUND)
    log_structured(
        "McpApi",
        "mcp_api_server_get",
        server_id=server_id,
        transport=row.get("transport"),
        **_mcp_audit_kwargs(request, tid),
    )
    return McpServerRecord.model_validate(row)


@router.put("/servers/{server_id}")
async def mcp_update_server(request: Request, server_id: str, body: UpdateMcpServerBody) -> McpServerRecord:
    tid = resolve_api_tenant_id(request)
    try:
        row = update_mcp_server(
            server_id,
            name=body.name,
            description=body.description,
            transport=body.transport,
            base_url=body.base_url,
            command=list(body.command) if body.command is not None else None,
            cwd=body.cwd,
            env=_optional_env_dict(body.env),
            enabled=body.enabled,
            tenant_id=tid,
        )
    except ValueError as e:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_validation_error",
            context="update_server",
            api_code="mcp_invalid_server",
            server_id=server_id,
            error_message=(str(e) or "")[:500],
        )
        raise_api_error(status_code=400, code="mcp_invalid_server", message=str(e))
    if not row:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_server_not_found",
            operation="update",
            server_id=server_id,
        )
        raise_api_error(status_code=404, code="mcp_server_not_found", message=MSG_MCP_SERVER_NOT_FOUND)
    log_structured(
        "McpApi",
        "mcp_api_server_update",
        server_id=server_id,
        transport=row.get("transport"),
        enabled=bool(row.get("enabled", True)),
        **_mcp_audit_kwargs(request, tid),
    )
    return McpServerRecord.model_validate(row)


@router.delete("/servers/{server_id}")
async def mcp_delete_server(request: Request, server_id: str) -> McpServerDeleteResponse:
    tid = resolve_api_tenant_id(request)
    ok = delete_mcp_server(server_id, tenant_id=tid)
    if not ok:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_server_not_found",
            operation="delete",
            server_id=server_id,
        )
        raise_api_error(status_code=404, code="mcp_server_not_found", message=MSG_MCP_SERVER_NOT_FOUND)
    log_structured(
        "McpApi",
        "mcp_api_server_delete",
        server_id=server_id,
        **_mcp_audit_kwargs(request, tid),
    )
    return McpServerDeleteResponse(id=server_id)


@router.get("/servers/{server_id}/tools")
async def mcp_server_tools(request: Request, server_id: str) -> McpServerToolsResponse:
    tid = resolve_api_tenant_id(request)
    row = get_mcp_server(server_id, tenant_id=tid)
    if not row:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_server_not_found",
            operation="tools_list",
            server_id=server_id,
        )
        raise_api_error(status_code=404, code="mcp_server_not_found", message=MSG_MCP_SERVER_NOT_FOUND)
    try:
        tools_raw = await fetch_tools_for_server_config(row)
        tools = [McpToolDescriptor.model_validate(t) for t in tools_raw if isinstance(t, dict)]
        log_structured(
            "McpApi",
            "mcp_api_server_tools_list",
            server_id=server_id,
            tools_count=len(tools),
            **_mcp_audit_kwargs(request, tid),
        )
        return McpServerToolsResponse(server_id=server_id, tools=tools)
    except ValueError as e:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_server_tools_failed",
            api_code="mcp_bad_request",
            server_id=server_id,
            error_message=(str(e) or "")[:500],
        )
        raise_api_error(status_code=400, code="mcp_bad_request", message=str(e))
    except Exception as e:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_server_tools_failed",
            level="error",
            api_code="mcp_tools_list_failed",
            server_id=server_id,
            error_type=type(e).__name__,
            error_message=(str(e) or "")[:500],
        )
        raise_api_error(
            status_code=502,
            code="mcp_tools_list_failed",
            message=str(e) or "tools/list failed",
        )


@router.get("/servers/{server_id}/skill-previews")
async def mcp_skill_previews(request: Request, server_id: str) -> McpSkillPreviewsResponse:
    tid = resolve_api_tenant_id(request)
    try:
        previews_raw = await skill_previews_for_server(server_id, tenant_id=tid)
        previews = [SkillDefinitionDiscoveryRecord.model_validate(p) for p in previews_raw]
        log_structured(
            "McpApi",
            "mcp_api_server_skill_previews",
            server_id=server_id,
            previews_count=len(previews),
            **_mcp_audit_kwargs(request, tid),
        )
        return McpSkillPreviewsResponse(server_id=server_id, skill_previews=previews)
    except KeyError:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_server_not_found",
            operation="skill_previews",
            server_id=server_id,
        )
        raise_api_error(status_code=404, code="mcp_server_not_found", message=MSG_MCP_SERVER_NOT_FOUND)
    except ValueError as e:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_skill_previews_failed",
            api_code="mcp_server_disabled",
            server_id=server_id,
            error_message=(str(e) or "")[:500],
        )
        raise_api_error(status_code=400, code="mcp_server_disabled", message=str(e))
    except Exception as e:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_skill_previews_failed",
            level="error",
            api_code="mcp_skill_preview_failed",
            server_id=server_id,
            error_type=type(e).__name__,
            error_message=(str(e) or "")[:500],
        )
        raise_api_error(
            status_code=502,
            code="mcp_skill_preview_failed",
            message=str(e) or "skill preview failed",
        )


@router.post("/servers/{server_id}/import-tools")
async def mcp_import_tools(request: Request, server_id: str, body: ImportToolsBody) -> McpImportToolsResponse:
    tid = resolve_api_tenant_id(request)
    try:
        raw = await import_mcp_tools_as_skills(server_id, tool_names=body.tool_names, tenant_id=tid)
        resp = McpImportToolsResponse.model_validate(raw)
        log_structured(
            "McpApi",
            "mcp_api_server_import_tools",
            server_id=server_id,
            imported_count=len(resp.imported),
            skipped_count=len(resp.skipped_existing),
            errors_count=len(resp.errors),
            filter_tool_names=bool(body.tool_names),
            **_mcp_audit_kwargs(request, tid),
        )
        return resp
    except KeyError:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_server_not_found",
            operation="import_tools",
            server_id=server_id,
        )
        raise_api_error(status_code=404, code="mcp_server_not_found", message=MSG_MCP_SERVER_NOT_FOUND)
    except ValueError as e:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_import_tools_failed",
            api_code="mcp_import_invalid",
            server_id=server_id,
            error_message=(str(e) or "")[:500],
        )
        raise_api_error(status_code=400, code="mcp_import_invalid", message=str(e))
    except Exception as e:
        _mcp_failure_log(
            request,
            tid,
            "mcp_api_import_tools_failed",
            level="error",
            api_code="mcp_import_failed",
            server_id=server_id,
            error_type=type(e).__name__,
            error_message=(str(e) or "")[:500],
        )
        raise_api_error(
            status_code=502,
            code="mcp_import_failed",
            message=str(e) or "import tools failed",
        )
