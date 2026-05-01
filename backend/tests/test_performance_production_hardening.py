"""生产级性能相关单元测试：调度并发、量化辅助、Kafka topic 命名。"""

from __future__ import annotations

from unittest.mock import MagicMock


def test_scheduler_max_concurrency_clamped_and_setter() -> None:
    from execution_kernel.engine.scheduler import Scheduler

    db = MagicMock()
    sm = MagicMock()
    ex = MagicMock()
    s = Scheduler(db, sm, ex, max_concurrency=999)
    assert s._max_concurrency == 256
    s.set_max_concurrency(0)
    assert s._max_concurrency == 1
    s.set_max_concurrency(48)
    assert s._max_concurrency == 48


def test_try_bitsandbytes_non_cuda_skips() -> None:
    from core.runtimes.torch.bnb_quant import try_bitsandbytes_config

    cfg, use_dm = try_bitsandbytes_config({"load_in_4bit": True}, resolved_device="mps")
    assert cfg is None and use_dm is False


def test_kafka_event_bus_topic_sanitized() -> None:
    from core.events.kafka_bus import KafkaEventBus

    bus = KafkaEventBus(
        bootstrap_servers="localhost:9092",
        topic_prefix="perilla.events",
        consumer_group="g",
    )
    assert "hello_world" in bus._topic("hello world")
    assert bus._topic("ok.evt").startswith("perilla.events.")


def test_composite_event_bus_lists_backend_kinds() -> None:
    from core.events.bus import CompositeEventBus, InProcessEventBus

    c = CompositeEventBus(InProcessEventBus())
    assert c.list_backend_kinds() == ["inprocess"]


def test_workflow_scheduler_gauge_updates_from_runtime_settings(monkeypatch) -> None:
    from core.system import runtime_settings as rs

    recorded: list[int] = []

    class FakeMetrics:
        def set_workflow_scheduler_platform_max_concurrency(self, n: int) -> None:
            recorded.append(int(n))

    monkeypatch.setattr("core.observability.get_prometheus_business_metrics", lambda: FakeMetrics())
    monkeypatch.setattr(rs.settings, "workflow_scheduler_max_concurrency", 17)
    store = rs.get_system_settings_store()
    monkeypatch.setattr(store, "get_setting", lambda _k: None)

    cap = rs.get_workflow_scheduler_max_concurrency()
    assert cap == 17
    assert recorded == [17]
