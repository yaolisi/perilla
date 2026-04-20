"""
API Key scope middleware.
基于配置中的 api_key_scopes_json 对敏感路径进行 scope 校验。
"""
from __future__ import annotations

import json
from typing import Dict, List

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config.settings import settings


def _parse_scopes(raw: str) -> Dict[str, List[str]]:
    try:
        data = json.loads(raw or "{}")
        if not isinstance(data, dict):
            return {}
        out: Dict[str, List[str]] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, list):
                out[k] = [str(x) for x in v]
        return out
    except Exception:
        return {}


class ApiKeyScopeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._header = getattr(settings, "api_rate_limit_api_key_header", "X-Api-Key")

    def _required_scope(self, method: str, path: str) -> str | None:
        m = method.upper()
        if path.startswith("/api/v1/audit"):
            return "audit:read"
        if path.startswith("/api/v1/workflows") and m in {"POST", "PUT", "PATCH", "DELETE"}:
            return "workflow:write"
        if path.startswith("/api/models") and m in {"POST", "PUT", "PATCH", "DELETE"}:
            return "model:write"
        return None

    async def dispatch(self, request: Request, call_next):
        required = self._required_scope(request.method, request.url.path)
        if not required:
            return await call_next(request)

        api_key = (request.headers.get(self._header) or "").strip()
        scopes_map = _parse_scopes(getattr(settings, "api_key_scopes_json", "{}"))
        scopes = scopes_map.get(api_key, [])
        if required not in scopes and "admin" not in scopes:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "insufficient api key scope",
                    "required_scope": required,
                    "path": request.url.path,
                },
            )
        request.state.api_key_scopes = scopes
        return await call_next(request)
