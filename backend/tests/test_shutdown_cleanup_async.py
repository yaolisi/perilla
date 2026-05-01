"""关停链路：事件总线失败不应阻断模型与连接池清理。"""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_shutdown_event_bus_stop_failure_still_runs_model_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    import main as main_module

    class _BadBus:
        async def stop(self) -> None:
            raise RuntimeError("event bus stop simulated failure")

    monkeypatch.setattr("core.events.get_event_bus", lambda: _BadBus())

    called: list[str] = []

    async def fake_unload(registry: object, factory: object) -> int:
        await asyncio.sleep(0)
        called.append("unload")
        return 2

    async def fake_cached(factory: object) -> None:
        await asyncio.sleep(0)
        called.append("cached")

    async def fake_close_db() -> None:
        await asyncio.sleep(0)
        called.append("db")

    async def fake_aclose_cache() -> None:
        await asyncio.sleep(0)
        called.append("cache")

    async def fake_aclose_rl() -> None:
        await asyncio.sleep(0)
        called.append("ratelimit")

    def fake_dispose() -> None:
        called.append("dispose")

    monkeypatch.setattr(main_module, "_shutdown_unload_registered_models", fake_unload)
    monkeypatch.setattr(main_module, "_shutdown_cleanup_cached_runtimes", fake_cached)
    monkeypatch.setattr("execution_kernel.persistence.db.close_global_database", fake_close_db)
    monkeypatch.setattr("core.cache.redis_cache.aclose_redis_cache_client", fake_aclose_cache)
    monkeypatch.setattr("middleware.rate_limit.aclose_rate_limit_redis_client", fake_aclose_rl)
    monkeypatch.setattr("core.data.base.dispose_engine", fake_dispose)

    n = await main_module._shutdown_cleanup_async()
    assert n == 2
    assert called == ["unload", "cached", "db", "cache", "ratelimit", "dispose"]
