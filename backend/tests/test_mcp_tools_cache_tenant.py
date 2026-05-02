"""MCP tools/list 内存缓存按租户隔离。"""

import pytest

from core.mcp.tools_cache import clear_all_tools_cache, get_cached_tools, set_cached_tools

pytestmark = pytest.mark.tenant_isolation


def test_tools_cache_scopes_by_tenant_id() -> None:
    clear_all_tools_cache()
    try:
        set_cached_tools("srv_x", [{"name": "a"}], tenant_id="tenant_a")
        set_cached_tools("srv_x", [{"name": "b"}], tenant_id="tenant_b")
        assert get_cached_tools("srv_x", tenant_id="tenant_a") == [{"name": "a"}]
        assert get_cached_tools("srv_x", tenant_id="tenant_b") == [{"name": "b"}]
        set_cached_tools("srv_y", [{"name": "d"}], tenant_id=None)
        assert get_cached_tools("srv_y", tenant_id=None) == [{"name": "d"}]
        assert get_cached_tools("srv_y", tenant_id="default") == [{"name": "d"}]
    finally:
        clear_all_tools_cache()
