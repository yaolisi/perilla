"""就绪探针：API 限流 Redis。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

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
    req.app.state.api_rate_limit_redis_ping_ok = None
    req.app.state.api_rate_limit_redis_ping_error = None
    return req


@pytest.mark.asyncio
async def test_health_ready_api_rate_limit_redis_strict_503(monkeypatch: pytest.MonkeyPatch):
    _patch_health_ready_db(monkeypatch)
    monkeypatch.setattr(main_mod.settings, "event_bus_enabled", False)
    monkeypatch.setattr(main_mod.settings, "api_rate_limit_redis_url", "redis://127.0.0.1:6379/14")
    monkeypatch.setattr(main_mod.settings, "health_ready_strict_api_rate_limit_redis", True)

    async def boom(_url: str, *, timeout_seconds: float = 2.0) -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr("core.events.redis_ping.probe_redis_url", boom)

    resp = await main_mod.health_ready(_req())
    assert resp.status_code == 503
    body = json.loads(resp.body.decode())
    assert "api_rate_limit_redis_ping_failed" in (body.get("degraded_reasons") or [])


@pytest.mark.asyncio
async def test_health_ready_api_rate_limit_redis_degraded_200_when_not_strict(monkeypatch: pytest.MonkeyPatch):
    _patch_health_ready_db(monkeypatch)
    monkeypatch.setattr(main_mod.settings, "event_bus_enabled", False)
    monkeypatch.setattr(main_mod.settings, "api_rate_limit_redis_url", "redis://127.0.0.1:6379/14")
    monkeypatch.setattr(main_mod.settings, "health_ready_strict_api_rate_limit_redis", False)

    async def boom(_url: str, *, timeout_seconds: float = 2.0) -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr("core.events.redis_ping.probe_redis_url", boom)

    out = await main_mod.health_ready(_req())
    assert isinstance(out, dict)
    assert out.get("degraded") is True
    assert "api_rate_limit_redis_ping_failed" in (out.get("degraded_reasons") or [])


@pytest.mark.asyncio
async def test_health_ready_arl_uses_startup_ping_when_probe_disabled(monkeypatch: pytest.MonkeyPatch):
    _patch_health_ready_db(monkeypatch)
    monkeypatch.setattr(main_mod.settings, "event_bus_enabled", False)
    monkeypatch.setattr(main_mod.settings, "api_rate_limit_redis_url", "redis://127.0.0.1:6379/14")
    monkeypatch.setattr(main_mod.settings, "health_ready_api_rate_limit_redis_probe_enabled", False)
    monkeypatch.setattr(main_mod.settings, "health_ready_strict_api_rate_limit_redis", False)

    calls: list[int] = []

    async def track(_url: str, *, timeout_seconds: float = 2.0) -> None:
        calls.append(1)

    monkeypatch.setattr("core.events.redis_ping.probe_redis_url", track)

    req = _req()
    req.app.state.api_rate_limit_redis_ping_ok = False
    req.app.state.api_rate_limit_redis_ping_error = "startup failed"

    out = await main_mod.health_ready(req)
    assert calls == []
    assert isinstance(out, dict)
    assert "api_rate_limit_redis_ping_failed" in (out.get("degraded_reasons") or [])
