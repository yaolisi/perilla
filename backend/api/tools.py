import sys
from typing import Annotated, Dict, Any

from fastapi import APIRouter, Query

from api.errors import raise_api_error
from core.tools.registry import ToolRegistry
from core.tools.context import ToolContext
from core.tools.base import Tool
from config.settings import settings

router = APIRouter(prefix="/api/tools", tags=["tools"])


def _duckduckgo_import_status() -> Dict[str, Any]:
    """Check if duckduckgo_search is importable in the process that runs the backend."""
    out = {"python": sys.executable, "duckduckgo_search": None}
    try:
        from duckduckgo_search import DDGS  # type: ignore[import-not-found]
        out["duckduckgo_search"] = "ok"
    except ImportError as e:
        out["duckduckgo_search"] = f"ImportError: {e}"
    except Exception as e:
        out["duckduckgo_search"] = f"{type(e).__name__}: {e}"
    return out


@router.get("/web-search/diagnostic")
async def web_search_diagnostic() -> Dict[str, Any]:
    """
    Show which Python runs the backend and whether duckduckgo_search can be imported.
    Use this to confirm you install duckduckgo-search in the correct environment.
    """
    return _duckduckgo_import_status()


@router.get("")
async def list_tools() -> Dict[str, Any]:
    """List all registered tools and their schemas."""
    tools = ToolRegistry.list()
    return {
        "object": "list",
        "data": [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "output_schema": tool.output_schema,
                "required_permissions": getattr(tool, "required_permissions", []) or [],
                "ui": getattr(tool, "ui_hint", None) if hasattr(tool, "ui_hint") else None,
            }
            for tool in tools
        ],
    }


@router.get("/web-search/probe")
async def web_search_probe(
    query: Annotated[str, Query(description="Search query")] = "test",
) -> Dict[str, Any]:
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
    data = result.data if isinstance(result.data, list) else []
    return {
        "ok": result.success,
        "mock": not enabled,
        "tool_net_web_enabled": enabled,
        "results_count": len(data),
        "results": data[:5] if result.success else None,
        "error": None if result.success else result.error,
        "diagnostic": diag,
    }


@router.get("/{name}")
async def get_tool(name: str) -> Dict[str, Any]:
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
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
        "required_permissions": getattr(tool, "required_permissions", []) or [],
        "ui": getattr(tool, "ui_hint", None) if hasattr(tool, "ui_hint") else None,
    }
