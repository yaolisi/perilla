"""
CSRF protection middleware (double-submit cookie).
"""
from __future__ import annotations

import secrets
from hmac import compare_digest

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config.settings import settings


class CSRFMiddleware(BaseHTTPMiddleware):
    _SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

    def __init__(self, app):
        super().__init__(app)
        self._header_name = getattr(settings, "csrf_header_name", "X-CSRF-Token")
        self._cookie_name = getattr(settings, "csrf_cookie_name", "csrf_token")
        self._cookie_path = getattr(settings, "csrf_cookie_path", "/")
        self._cookie_samesite = getattr(settings, "csrf_cookie_samesite", "lax")
        self._cookie_max_age = int(getattr(settings, "csrf_cookie_max_age_seconds", 86400) or 86400)
        self._cookie_secure = bool(
            getattr(settings, "csrf_cookie_secure", False) or (not bool(getattr(settings, "debug", True)))
        )

    @staticmethod
    def _new_token() -> str:
        return secrets.token_urlsafe(32)

    def _set_cookie(self, response, token: str) -> None:
        response.set_cookie(
            key=self._cookie_name,
            value=token,
            max_age=self._cookie_max_age,
            path=self._cookie_path,
            secure=self._cookie_secure,
            httponly=False,  # frontend needs to read and echo token
            samesite=self._cookie_samesite,
        )

    def _is_exempt_path(self, path: str) -> bool:
        return path.startswith("/api/health") or path in {"/", "/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        if not bool(getattr(settings, "csrf_enabled", True)):
            return await call_next(request)

        method = (request.method or "").upper()
        path = request.url.path or ""
        cookie_token = (request.cookies.get(self._cookie_name) or "").strip()

        if method not in self._SAFE_METHODS and not self._is_exempt_path(path):
            header_token = (request.headers.get(self._header_name) or "").strip()
            if not cookie_token or not header_token or not compare_digest(cookie_token, header_token):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "CSRF token validation failed",
                        "required_header": self._header_name,
                    },
                )

        response = await call_next(request)

        effective_token = cookie_token or self._new_token()
        response.headers[self._header_name] = effective_token
        if not cookie_token:
            self._set_cookie(response, effective_token)
        return response
