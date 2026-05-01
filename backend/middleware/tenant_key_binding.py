"""
API Key -> tenant 绑定校验中间件。
"""
from __future__ import annotations

import json
from typing import Dict, List

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config.settings import settings
from middleware.tenant_paths import is_tenant_enforcement_protected_path


def _parse_key_tenants(raw: str) -> Dict[str, List[str]]:
    try:
        data = json.loads(raw or "{}")
        if not isinstance(data, dict):
            return {}
        out: Dict[str, List[str]] = {}
        for k, v in data.items():
            if not isinstance(k, str) or not isinstance(v, list):
                continue
            out[k] = [str(x).strip() for x in v if str(x).strip()]
        return out
    except Exception:
        return {}


class TenantApiKeyBindingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._api_key_header = getattr(settings, "api_rate_limit_api_key_header", "X-Api-Key")

    async def dispatch(self, request: Request, call_next):
        if not getattr(settings, "tenant_api_key_binding_enabled", False):
            return await call_next(request)
        if not is_tenant_enforcement_protected_path(request.url.path):
            return await call_next(request)

        tenant_id = str(getattr(request.state, "tenant_id", "") or "").strip()
        if not tenant_id:
            tenant_header = getattr(settings, "tenant_header_name", "X-Tenant-Id")
            tenant_id = (request.headers.get(tenant_header) or getattr(settings, "tenant_default_id", "default")).strip()
        api_key = (request.headers.get(self._api_key_header) or "").strip()
        if not api_key:
            return JSONResponse(status_code=403, content={"detail": "api key required for tenant-bound path"})

        mapping = _parse_key_tenants(getattr(settings, "tenant_api_key_tenants_json", "{}"))
        allowed_tenants = mapping.get(api_key, [])
        if not allowed_tenants:
            return JSONResponse(status_code=403, content={"detail": "api key is not tenant-bound"})

        if "*" not in allowed_tenants and tenant_id not in allowed_tenants:
            return JSONResponse(
                status_code=403,
                content={"detail": "tenant access denied for api key", "tenant_id": tenant_id},
            )
        return await call_next(request)
