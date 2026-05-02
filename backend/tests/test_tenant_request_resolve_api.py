"""
租户解析：
- resolve_api_tenant_id：仅 state + settings 默认；无有效 state 时不读头。
- get_effective_tenant_id：state 有有效非空白字符串时用之；state 未设置时可读头；
  state 已设置但为空串/纯空白时回落 default、不读头。

二者在「state 已写入可信租户」时应一致且优先于请求头。
"""

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from config.settings import settings
from core.utils.tenant_request import get_effective_tenant_id, resolve_api_tenant_id

pytestmark = pytest.mark.tenant_isolation


def test_resolve_api_tenant_id_prefers_state():
    request = SimpleNamespace(state=SimpleNamespace(tenant_id="tenant-a"))
    assert resolve_api_tenant_id(request) == "tenant-a"


def test_state_tenant_wins_over_conflicting_header_for_both_resolvers():
    """网关已将租户写入 state 时，客户端头不得覆盖（两种解析函数行为一致）。"""
    hdr_name = getattr(settings, "tenant_header_name", "X-Tenant-Id")
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(hdr_name.lower().encode("ascii"), b"evil-other-tenant")],
    }
    request = Request(scope)
    request.state.tenant_id = "trusted-tenant"
    assert resolve_api_tenant_id(request) == "trusted-tenant"
    assert get_effective_tenant_id(request) == "trusted-tenant"


def test_resolve_api_tenant_id_ignores_tenant_header_when_state_absent():
    hdr_name = getattr(settings, "tenant_header_name", "X-Tenant-Id")
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(hdr_name.lower().encode("ascii"), b"from-header-tenant")],
    }
    request = Request(scope)
    default_tid = str(getattr(settings, "tenant_default_id", "default") or "default").strip() or "default"
    assert resolve_api_tenant_id(request) == default_tid
    assert get_effective_tenant_id(request) == "from-header-tenant"


def test_effective_empty_state_string_matches_resolve_ignores_header():
    hdr_name = getattr(settings, "tenant_header_name", "X-Tenant-Id")
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(hdr_name.lower().encode("ascii"), b"from-header-tenant")],
    }
    request = Request(scope)
    request.state.tenant_id = ""
    default_tid = str(getattr(settings, "tenant_default_id", "default") or "default").strip() or "default"
    assert resolve_api_tenant_id(request) == default_tid
    assert get_effective_tenant_id(request) == default_tid
