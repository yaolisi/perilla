"""Kafka bootstrap TCP 探测单元测试。"""

from __future__ import annotations

import asyncio

import pytest

from core.events import kafka_ping


def test_parse_kafka_broker_host_port_plain():
    assert kafka_ping.parse_kafka_broker_host_port("broker:9092") == ("broker", 9092)


def test_parse_kafka_broker_host_port_scheme():
    assert kafka_ping.parse_kafka_broker_host_port("PLAINTEXT://broker:9092") == ("broker", 9092)


def test_parse_kafka_broker_host_port_ipv6():
    assert kafka_ping.parse_kafka_broker_host_port("[::1]:9092") == ("::1", 9092)


@pytest.mark.asyncio
async def test_probe_kafka_bootstrap_tcp_success():
    class FakeWriter:
        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def fake_connector(_host: str, _port: int):
        await asyncio.sleep(0)
        return None, FakeWriter()

    kafka_ping.set_kafka_tcp_connector_for_testing(fake_connector)
    try:
        await kafka_ping.probe_kafka_bootstrap_tcp("127.0.0.1:9092", timeout_seconds=1.0)
    finally:
        kafka_ping.set_kafka_tcp_connector_for_testing(None)


@pytest.mark.asyncio
async def test_probe_kafka_bootstrap_tcp_all_fail():
    async def failing_connector(_host: str, _port: int):
        await asyncio.sleep(0)
        raise ConnectionRefusedError("nope")

    kafka_ping.set_kafka_tcp_connector_for_testing(failing_connector)
    try:
        with pytest.raises(OSError, match="no reachable kafka broker"):
            await kafka_ping.probe_kafka_bootstrap_tcp("127.0.0.1:9092", timeout_seconds=0.2)
    finally:
        kafka_ping.set_kafka_tcp_connector_for_testing(None)


@pytest.mark.asyncio
async def test_probe_kafka_bootstrap_tcp_empty():
    with pytest.raises(ValueError, match="empty kafka bootstrap"):
        await kafka_ping.probe_kafka_bootstrap_tcp("", timeout_seconds=0.2)


@pytest.mark.asyncio
async def test_probe_event_bus_kafka_if_configured_skips_when_backend_redis(monkeypatch):
    import main as main_mod

    monkeypatch.setattr(main_mod.settings, "event_bus_enabled", True)
    monkeypatch.setattr(main_mod.settings, "event_bus_backend", "redis")
    ok, err = await main_mod._probe_event_bus_kafka_if_configured()
    assert ok is None and err is None


@pytest.mark.asyncio
async def test_probe_event_bus_kafka_if_configured_strict_raises(monkeypatch):
    import main as main_mod

    monkeypatch.setattr(main_mod.settings, "event_bus_enabled", True)
    monkeypatch.setattr(main_mod.settings, "event_bus_backend", "kafka")
    monkeypatch.setattr(main_mod.settings, "event_bus_kafka_bootstrap_servers", "127.0.0.1:1")
    monkeypatch.setattr(main_mod.settings, "event_bus_strict_startup", True)
    monkeypatch.setattr(main_mod.settings, "event_bus_kafka_ping_timeout_seconds", 0.2)

    async def failing_connector(_host: str, _port: int):
        await asyncio.sleep(0)
        raise ConnectionRefusedError("refused")

    kafka_ping.set_kafka_tcp_connector_for_testing(failing_connector)
    try:
        with pytest.raises(RuntimeError, match="Kafka bootstrap TCP"):
            await main_mod._probe_event_bus_kafka_if_configured()
    finally:
        kafka_ping.set_kafka_tcp_connector_for_testing(None)
