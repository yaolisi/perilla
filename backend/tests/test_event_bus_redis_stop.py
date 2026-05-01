"""Redis 事件总线关停释放连接。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.events.bus import RedisEventBus


@pytest.mark.asyncio
async def test_redis_event_bus_stop_aclose_client() -> None:
    bus = RedisEventBus("redis://127.0.0.1:6379/15", "test:eb")
    client = AsyncMock()
    bus._client = client
    await bus.stop()
    client.aclose.assert_awaited_once()
    assert bus._client is None


@pytest.mark.asyncio
async def test_redis_event_bus_stop_no_client_noop() -> None:
    bus = RedisEventBus("redis://127.0.0.1:6379/15", "test:eb2")
    bus._client = None
    await bus.stop()
