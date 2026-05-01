"""就绪探针事件总线降级语义单元测试。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

import main as main_mod


def test_event_bus_degraded_reasons_disabled():
    assert (
        main_mod._event_bus_degraded_reasons(
            event_bus_enabled=False,
            intended_backend="kafka",
            redis_ping_ok=False,
            kafka_tcp_ok=False,
            bus_backends=["kafka"],
        )
        == []
    )


def test_event_bus_degraded_redis_ping_failed():
    assert main_mod._event_bus_degraded_reasons(
        event_bus_enabled=True,
        intended_backend="redis",
        redis_ping_ok=False,
        kafka_tcp_ok=None,
        bus_backends=["redis"],
    ) == ["event_bus_redis_ping_failed"]


def test_event_bus_degraded_redis_not_attached():
    assert main_mod._event_bus_degraded_reasons(
        event_bus_enabled=True,
        intended_backend="redis",
        redis_ping_ok=True,
        kafka_tcp_ok=None,
        bus_backends=["memory"],
    ) == ["event_bus_redis_not_attached"]


def test_event_bus_degraded_kafka_tcp_and_not_attached():
    r = main_mod._event_bus_degraded_reasons(
        event_bus_enabled=True,
        intended_backend="kafka",
        redis_ping_ok=None,
        kafka_tcp_ok=False,
        bus_backends=["redis"],
    )
    assert "event_bus_kafka_tcp_failed" in r
    assert "event_bus_kafka_not_attached" in r
    assert len(r) == 2


def test_event_bus_degraded_inprocess_backend_no_cross_process_codes():
    assert (
        main_mod._event_bus_degraded_reasons(
            event_bus_enabled=True,
            intended_backend="inprocess",
            redis_ping_ok=None,
            kafka_tcp_ok=None,
            bus_backends=["Something"],
        )
        == []
    )


def test_log_event_bus_degraded_transition_only_logs_on_change(monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    infos: list[tuple[str, tuple[object, ...]]] = []

    def _capture_info(msg: str, *args: object) -> None:
        infos.append((msg, args))

    monkeypatch.setattr(main_mod.logger, "info", _capture_info)

    app = SimpleNamespace(state=SimpleNamespace())
    main_mod._log_event_bus_degraded_transition(app, [])
    assert infos == []
    main_mod._log_event_bus_degraded_transition(app, ["event_bus_redis_ping_failed"])
    assert len(infos) == 1
    main_mod._log_event_bus_degraded_transition(app, ["event_bus_redis_ping_failed"])
    assert len(infos) == 1
    main_mod._log_event_bus_degraded_transition(app, [])
    assert len(infos) == 2


def test_prometheus_set_health_ready_event_bus_degraded_smoke():
    from core.observability.prometheus_metrics import get_prometheus_business_metrics

    m = get_prometheus_business_metrics()
    m.set_health_ready_event_bus_degraded(True)
    m.set_health_ready_event_bus_degraded(False)
    m.set_health_ready_inference_cache_redis_degraded(True)
    m.set_health_ready_inference_cache_redis_degraded(False)


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


def _health_ready_request_mock() -> MagicMock:
    req = MagicMock()
    req.app.state.event_bus_redis_ping_ok = False
    req.app.state.event_bus_redis_ping_error = "down"
    req.app.state.event_bus_kafka_tcp_ok = None
    req.app.state.event_bus_kafka_tcp_error = None
    return req


@pytest.mark.asyncio
async def test_health_ready_event_bus_degraded_200_when_not_strict(monkeypatch: pytest.MonkeyPatch):
    _patch_health_ready_db(monkeypatch)
    monkeypatch.setattr(main_mod.settings, "inference_cache_enabled", False)

    async def fake_eb_status():
        return {"bus_backends": ["redis"], "dlq_size": 0}

    monkeypatch.setattr(main_mod.settings, "health_ready_strict_event_bus", False)
    monkeypatch.setattr(main_mod.settings, "event_bus_enabled", True)
    monkeypatch.setattr(main_mod.settings, "event_bus_backend", "redis")
    monkeypatch.setattr("core.events.bus.get_event_bus_runtime_status", fake_eb_status)

    out = await main_mod.health_ready(_health_ready_request_mock())
    assert isinstance(out, dict)
    assert out.get("status") == "ready"
    assert out.get("degraded") is True
    assert "event_bus_redis_ping_failed" in (out.get("degraded_reasons") or [])


@pytest.mark.asyncio
async def test_resolve_event_bus_ready_snapshot_aligns_with_degraded_reasons(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main_mod.settings, "event_bus_enabled", True)
    monkeypatch.setattr(main_mod.settings, "event_bus_backend", "redis")

    async def fake_eb_status():
        return {"bus_backends": ["redis"], "dlq_size": 0}

    monkeypatch.setattr("core.events.bus.get_event_bus_runtime_status", fake_eb_status)

    app = MagicMock()
    app.state.event_bus_redis_ping_ok = False
    app.state.event_bus_redis_ping_error = "down"
    app.state.event_bus_kafka_tcp_ok = None
    app.state.event_bus_kafka_tcp_error = None

    bb_list, reasons = await main_mod._resolve_event_bus_ready_snapshot(app)
    assert bb_list == ["redis"]
    assert reasons == ["event_bus_redis_ping_failed"]


async def test_health_ready_strict_event_bus_returns_503(monkeypatch: pytest.MonkeyPatch):
    _patch_health_ready_db(monkeypatch)
    monkeypatch.setattr(main_mod.settings, "inference_cache_enabled", False)

    async def fake_eb_status():
        return {"bus_backends": ["redis"], "dlq_size": 0}

    monkeypatch.setattr(main_mod.settings, "health_ready_strict_event_bus", True)
    monkeypatch.setattr(main_mod.settings, "event_bus_enabled", True)
    monkeypatch.setattr(main_mod.settings, "event_bus_backend", "redis")
    monkeypatch.setattr("core.events.bus.get_event_bus_runtime_status", fake_eb_status)

    resp = await main_mod.health_ready(_health_ready_request_mock())
    assert resp.status_code == 503
    assert resp.headers.get("retry-after") == "5"
    body = json.loads(resp.body.decode())
    assert body.get("degraded") is True
