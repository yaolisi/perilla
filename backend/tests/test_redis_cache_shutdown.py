"""推理缓存 Redis 关停。"""

from __future__ import annotations

import pytest

import core.cache.redis_cache as rc_mod


@pytest.mark.asyncio
async def test_aclose_redis_cache_client_noop_when_uninitialized() -> None:
    with rc_mod._redis_cache_lock:
        rc_mod._redis_cache_client = None
    await rc_mod.aclose_redis_cache_client()


@pytest.mark.asyncio
async def test_aclose_redis_cache_client_calls_instance_aclose(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[int] = []

    class _Inst:
        async def aclose(self) -> None:
            called.append(1)

    monkeypatch.setattr(rc_mod, "_redis_cache_client", _Inst(), raising=False)
    await rc_mod.aclose_redis_cache_client()
    assert called == [1]
    assert rc_mod._redis_cache_client is None
