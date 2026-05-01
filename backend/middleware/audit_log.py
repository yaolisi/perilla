"""
审计中间件：在响应完成后记录控制面请求（可配置路径前缀）。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from config.settings import settings
from log import logger


class AuditLogMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)

    def _should_audit(self, path: str) -> bool:
        if not getattr(settings, "audit_log_enabled", False):
            return False
        # 避免审计查询自身产生无限写放大
        if path.startswith("/api/v1/audit"):
            return False
        prefixes = (getattr(settings, "audit_log_path_prefixes", "") or "").strip()
        if not prefixes:
            return False
        for p in prefixes.split(","):
            p = p.strip()
            if p and path.startswith(p):
                return True
        return False

    def _client_ip(self, request: Request) -> str:
        xff = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if xff:
            return xff[:128]
        if request.client:
            return request.client.host
        return ""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        try:
            if not self._should_audit(request.url.path):
                return response
            method = request.method.upper()
            if method in ("GET", "HEAD", "OPTIONS") and not getattr(
                settings, "audit_log_include_get", False
            ):
                return response

            from core.data.base import DB_ENGINE_STATE_KEY, get_engine, sessionmaker_for_engine
            from core.security.audit_service import append_audit_log
            from middleware.user_context import get_current_user

            user_id = getattr(request.state, "user_id", None) or get_current_user(request)
            tenant_id = getattr(request.state, "tenant_id", None) or getattr(settings, "tenant_default_id", "default")
            role = getattr(request.state, "platform_role", None)
            role_s = getattr(role, "value", None) or str(role or "operator")
            rid = getattr(request.state, "request_id", None)
            tid = getattr(request.state, "trace_id", None)
            bind = getattr(request.state, DB_ENGINE_STATE_KEY, None) or get_engine()
            db = sessionmaker_for_engine(bind)()
            try:
                append_audit_log(
                    db,
                    tenant_id=str(tenant_id),
                    user_id=str(user_id),
                    platform_role=role_s,
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    request_id=str(rid) if rid else None,
                    trace_id=str(tid) if tid else None,
                    client_ip=self._client_ip(request),
                    detail=None,
                )
            finally:
                db.close()
        except Exception as e:
            logger.debug(f"[AuditLog] skip: {e}")
        return response
