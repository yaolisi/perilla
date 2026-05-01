"""优雅关停期间就绪探针应返回 503，便于 K8s 摘流量。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import main as main_mod

from tests.test_health_ready_event_bus import _patch_health_ready_db


@pytest.mark.asyncio
async def test_health_ready_shutting_down_returns_503_before_db() -> None:
    req = MagicMock()
    req.app.state = SimpleNamespace(shutting_down=True)
    resp = await main_mod.health_ready(req)
    assert resp.status_code == 503
    assert resp.headers.get("retry-after") == "1"
    body = json.loads(resp.body.decode())
    assert body.get("status") == "not_ready"
    assert "application_shutting_down" in (body.get("degraded_reasons") or [])


@pytest.mark.asyncio
async def test_health_ready_magicmock_state_not_treated_as_shutting_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """MagicMock 的 shutting_down 子 mock 不得被当成 True。"""
    _patch_health_ready_db(monkeypatch)
    monkeypatch.setattr(main_mod.settings, "inference_cache_enabled", False)
    monkeypatch.setattr(main_mod.settings, "event_bus_enabled", False)

    req = MagicMock()
    out = await main_mod.health_ready(req)
    assert isinstance(out, dict)
    assert out.get("status") == "ready"


def test_set_application_shutting_down_updates_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    class _M:
        def set_health_ready_shutting_down(self, v: bool) -> None:
            calls.append(v)

    _stub = _M()
    monkeypatch.setattr(
        "core.observability.prometheus_metrics.get_prometheus_business_metrics",
        lambda: _stub,
    )
    app = SimpleNamespace(state=SimpleNamespace())
    main_mod._set_application_shutting_down(app, True)
    assert app.state.shutting_down is True
    assert calls == [True]
    main_mod._set_application_shutting_down(app, False)
    assert app.state.shutting_down is False
    assert calls == [True, False]
