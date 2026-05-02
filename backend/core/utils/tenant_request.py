"""租户解析工具：resolve_api_tenant_id（控制面）、get_effective_tenant_id（允许租户头的业务 API）。"""

from __future__ import annotations

from starlette.requests import Request

from config.settings import settings
from core.workflows.tenant_guard import resolve_tenant_id


def resolve_api_tenant_id(request: Request) -> str:
    """
    控制面 / 业务 API 统一租户：仅使用 request.state.tenant_id（中间件注入），
    缺省为 settings.tenant_default_id。不读取 X-Tenant-Id 等请求头
    （与 get_effective_tenant_id 不同，避免头覆盖 state）。
    """
    default = str(getattr(settings, "tenant_default_id", "default") or "default").strip() or "default"
    return resolve_tenant_id(request, default_tenant=default)


def get_effective_tenant_id(request: Request) -> str:
    """
    state.tenant_id 未设置：可读租户头，最后 settings 默认。
    state 已设置但去空白后为空（\"\"、纯空白）：回落默认租户，不读头（与网关误写空 state 时避免头注入对齐）。
    """
    default = str(getattr(settings, "tenant_default_id", "default") or "default").strip() or "default"
    raw = getattr(request.state, "tenant_id", None)
    if raw is not None:
        s = str(raw).strip()
        if s:
            return s
        return default
    hdr = getattr(settings, "tenant_header_name", "X-Tenant-Id")
    from_hdr = (request.headers.get(hdr) or "").strip()
    if from_hdr:
        return from_hdr
    return default
