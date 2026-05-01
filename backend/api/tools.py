import sys
from typing import Annotated, List, Literal, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from api.errors import raise_api_error
from core.tools.registry import ToolRegistry
from core.tools.context import ToolContext
from core.tools.base import Tool
from config.settings import settings

router = APIRouter(prefix="/api/tools", tags=["tools"])


class ToolJsonMap(BaseModel):
    """工具描述中的 JSON Schema 片段或 UI 提示等自由对象。"""

    model_config = ConfigDict(extra="allow")


class WebSearchDiagnosticResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    python: str
    duckduckgo_search: Optional[str] = None


class WebSearchResultItem(BaseModel):
    """web.search 单条结果（Serper/DuckDuckGo 字段略有差异，允许扩展键）。"""

    model_config = ConfigDict(extra="allow")

    title: Optional[str] = None
    snippet: Optional[str] = None
    url: Optional[str] = None


class ToolDescriptorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    input_schema: ToolJsonMap
    output_schema: ToolJsonMap
    required_permissions: List[str]
    ui: Optional[ToolJsonMap] = None


class ToolListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object: Literal["list"] = "list"
    data: List[ToolDescriptorResponse]


class WebSearchProbeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    mock: bool
    tool_net_web_enabled: bool
    results_count: int
    results: Optional[List[WebSearchResultItem]] = None
    error: Optional[str] = None
    diagnostic: WebSearchDiagnosticResponse


def _tool_descriptor(tool: Tool) -> ToolDescriptorResponse:
    ui_val = getattr(tool, "ui_hint", None) if hasattr(tool, "ui_hint") else None
    ui_model = ToolJsonMap.model_validate(ui_val) if isinstance(ui_val, dict) else None
    return ToolDescriptorResponse(
        name=tool.name,
        description=tool.description,
        input_schema=ToolJsonMap.model_validate(dict(tool.input_schema or {})),
        output_schema=ToolJsonMap.model_validate(dict(tool.output_schema or {})),
        required_permissions=list(getattr(tool, "required_permissions", []) or []),
        ui=ui_model,
    )


def _duckduckgo_import_status() -> WebSearchDiagnosticResponse:
    """Check if duckduckgo_search is importable in the process that runs the backend."""
    ddg: Optional[str] = None
    try:
        from duckduckgo_search import DDGS  # type: ignore[import-not-found]

        _ = DDGS  # import side-effect only
        ddg = "ok"
    except ImportError as e:
        ddg = f"ImportError: {e}"
    except Exception as e:
        ddg = f"{type(e).__name__}: {e}"
    return WebSearchDiagnosticResponse(python=sys.executable, duckduckgo_search=ddg)


@router.get("/web-search/diagnostic")
async def web_search_diagnostic() -> WebSearchDiagnosticResponse:
    """
    Show which Python runs the backend and whether duckduckgo_search can be imported.
    Use this to confirm you install duckduckgo-search in the correct environment.
    """
    return _duckduckgo_import_status()


@router.get("")
async def list_tools() -> ToolListResponse:
    """List all registered tools and their schemas."""
    tools = ToolRegistry.list()
    return ToolListResponse(data=[_tool_descriptor(tool) for tool in tools])


@router.get("/web-search/probe")
async def web_search_probe(
    query: Annotated[str, Query(description="Search query")] = "test",
) -> WebSearchProbeResponse:
    """
    Directly run web.search tool to verify it works (bypasses agent).
    Returns ok, mock, results_count, error, and diagnostic (python path + duckduckgo_search import status).
    """
    diag = _duckduckgo_import_status()
    tool = ToolRegistry.get("web.search")
    if not tool:
        raise_api_error(
            status_code=503,
            code="tool_web_search_not_registered",
            message="Tool web.search not registered",
        )
    tool = tool if isinstance(tool, Tool) else None
    if tool is None:
        raise_api_error(
            status_code=503,
            code="tool_web_search_invalid",
            message="Tool web.search is invalid",
        )
    assert tool is not None
    enabled = getattr(settings, "tool_net_web_enabled", True)
    ctx = ToolContext(agent_id=None, trace_id="probe", workspace=".", permissions={"net.web": True})
    result = await tool.run({"query": query, "top_k": 3}, ctx)
    raw = result.data if isinstance(result.data, list) else []
    rows: List[WebSearchResultItem] = []
    for item in raw[:5]:
        if isinstance(item, dict):
            rows.append(WebSearchResultItem.model_validate(item))
    return WebSearchProbeResponse(
        ok=result.success,
        mock=not enabled,
        tool_net_web_enabled=enabled,
        results_count=len(raw),
        results=rows if result.success else None,
        error=None if result.success else result.error,
        diagnostic=diag,
    )


@router.get("/{name}")
async def get_tool(name: str) -> ToolDescriptorResponse:
    """Get a specific tool's schema."""
    tool = ToolRegistry.get(name)
    if not tool:
        raise_api_error(
            status_code=404,
            code="tool_not_found",
            message="Tool not found",
            details={"name": name},
        )
    tool = tool if isinstance(tool, Tool) else None
    if tool is None:
        raise_api_error(
            status_code=500,
            code="tool_registry_invalid",
            message="Tool registry returned invalid tool",
            details={"name": name},
        )
    assert tool is not None
    return _tool_descriptor(tool)
