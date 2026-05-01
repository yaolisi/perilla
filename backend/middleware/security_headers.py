"""
可选：为响应追加通用安全头（由 settings.security_headers_enabled 控制）。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from config.settings import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        if not bool(getattr(settings, "security_headers_enabled", False)):
            return response
        cto = (getattr(settings, "security_headers_x_content_type_options", "") or "").strip()
        if cto:
            response.headers.setdefault("X-Content-Type-Options", cto)
        xfo = (getattr(settings, "security_headers_x_frame_options", "") or "").strip()
        if xfo:
            response.headers.setdefault("X-Frame-Options", xfo)
        rp = (getattr(settings, "security_headers_referrer_policy", "") or "").strip()
        if rp:
            response.headers.setdefault("Referrer-Policy", rp)
        hsts = (getattr(settings, "security_headers_strict_transport_security", "") or "").strip()
        if hsts:
            response.headers.setdefault("Strict-Transport-Security", hsts)
        return response
