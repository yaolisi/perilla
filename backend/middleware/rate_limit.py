"""
API 请求限流中间件。

- 默认：进程内滑动窗口近似（deque）与并发计数（线程锁）。
- 可选：配置 api_rate_limit_redis_url 后，窗口计数与并发上限在 Redis 中共池，
  适合多副本部署（固定窗口 INCR；并发 INCR/DECR + Lua 原子封顶）。

Redis 临时不可用：默认 fail-open（放行）并记 Prometheus 计数；可将 api_rate_limit_redis_fail_closed=True
改为返回 503（严格依赖 Redis 的集群）。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any, Deque, Dict, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config.settings import settings
from core.observability.prometheus_metrics import get_prometheus_business_metrics
from middleware.client_ip import client_host_from_request
from middleware.ops_paths import is_ops_probe_or_metrics_path

logger = logging.getLogger(__name__)

_DEFAULT_REDIS_KEY_PREFIX = "perilla:ratelimit"

# 分布式并发：超过上限则撤销本次 INCR并拒绝（ARGV[1]=max concurrent, ARGV[2]=key TTL 秒）
_ACQUIRE_CONCURRENCY_LUA = """
local cur = redis.call('INCR', KEYS[1])
if cur == 1 then redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2])) end
if cur > tonumber(ARGV[1]) then
  redis.call('DECR', KEYS[1])
  return 0
end
return 1
"""


class RateLimitRedisUnavailableError(Exception):
    """配置了 fail-closed 且 Redis 不可用时由中间件抛出。"""


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    """关停时通过 `_active_redis_client` 关闭共享 Redis 连接（见 `aclose_rate_limit_redis_client`）。"""

    _active_redis_client: Any | None = None

    def __init__(
        self,
        app,
        requests_per_window: int = 120,
        window_seconds: int = 60,
        api_key_header: str = "X-Api-Key",
        max_concurrent_per_user: int = 5,
        *,
        redis_url: str | None = None,
        redis_key_prefix: str = _DEFAULT_REDIS_KEY_PREFIX,
        trust_x_forwarded_for: bool = True,
    ):
        super().__init__(app)
        self._trust_x_forwarded_for = bool(trust_x_forwarded_for)
        self._requests_per_window = max(1, int(requests_per_window))
        self._window_seconds = max(1, int(window_seconds))
        self._api_key_header = api_key_header
        self._max_concurrent_per_user = max(1, int(max_concurrent_per_user))
        self._redis_url = (redis_url or "").strip() or None
        rp = (redis_key_prefix or _DEFAULT_REDIS_KEY_PREFIX).strip().rstrip(":")
        self._redis_key_prefix = rp or _DEFAULT_REDIS_KEY_PREFIX

        self._lock = Lock()
        self._buckets: Dict[str, Deque[float]] = defaultdict(deque)
        self._in_flight_by_identity: Dict[str, int] = defaultdict(int)

        self._redis: Any = None
        self._redis_lock = asyncio.Lock()

    @staticmethod
    def _identity_digest(identity: str) -> str:
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _rate_backend_label(self) -> str:
        return "redis" if self._redis_url else "memory"

    def _observe_blocked(self, reason: str, identity: str) -> None:
        get_prometheus_business_metrics().observe_rate_limit_blocked(
            reason=reason,
            identity_type=self._identity_type(identity),
            backend=self._rate_backend_label(),
        )

    async def _get_redis(self) -> Any | None:
        if not self._redis_url:
            return None
        if self._redis is not None:
            return self._redis
        async with self._redis_lock:
            if self._redis is None:
                from core.redis_client_factory import create_async_redis_client

                self._redis = create_async_redis_client(self._redis_url)
                InMemoryRateLimitMiddleware._active_redis_client = self._redis
            return self._redis

    def _identity(self, request: Request) -> str:
        user_id = str(getattr(request.state, "user_id", "") or "").strip()
        if user_id:
            return f"user:{user_id}"
        api_key = request.headers.get(self._api_key_header, "").strip()
        if api_key:
            return f"key:{api_key}"
        host = client_host_from_request(request, trust_x_forwarded_for=self._trust_x_forwarded_for)
        if host:
            return f"ip:{host}"
        return "ip:unknown"

    @staticmethod
    def _identity_type(identity: str) -> str:
        if identity.startswith("user:"):
            return "user"
        if identity.startswith("key:"):
            return "api_key"
        if identity.startswith("ip:"):
            return "ip"
        return "unknown"

    def _allow_memory(self, identity: str) -> bool:
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

    async def _allow_redis(self, redis: Any, identity: str) -> bool:
        digest = self._identity_digest(identity)
        bucket = int(time.time() // self._window_seconds)
        key = f"{self._redis_key_prefix}:w:{digest}:{bucket}"
        n = int(await redis.incr(key))
        if n == 1:
            await redis.expire(key, self._window_seconds * 2 + 1)
        return n <= self._requests_per_window

    async def _allow(self, identity: str) -> bool:
        if not self._redis_url:
            return self._allow_memory(identity)
        try:
            redis = await self._get_redis()
            return await self._allow_redis(redis, identity)
        except Exception as e:
            get_prometheus_business_metrics().observe_rate_limit_redis_backend_error(phase="allow")
            if getattr(settings, "api_rate_limit_redis_fail_closed", False):
                raise RateLimitRedisUnavailableError from e
            logger.warning(
                "[RateLimit] Redis window check failed; fail-open (url configured)",
                exc_info=True,
            )
            return True

    def _acquire_concurrency_memory(self, identity: str) -> bool:
        with self._lock:
            cur = self._in_flight_by_identity.get(identity, 0)
            if cur >= self._max_concurrent_per_user:
                return False
            self._in_flight_by_identity[identity] = cur + 1
            return True

    def _conc_ttl_seconds(self) -> int:
        return max(120, min(86400, int(self._window_seconds) * 120))

    async def _acquire_concurrency_redis(self, redis: Any, identity: str) -> bool:
        key = f"{self._redis_key_prefix}:c:{self._identity_digest(identity)}"
        ttl = self._conc_ttl_seconds()
        r = await redis.eval(
            _ACQUIRE_CONCURRENCY_LUA,
            1,
            key,
            str(self._max_concurrent_per_user),
            str(ttl),
        )
        if isinstance(r, bytes):
            return bool(int(r.decode().strip() or "0"))
        return bool(int(r))

    async def _acquire_concurrency(self, redis: Optional[Any], identity: str) -> bool:
        if not self._redis_url:
            return self._acquire_concurrency_memory(identity)
        if redis is None:
            return True
        try:
            return await self._acquire_concurrency_redis(redis, identity)
        except Exception as e:
            get_prometheus_business_metrics().observe_rate_limit_redis_backend_error(phase="acquire")
            if getattr(settings, "api_rate_limit_redis_fail_closed", False):
                raise RateLimitRedisUnavailableError from e
            logger.warning(
                "[RateLimit] Redis concurrency acquire failed; fail-open",
                exc_info=True,
            )
            return True

    def _release_concurrency_memory(self, identity: str) -> None:
        with self._lock:
            cur = self._in_flight_by_identity.get(identity, 0) - 1
            if cur <= 0:
                self._in_flight_by_identity.pop(identity, None)
            else:
                self._in_flight_by_identity[identity] = cur

    async def _release_concurrency_redis(self, redis: Any, identity: str) -> None:
        key = f"{self._redis_key_prefix}:c:{self._identity_digest(identity)}"
        try:
            cur = int(await redis.decr(key))
            if cur < 0:
                await redis.set(key, 0)
        except Exception:
            get_prometheus_business_metrics().observe_rate_limit_redis_backend_error(phase="release")
            logger.debug("[RateLimit] Redis concurrency release ignored", exc_info=True)

    async def _release_concurrency(self, redis: Optional[Any], identity: str) -> None:
        if not self._redis_url:
            self._release_concurrency_memory(identity)
            return
        if redis is None:
            return
        try:
            await self._release_concurrency_redis(redis, identity)
        except Exception:
            pass

    def _json_429_rate(self, identity: str) -> JSONResponse:
        ra = str(max(1, int(self._window_seconds)))
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": ra},
            content={
                "error": "rate_limit_exceeded",
                "message": "Too many requests. Please retry later.",
                "identity_type": self._identity_type(identity),
                "window_seconds": self._window_seconds,
                "limit": self._requests_per_window,
            },
        )

    def _json_429_concurrency(self, identity: str) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "5"},
            content={
                "error": "concurrency_limit_exceeded",
                "message": "Too many concurrent requests for this user.",
                "identity_type": self._identity_type(identity),
                "concurrency_limit": self._max_concurrent_per_user,
            },
        )

    def _json_503_redis_backend(self) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": "5"},
            content={
                "error": "rate_limit_backend_unavailable",
                "message": "Rate limit backend temporarily unavailable.",
            },
        )

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if is_ops_probe_or_metrics_path(path):
            return await call_next(request)

        identity = self._identity(request)

        try:
            allowed = await self._allow(identity)
        except RateLimitRedisUnavailableError:
            return self._json_503_redis_backend()

        if not allowed:
            self._observe_blocked("window", identity)
            return self._json_429_rate(identity)

        redis = None
        if self._redis_url:
            try:
                redis = await self._get_redis()
            except Exception:
                redis = None  # _allow 已 fail-open；此处不再向外抛，避免未捕获 500

        try:
            ok = await self._acquire_concurrency(redis, identity)
        except RateLimitRedisUnavailableError:
            return self._json_503_redis_backend()

        if not ok:
            self._observe_blocked("concurrency", identity)
            return self._json_429_concurrency(identity)

        try:
            return await call_next(request)
        finally:
            await self._release_concurrency(redis, identity)


async def aclose_rate_limit_redis_client() -> None:
    """进程关停时关闭 API 限流中间件持有的 Redis 异步客户端（释放连接，便于优雅退出）。"""
    c = InMemoryRateLimitMiddleware._active_redis_client
    InMemoryRateLimitMiddleware._active_redis_client = None
    if c is None:
        return
    try:
        fn = getattr(c, "aclose", None)
        if callable(fn):
            await fn()
            logger.info("[RateLimit] Redis client closed for shutdown")
            return
        fn = getattr(c, "close", None)
        if callable(fn):
            out = fn()
            if asyncio.iscoroutine(out):
                await out
    except Exception as e:
        logger.debug("[RateLimit] Redis shutdown close failed: %s", e)
