"""
In-memory API rate limit middleware.
用于基础防护，适合单进程部署。多实例场景可替换为 Redis 实现。
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque, Dict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        requests_per_window: int = 120,
        window_seconds: int = 60,
        api_key_header: str = "X-Api-Key",
    ):
        super().__init__(app)
        self._requests_per_window = max(1, int(requests_per_window))
        self._window_seconds = max(1, int(window_seconds))
        self._api_key_header = api_key_header
        self._lock = Lock()
        self._buckets: Dict[str, Deque[float]] = defaultdict(deque)

    def _identity(self, request: Request) -> str:
        api_key = request.headers.get(self._api_key_header, "").strip()
        if api_key:
            return f"key:{api_key}"
        xff = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if xff:
            return f"ip:{xff}"
        client_host = request.client.host if request.client else "unknown"
        return f"ip:{client_host}"

    @staticmethod
    def _identity_type(identity: str) -> str:
        if identity.startswith("key:"):
            return "api_key"
        if identity.startswith("ip:"):
            return "ip"
        return "unknown"

    def _allow(self, identity: str) -> bool:
        now = time.time()
        cutoff = now - self._window_seconds
        with self._lock:
            q = self._buckets[identity]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self._requests_per_window:
                return False
            q.append(now)
            return True

    async def dispatch(self, request: Request, call_next):
        # 健康检查路径跳过限流，避免探针抖动影响可用性。
        if request.url.path.startswith("/api/health"):
            return await call_next(request)

        identity = self._identity(request)
        if not self._allow(identity):
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": "Too many requests. Please retry later.",
                    "identity_type": self._identity_type(identity),
                    "window_seconds": self._window_seconds,
                    "limit": self._requests_per_window,
                },
            )

        return await call_next(request)
