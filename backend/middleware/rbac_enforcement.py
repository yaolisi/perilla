"""
在 rbac_enforcement 开启时，按路径与方法拒绝 viewer 的写操作。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config.settings import settings
from core.security.rbac import (
    PlatformRole,
    parse_api_key_list,
    resolve_role_from_api_key,
    viewer_http_access_denied,
)


class RBACEnforcementMiddleware(BaseHTTPMiddleware):
    def _resolve_role_fallback(self, request: Request) -> PlatformRole:
        role = getattr(request.state, "platform_role", None)
        if isinstance(role, PlatformRole):
            return role
        # 兜底：即便执行顺序导致 RBACContext 尚未运行，也可按 API Key 推断角色，避免误放行。
        api_key_header = getattr(settings, "api_rate_limit_api_key_header", "X-Api-Key")
        api_key = request.headers.get(api_key_header)
        admin_keys = parse_api_key_list(getattr(settings, "rbac_admin_api_keys", "") or "")
        operator_keys = parse_api_key_list(getattr(settings, "rbac_operator_api_keys", "") or "")
        viewer_keys = parse_api_key_list(getattr(settings, "rbac_viewer_api_keys", "") or "")
        default_s = (getattr(settings, "rbac_default_role", "operator") or "operator").lower()
        try:
            default_role = PlatformRole(default_s)
        except ValueError:
            default_role = PlatformRole.OPERATOR
        return resolve_role_from_api_key(api_key, admin_keys, operator_keys, viewer_keys, default_role)

    async def dispatch(self, request: Request, call_next):
        if not getattr(settings, "rbac_enabled", False):
            return await call_next(request)
        if not getattr(settings, "rbac_enforcement", False):
            return await call_next(request)

        role = self._resolve_role_fallback(request)
        if role != PlatformRole.VIEWER:
            return await call_next(request)

        if viewer_http_access_denied(request.method, request.url.path):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "viewer role is not allowed to perform this operation",
                    "path": request.url.path,
                    "method": request.method,
                },
            )
        return await call_next(request)
