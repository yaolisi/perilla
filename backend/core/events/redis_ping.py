"""
事件总线 Redis 连通性探测（启动 / 运维自检）

短超时 PING，失败即抛错，由调用方决定是否阻断启动。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable


def _default_redis_client(url: str) -> Any:
    from core.redis_client_factory import create_async_redis_client

    return create_async_redis_client(url, decode_responses=True)


_redis_client_factory: Callable[[str], Any] = _default_redis_client


def set_redis_client_factory_for_testing(factory: Callable[[str], Any] | None) -> None:
    """测试注入客户端工厂；传 None 恢复默认。"""
    global _redis_client_factory
    _redis_client_factory = factory or _default_redis_client


async def probe_redis_url(url: str, *, timeout_seconds: float = 2.0) -> None:
    """
    对任意 Redis URL 执行短超时 PING；失败抛出异常。
    使用独立短生命周期客户端，便于启动/就绪探针与业务连接池解耦。
    """
    client = _redis_client_factory(url.strip())
    try:
        await asyncio.wait_for(client.ping(), timeout=max(0.1, float(timeout_seconds)))
    finally:
        close = getattr(client, "aclose", None)
        if callable(close):
            await close()
        else:
            close_sync = getattr(client, "close", None)
            if callable(close_sync):
                maybe = close_sync()
                if asyncio.iscoroutine(maybe):
                    await maybe


async def probe_event_bus_redis(url: str, *, timeout_seconds: float = 2.0) -> None:
    """
    对给定 Redis URL 执行 PING；失败抛出异常。

    使用独立短生命周期客户端，避免与 EventBus 内懒加载客户端耦合。
    """
    await probe_redis_url(url, timeout_seconds=timeout_seconds)
