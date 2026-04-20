"""
Tenant context middleware.
为请求注入 tenant_id，并可对关键控制面启用租户强制校验。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config.settings import settings


class TenantContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._header = getattr(settings, "tenant_header_name", "X-Tenant-Id")

    def _is_protected_path(self, path: str) -> bool:
        return (
            path.startswith("/api/v1/workflows")
            or path.startswith("/api/v1/audit")
            or path.startswith("/api/system")
        )

    async def dispatch(self, request: Request, call_next):
        header_tenant_id = (request.headers.get(self._header) or "").strip()
        tenant_id = (header_tenant_id or getattr(settings, "tenant_default_id", "default")).strip()
        if not tenant_id:
            tenant_id = getattr(settings, "tenant_default_id", "default")
        request.state.tenant_id = tenant_id

        if getattr(settings, "tenant_enforcement_enabled", False) and self._is_protected_path(request.url.path):
            # 受保护控制面必须显式携带租户头；允许使用 default 租户值。
            if not header_tenant_id:
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": "tenant id required for protected path",
                        "path": request.url.path,
                    },
                )
        return await call_next(request)
