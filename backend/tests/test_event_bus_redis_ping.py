"""事件总线 Redis PING 探测单元测试。"""

from __future__ import annotations

import pytest

import core.events.redis_ping as redis_ping


@pytest.mark.asyncio
async def test_probe_event_bus_redis_success(monkeypatch):
    class FakeClient:
        async def ping(self) -> bool:
            return True

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(redis_ping, "_redis_client_factory", lambda _url: FakeClient())

    await redis_ping.probe_event_bus_redis("redis://127.0.0.1:6379/1", timeout_seconds=1.0)


@pytest.mark.asyncio
async def test_probe_event_bus_redis_ping_raises(monkeypatch):
    class FakeClient:
        async def ping(self) -> bool:
            raise OSError("boom")

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(redis_ping, "_redis_client_factory", lambda _url: FakeClient())

    with pytest.raises(OSError, match="boom"):
        await redis_ping.probe_event_bus_redis("redis://127.0.0.1:6379/1", timeout_seconds=1.0)
