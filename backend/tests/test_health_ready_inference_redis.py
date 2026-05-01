"""就绪探针：推理缓存 Redis 严格模式。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

import core.cache.redis_cache as redis_cache_mod
import main as main_mod


def _patch_health_ready_db(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Conn:
        def execute(self, *_a, **_k):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_a, **_k):
            pass

    class _Eng:
        def connect(self):
            return _Conn()

    monkeypatch.setattr("core.data.base.get_engine", lambda: _Eng())


def _req() -> MagicMock:
    req = MagicMock()
    req.app.state.event_bus_redis_ping_ok = None
    req.app.state.event_bus_redis_ping_error = None
    req.app.state.event_bus_kafka_tcp_ok = None
    req.app.state.event_bus_kafka_tcp_error = None
    return req


@pytest.mark.asyncio
async def test_health_ready_inference_redis_strict_503(monkeypatch: pytest.MonkeyPatch):
    _patch_health_ready_db(monkeypatch)
    monkeypatch.setattr(redis_cache_mod, "_redis_cache_client", None)
    monkeypatch.setattr(main_mod.settings, "event_bus_enabled", False)
    monkeypatch.setattr(main_mod.settings, "inference_cache_enabled", True)
    monkeypatch.setattr(main_mod.settings, "inference_cache_redis_url", "redis://127.0.0.1:6379/0")
    monkeypatch.setattr(main_mod.settings, "health_ready_strict_inference_redis", True)

    async def fail_ping(_self):
        return False, "eof"

    monkeypatch.setattr(
        "core.cache.redis_cache.RedisCacheClient.ping_for_health",
        fail_ping,
        raising=True,
    )

    resp = await main_mod.health_ready(_req())
    assert resp.status_code == 503
    body = json.loads(resp.body.decode())
    assert "inference_cache_redis_ping_failed" in (body.get("degraded_reasons") or [])


@pytest.mark.asyncio
async def test_health_ready_inference_redis_degraded_200_when_not_strict(monkeypatch: pytest.MonkeyPatch):
    _patch_health_ready_db(monkeypatch)
    monkeypatch.setattr(redis_cache_mod, "_redis_cache_client", None)
    monkeypatch.setattr(main_mod.settings, "event_bus_enabled", False)
    monkeypatch.setattr(main_mod.settings, "inference_cache_enabled", True)
    monkeypatch.setattr(main_mod.settings, "inference_cache_redis_url", "redis://127.0.0.1:6379/0")
    monkeypatch.setattr(main_mod.settings, "health_ready_strict_inference_redis", False)

    async def fail_ping(_self):
        return False, "down"

    monkeypatch.setattr(
        "core.cache.redis_cache.RedisCacheClient.ping_for_health",
        fail_ping,
        raising=True,
    )

    out = await main_mod.health_ready(_req())
    assert isinstance(out, dict)
    assert out.get("degraded") is True
    assert "inference_cache_redis_ping_failed" in (out.get("degraded_reasons") or [])


@pytest.mark.asyncio
async def test_inference_redis_probe_skipped_when_disabled_non_strict(monkeypatch: pytest.MonkeyPatch):
    _patch_health_ready_db(monkeypatch)
    monkeypatch.setattr(redis_cache_mod, "_redis_cache_client", None)
    monkeypatch.setattr(main_mod.settings, "event_bus_enabled", False)
    monkeypatch.setattr(main_mod.settings, "inference_cache_enabled", True)
    monkeypatch.setattr(main_mod.settings, "inference_cache_redis_url", "redis://127.0.0.1:6379/0")
    monkeypatch.setattr(main_mod.settings, "health_ready_inference_redis_probe_enabled", False)
    monkeypatch.setattr(main_mod.settings, "health_ready_strict_inference_redis", False)

    calls: list[int] = []

    async def ping(_self):
        calls.append(1)
        return True, None

    monkeypatch.setattr(
        "core.cache.redis_cache.RedisCacheClient.ping_for_health",
        ping,
        raising=True,
    )

    out = await main_mod.health_ready(_req())
    assert isinstance(out, dict)
    assert calls == []
    assert "inference_cache_redis_ping_ok" not in out


@pytest.mark.asyncio
async def test_inference_redis_probe_cache_reuses_result(monkeypatch: pytest.MonkeyPatch):
    _patch_health_ready_db(monkeypatch)
    monkeypatch.setattr(redis_cache_mod, "_redis_cache_client", None)
    monkeypatch.setattr(main_mod.settings, "event_bus_enabled", False)
    monkeypatch.setattr(main_mod.settings, "inference_cache_enabled", True)
    monkeypatch.setattr(main_mod.settings, "inference_cache_redis_url", "redis://127.0.0.1:6379/0")
    monkeypatch.setattr(main_mod.settings, "health_ready_strict_inference_redis", False)
    monkeypatch.setattr(main_mod.settings, "health_ready_inference_redis_probe_cache_seconds", 60.0)

    n = 0

    async def ping(_self):
        nonlocal n
        n += 1
        return False, "once"

    monkeypatch.setattr(
        "core.cache.redis_cache.RedisCacheClient.ping_for_health",
        ping,
        raising=True,
    )

    req = _req()
    await main_mod.health_ready(req)
    await main_mod.health_ready(req)
    assert n == 1
    body2 = await main_mod.health_ready(req)
    assert isinstance(body2, dict)
    assert body2.get("inference_cache_redis_ping_ok") is False


@pytest.mark.asyncio
async def test_inference_redis_strict_bypasses_probe_cache(monkeypatch: pytest.MonkeyPatch):
    _patch_health_ready_db(monkeypatch)
    monkeypatch.setattr(redis_cache_mod, "_redis_cache_client", None)
    monkeypatch.setattr(main_mod.settings, "event_bus_enabled", False)
    monkeypatch.setattr(main_mod.settings, "inference_cache_enabled", True)
    monkeypatch.setattr(main_mod.settings, "inference_cache_redis_url", "redis://127.0.0.1:6379/0")
    monkeypatch.setattr(main_mod.settings, "health_ready_strict_inference_redis", True)
    monkeypatch.setattr(main_mod.settings, "health_ready_inference_redis_probe_cache_seconds", 60.0)

    n = 0

    async def ping(_self):
        nonlocal n
        n += 1
        return False, "x"

    monkeypatch.setattr(
        "core.cache.redis_cache.RedisCacheClient.ping_for_health",
        ping,
        raising=True,
    )

    req = _req()
    await main_mod.health_ready(req)
    await main_mod.health_ready(req)
    assert n == 2
