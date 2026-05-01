"""
可选 Kafka 事件总线（高吞吐、跨进程）

依赖: pip install aiokafka
配置: EVENT_BUS_BACKEND=kafka 且 EVENT_BUS_KAFKA_BOOTSTRAP_SERVERS 非空
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import suppress
from typing import Any, Awaitable, Callable, Dict, Optional

from log import logger

from core.events.bus import EventBus

EventHandler = Callable[[Dict[str, Any]], Awaitable[None]]


class KafkaEventBus(EventBus):
    """基于 Kafka 的 publish/subscribe；与 Redis 版语义对齐（跳过本实例发出的副本）。"""

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        topic_prefix: str,
        consumer_group: str,
    ) -> None:
        self._bootstrap = (bootstrap_servers or "").strip()
        self._prefix = (topic_prefix or "perilla.events").strip().rstrip(".")
        self._group = (consumer_group or "perilla-event-bus").strip()
        self._instance_id = f"bus_{uuid.uuid4().hex[:12]}"
        self._producer = None
        self._consumer = None
        self._subscriptions: Dict[str, tuple[str, EventHandler]] = {}
        self._lock = asyncio.Lock()
        self._listen_task: Optional[asyncio.Task[None]] = None
        self._last_topics: Optional[frozenset[str]] = None

    def _topic(self, event_type: str) -> str:
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in event_type)
        name = f"{self._prefix}.{safe}"
        return name[:249]

    async def _producer_or_none(self) -> Any | None:
        if self._producer is not None:
            return self._producer
        try:
            from aiokafka import AIOKafkaProducer
        except Exception as exc:
            logger.warning("[EventBus] aiokafka not installed: %s", exc)
            return None
        try:
            prod = AIOKafkaProducer(bootstrap_servers=self._bootstrap)
            await prod.start()
            self._producer = prod
            return prod
        except Exception as exc:
            logger.warning("[EventBus] kafka producer start failed: %s", exc)
            return None

    async def start(self) -> None:
        if self._listen_task is None or self._listen_task.done():
            self._listen_task = asyncio.create_task(self._listen_loop(), name="kafka-event-bus-listener")

    async def stop(self) -> None:
        if self._listen_task is not None:
            self._listen_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._listen_task
            self._listen_task = None
        if self._consumer is not None:
            with suppress(Exception):
                await self._consumer.stop()
            self._consumer = None
        if self._producer is not None:
            with suppress(Exception):
                await self._producer.stop()
            self._producer = None

    def _needed_topics(self) -> frozenset[str]:
        return frozenset(self._topic(evt) for evt, _ in self._subscriptions.values())

    async def _listen_loop(self) -> None:
        try:
            from aiokafka import AIOKafkaConsumer
        except Exception as exc:
            logger.warning("[EventBus] kafka consumer unavailable: %s", exc)
            return

        consumer = AIOKafkaConsumer(
            bootstrap_servers=self._bootstrap,
            group_id=self._group,
            enable_auto_commit=True,
            auto_offset_reset="latest",
        )
        await consumer.start()
        self._consumer = consumer
        try:
            while True:
                topics = self._needed_topics()
                if not topics:
                    await asyncio.sleep(0.2)
                    continue
                if topics != self._last_topics:
                    await consumer.subscribe(list(topics))
                    self._last_topics = topics
                try:
                    result = await consumer.getmany(timeout_ms=800, max_records=64)
                except Exception as exc:
                    logger.warning("[EventBus] kafka getmany failed: %s", exc)
                    await asyncio.sleep(0.5)
                    continue
                for _tp, records in result.items():
                    for rec in records:
                        await self._handle_record(rec.value)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[EventBus] kafka listener loop failed: %s", exc)
        finally:
            with suppress(Exception):
                await consumer.stop()
            self._consumer = None

    async def _handle_record(self, raw: Any) -> None:
        if not raw:
            return
        try:
            if isinstance(raw, bytes):
                text = raw.decode("utf-8", errors="ignore")
            else:
                text = str(raw)
            envelope = json.loads(text)
            if envelope.get("bus_instance_id") == self._instance_id:
                return
            event_type = str(envelope.get("event_type") or "").strip()
            if not event_type:
                return
            targets = [h for evt, h in self._subscriptions.values() if evt == event_type]
            from core.events.bus import _run_handler_with_retry

            for handler in targets:
                await _run_handler_with_retry(handler, envelope, event_type)
        except Exception as exc:
            logger.warning("[EventBus] invalid kafka event payload: %s", exc)

    async def publish(self, event_type: str, payload: Dict[str, Any], source: str = "system") -> None:
        from core.events.bus import _observe_event_bus_transport, _record_publish_metric

        t0 = time.perf_counter()
        await _record_publish_metric(event_type)
        prod = await self._producer_or_none()
        if prod is None:
            _observe_event_bus_transport("kafka", t0)
            return
        envelope = {
            "event_id": f"evt_{uuid.uuid4().hex[:16]}",
            "event_type": event_type,
            "source": source,
            "ts": int(time.time() * 1000),
            "schema_version": 1,
            "payload": payload,
            "bus_instance_id": self._instance_id,
        }
        try:
            topic = self._topic(event_type)
            await prod.send_and_wait(
                topic,
                json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
            )
        except Exception as exc:
            logger.warning("[EventBus] kafka publish failed for %s: %s", event_type, exc)
        finally:
            _observe_event_bus_transport("kafka", t0)

    async def subscribe(self, event_type: str, handler: EventHandler) -> str:
        subscription_id = f"sub_{uuid.uuid4().hex[:16]}"
        async with self._lock:
            self._subscriptions[subscription_id] = (event_type, handler)
        await self.start()
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        async with self._lock:
            return self._subscriptions.pop(subscription_id, None) is not None
