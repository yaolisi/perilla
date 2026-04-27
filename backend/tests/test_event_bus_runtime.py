import pytest
import asyncio

from config.settings import settings
from core.events.bus import (
    CompositeEventBus,
    InProcessEventBus,
    clear_event_bus_dlq,
    get_event_bus_runtime_status,
    replay_event_bus_dlq,
)


@pytest.mark.asyncio
async def test_inprocess_event_bus_publish_subscribe_roundtrip():
    bus = InProcessEventBus()
    got = []

    async def handler(evt):
        await asyncio.sleep(0)
        got.append(evt)

    sub_id = await bus.subscribe("demo.event", handler)
    await bus.publish("demo.event", {"k": "v"}, source="test")
    assert len(got) == 1
    assert got[0]["event_type"] == "demo.event"
    assert got[0]["payload"] == {"k": "v"}
    assert await bus.unsubscribe(sub_id) is True


@pytest.mark.asyncio
async def test_composite_event_bus_subscription_id_and_unsubscribe():
    b1 = InProcessEventBus()
    b2 = InProcessEventBus()
    bus = CompositeEventBus(b1, b2)
    count = {"v": 0}

    async def handler(_evt):
        await asyncio.sleep(0)
        count["v"] += 1

    sub_id = await bus.subscribe("demo.event", handler)
    assert "," in sub_id
    await bus.publish("demo.event", {"ok": True}, source="test")
    assert count["v"] == 2
    assert await bus.unsubscribe(sub_id) is True


@pytest.mark.asyncio
async def test_event_bus_metrics_and_dlq_recording():
    await clear_event_bus_dlq()
    bus = InProcessEventBus()

    async def bad_handler(_evt):
        await asyncio.sleep(0)
        raise RuntimeError("boom")

    await bus.subscribe("bad.event", bad_handler)
    await bus.publish("bad.event", {"x": 1}, source="test")

    status = await get_event_bus_runtime_status()
    assert status["published_total"] >= 1
    assert status["handled_failure_total"] >= 1
    assert status["dlq_size"] >= 1
    assert "bad.event" in status.get("per_event_type", {})


@pytest.mark.asyncio
async def test_event_bus_dlq_filtering():
    await clear_event_bus_dlq()
    bus = InProcessEventBus()

    async def bad_a(_evt):
        raise RuntimeError("err_a")

    async def bad_b(_evt):
        raise RuntimeError("err_b")

    await bus.subscribe("a.event", bad_a)
    await bus.subscribe("b.event", bad_b)
    await bus.publish("a.event", {"a": 1}, source="test")
    await bus.publish("b.event", {"b": 1}, source="test")

    from core.events.bus import get_event_bus_dlq

    only_a = await get_event_bus_dlq(limit=50, event_type="a.event")
    assert len(only_a) >= 1
    assert all(item.get("event_type") == "a.event" for item in only_a if item.get("event_type"))


@pytest.mark.asyncio
async def test_event_bus_dlq_replay():
    import core.events.bus as bus_module

    bus_module._last_replay_ts_ms = 0
    await clear_event_bus_dlq()
    bus = InProcessEventBus()
    got = []

    async def bad_handler(_evt):
        raise RuntimeError("err_replay")

    async def ok_handler(evt):
        await asyncio.sleep(0)
        got.append(evt)

    await bus.subscribe("replay.event", bad_handler)
    await bus.publish("replay.event", {"x": 1}, source="test")

    # 使用全局总线注册目标 handler，以便 replay 能命中
    from core.events import get_event_bus

    sub_id = await get_event_bus().subscribe("replay.event", ok_handler)
    try:
        result = await replay_event_bus_dlq(event_type="replay.event", limit=10)
        assert result["replayed"] >= 1
        assert result["failed"] == 0
        assert len(got) >= 1
        assert got[-1]["payload"].get("_event_meta", {}).get("replayed_from_dlq") is True
    finally:
        await get_event_bus().unsubscribe(sub_id)


@pytest.mark.asyncio
async def test_event_bus_dlq_replay_respects_rate_limit():
    import core.events.bus as bus_module

    bus_module._last_replay_ts_ms = 0
    await clear_event_bus_dlq()
    bus = InProcessEventBus()

    async def bad_handler(_evt):
        raise RuntimeError("err_rate")

    await bus.subscribe("rate.event", bad_handler)
    await bus.publish("rate.event", {"x": 1}, source="test")

    old_min_interval = settings.event_bus_replay_min_interval_ms
    try:
        settings.event_bus_replay_min_interval_ms = 10_000
        first = await replay_event_bus_dlq(event_type="rate.event", limit=1)
        assert first["replayed"] >= 1
        with pytest.raises(RuntimeError):
            await replay_event_bus_dlq(event_type="rate.event", limit=1)
    finally:
        settings.event_bus_replay_min_interval_ms = old_min_interval


@pytest.mark.asyncio
async def test_event_bus_dlq_replay_dry_run_with_grouped_stats():
    import core.events.bus as bus_module
    from core.events.bus import get_event_bus_dlq

    bus_module._last_replay_ts_ms = 0
    await clear_event_bus_dlq()
    bus = InProcessEventBus()

    async def bad_a(_evt):
        raise RuntimeError("dry_a")

    async def bad_b(_evt):
        raise RuntimeError("dry_b")

    await bus.subscribe("dry.a", bad_a)
    await bus.subscribe("dry.b", bad_b)
    await bus.publish("dry.a", {"a": 1}, source="test")
    await bus.publish("dry.b", {"b": 1}, source="test")

    before = await get_event_bus_dlq(limit=100)
    result = await replay_event_bus_dlq(limit=100, dry_run=True)
    after = await get_event_bus_dlq(limit=100)

    assert result["dry_run"] is True
    assert result["candidate"] >= 2
    assert result["replayed"] == 0
    assert "dry.a" in result["grouped"]
    assert "dry.b" in result["grouped"]
    assert len(after) == len(before)

    status = await get_event_bus_runtime_status()
    assert status.get("replay_dry_run_total", 0) >= 1
