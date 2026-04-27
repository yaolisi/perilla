"""
Request trace middleware.
为每个请求注入 request_id、trace_id（W3C traceparent / X-Trace-Id），并记录耗时。
"""
from __future__ import annotations

import re
import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from config.settings import settings
from log import logger

# W3C traceparent: 00-{trace_id}-{parent_id}-{flags}，trace_id 为 32 位 hex
_TRACEPARENT_RE = re.compile(
    r"^[0-9a-f]{2}-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$",
    re.IGNORECASE,
)
_SAFE_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def _trace_id_from_traceparent(header_val: str | None) -> str | None:
    if not header_val:
        return None
    parts = header_val.strip().split("-")
    if len(parts) >= 2 and len(parts[1]) == 32:
        return parts[1].lower()
    m = _TRACEPARENT_RE.match(header_val.strip())
    if m:
        return m.group(1).lower()
    return None


def _sanitize_trace_id(trace_id: str | None) -> str | None:
    if not trace_id:
        return None
    val = trace_id.strip()
    if not val:
        return None
    if _SAFE_TRACE_ID_RE.match(val):
        return val
    return None


def _sanitize_request_id(request_id: str | None) -> str | None:
    if not request_id:
        return None
    val = request_id.strip()
    if not val:
        return None
    if _SAFE_REQUEST_ID_RE.match(val):
        return val
    return None


class RequestTraceMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, header_name: str = "X-Request-Id"):
        super().__init__(app)
        self._header_name = header_name

    async def dispatch(self, request: Request, call_next):
        request_id = _sanitize_request_id(request.headers.get(self._header_name)) or str(uuid.uuid4())
        request.state.request_id = request_id

        if getattr(settings, "trace_link_enabled", True):
            trace_id = _sanitize_trace_id(request.headers.get("X-Trace-Id"))
            if not trace_id:
                trace_id = _trace_id_from_traceparent(request.headers.get("traceparent"))
            if not trace_id:
                trace_id = request_id
        else:
            trace_id = request_id
        request.state.trace_id = trace_id

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        response.headers[self._header_name] = request_id
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
        logger.info(
            f"[Request] {request.method} {request.url.path} "
            f"status={response.status_code} request_id={request_id} trace_id={trace_id} latency_ms={elapsed_ms}",
            extra={
                "component": "RequestTrace",
                "trace_id": trace_id,
                "request_id": request_id,
            },
        )
        return response
