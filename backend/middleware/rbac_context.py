"""
注入平台角色（PlatformRole）到 request.state.platform_role。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from config.settings import settings
from core.security.rbac import PlatformRole, parse_api_key_list, resolve_role_from_api_key


class RBACContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key_header: str = "X-Api-Key"):
        super().__init__(app)
        self._api_key_header = api_key_header

    async def dispatch(self, request: Request, call_next):
        if not getattr(settings, "rbac_enabled", False):
            request.state.platform_role = PlatformRole.OPERATOR
            return await call_next(request)

        api_key = request.headers.get(self._api_key_header)
        admin_keys = parse_api_key_list(getattr(settings, "rbac_admin_api_keys", "") or "")
        operator_keys = parse_api_key_list(getattr(settings, "rbac_operator_api_keys", "") or "")
        viewer_keys = parse_api_key_list(getattr(settings, "rbac_viewer_api_keys", "") or "")
        default_s = (getattr(settings, "rbac_default_role", "operator") or "operator").lower()
        try:
            default_role = PlatformRole(default_s)
        except ValueError:
            default_role = PlatformRole.OPERATOR

        role = resolve_role_from_api_key(
            api_key, admin_keys, operator_keys, viewer_keys, default_role
        )
        request.state.platform_role = role
        return await call_next(request)
