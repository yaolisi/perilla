"""API 限流 Redis 客户端关停。"""

from __future__ import annotations

import pytest

from middleware.rate_limit import InMemoryRateLimitMiddleware, aclose_rate_limit_redis_client


@pytest.mark.asyncio
async def test_aclose_rate_limit_redis_noop_when_absent() -> None:
    InMemoryRateLimitMiddleware._active_redis_client = None
    await aclose_rate_limit_redis_client()


@pytest.mark.asyncio
async def test_aclose_rate_limit_redis_calls_aclose() -> None:
    called: list[int] = []

    class _Fake:
        async def aclose(self) -> None:
            called.append(1)

    InMemoryRateLimitMiddleware._active_redis_client = _Fake()
    await aclose_rate_limit_redis_client()
    assert called == [1]
    assert InMemoryRateLimitMiddleware._active_redis_client is None
