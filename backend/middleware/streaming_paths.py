"""
长生命周期 SSE / 流式 HTTP 路径集合。

SensitiveDataRedactionMiddleware（BaseHTTPMiddleware）对 JSON 请求会执行 ``await request.body()``
并重写 ``request._receive``；与下游 ``StreamingResponse``（SSE）叠加时可能触发 Starlette 与
ASGI 语义不匹配（例如 ``RuntimeError: Unexpected message received: http.request``）。

此类路径须在读取请求体之前短路，不对 SSE 响应迭代 ``body_iterator``。
"""

from __future__ import annotations


def is_sse_stream_exempt_path(path: str) -> bool:
    """是否为已知的 SSE 或长连接流式 API（中间件须完全旁路）。"""
    p = path or ""
    if p.startswith("/v1/chat/completions"):
        return True
    if p.startswith("/api/v1/chat/completions"):
        return True
    if p.startswith("/api/system/logs/stream"):
        return True
    if p.startswith("/api/v1/workflows/") and "/executions/" in p and p.endswith("/stream"):
        return True
    if p.startswith("/api/agent-sessions/") and p.endswith("/stream"):
        return True
    return False
