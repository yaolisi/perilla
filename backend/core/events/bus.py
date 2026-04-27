from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, Optional

from config.settings import settings
from log import logger


EventHandler = Callable[[Dict[str, Any]], Awaitable[None]]


class EventBus(ABC):
    async def start(self) -> None:
        return

    async def stop(self) -> None:
        return

    @abstractmethod
    async def publish(self, event_type: str, payload: Dict[str, Any], source: str = "system") -> None:
        raise NotImplementedError

    @abstractmethod
    async def subscribe(self, event_type: str, handler: EventHandler) -> str:
        raise NotImplementedError

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> bool:
        raise NotImplementedError


class InProcessEventBus(EventBus):
    def __init__(self) -> None:
        self._handlers: Dict[str, Dict[str, EventHandler]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, event_type: str, payload: Dict[str, Any], source: str = "system") -> None:
        await _record_publish_metric(event_type)
        envelope = {
            "event_id": f"evt_{uuid.uuid4().hex[:16]}",
            "event_type": event_type,
            "source": source,
            "ts": int(time.time() * 1000),
            "schema_version": 1,
            "payload": payload,
        }
        handlers = list(self._handlers.get(event_type, {}).values())
        for handler in handlers:
            await _run_handler_with_retry(handler, envelope, event_type)

    async def subscribe(self, event_type: str, handler: EventHandler) -> str:
        subscription_id = f"sub_{uuid.uuid4().hex[:16]}"
        async with self._lock:
            self._handlers.setdefault(event_type, {})[subscription_id] = handler
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        async with self._lock:
            for _, handlers in self._handlers.items():
                if subscription_id in handlers:
                    handlers.pop(subscription_id, None)
                    return True
        return False


class RedisEventBus(EventBus):
    def __init__(self, redis_url: str, channel_prefix: str) -> None:
        self._redis_url = redis_url
        self._channel_prefix = channel_prefix
        self._client = None
        self._subscriptions: Dict[str, tuple[str, EventHandler]] = {}
        self._lock = asyncio.Lock()
        self._instance_id = f"bus_{uuid.uuid4().hex[:12]}"
        self._listen_task: Optional[asyncio.Task] = None

    def _client_or_none(self):
        if self._client is not None:
            return self._client
        try:
            from redis.asyncio import Redis  # type: ignore[import-untyped]

            self._client = Redis.from_url(self._redis_url, decode_responses=True)
            return self._client
        except Exception as exc:
            logger.warning("[EventBus] redis unavailable, skip redis event bus: %s", exc)
            return None

    def _channel(self, event_type: str) -> str:
        return f"{self._channel_prefix}:{event_type}"

    async def start(self) -> None:
        client = self._client_or_none()
        if client is None:
            return
        if self._listen_task is None or self._listen_task.done():
            self._listen_task = asyncio.create_task(self._listen_loop(), name="redis-event-bus-listener")

    async def stop(self) -> None:
        if self._listen_task is not None:
            self._listen_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._listen_task
            self._listen_task = None

    async def _listen_loop(self) -> None:
        client = self._client_or_none()
        if client is None:
            return
        pubsub = client.pubsub()
        try:
            while True:
                channels = self._subscribed_channels()
                if channels:
                    await pubsub.subscribe(*channels)
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    await self._handle_message(message.get("data"))
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[EventBus] redis listener loop failed: %s", exc)
        finally:
            try:
                await pubsub.close()
            except Exception:
                pass

    def _subscribed_channels(self) -> list[str]:
        event_types = {event_type for event_type, _handler in self._subscriptions.values()}
        return [self._channel(evt) for evt in sorted(event_types)]

    async def _handle_message(self, data: Any) -> None:
        if not data:
            return
        try:
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="ignore")
            envelope = json.loads(str(data))
            if envelope.get("bus_instance_id") == self._instance_id:
                return
            event_type = str(envelope.get("event_type") or "").strip()
            if not event_type:
                return
            targets = [handler for evt, handler in self._subscriptions.values() if evt == event_type]
            for handler in targets:
                await _run_handler_with_retry(handler, envelope, event_type)
        except Exception as exc:
            logger.warning("[EventBus] invalid redis event message: %s", exc)

    async def publish(self, event_type: str, payload: Dict[str, Any], source: str = "system") -> None:
        await _record_publish_metric(event_type)
        client = self._client_or_none()
        if client is None:
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
            await client.publish(self._channel(event_type), json.dumps(envelope, ensure_ascii=False))
        except Exception as exc:
            logger.warning("[EventBus] redis publish failed for %s: %s", event_type, exc)

    async def subscribe(self, event_type: str, handler: EventHandler) -> str:
        # 当前阶段仅保证统一接口，跨进程消费由后续 worker 接入
        subscription_id = f"sub_{uuid.uuid4().hex[:16]}"
        async with self._lock:
            self._subscriptions[subscription_id] = (event_type, handler)
        await self.start()
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        async with self._lock:
            return self._subscriptions.pop(subscription_id, None) is not None


class CompositeEventBus(EventBus):
    def __init__(self, *buses: EventBus) -> None:
        self._buses = buses

    async def publish(self, event_type: str, payload: Dict[str, Any], source: str = "system") -> None:
        for bus in self._buses:
            try:
                await bus.publish(event_type, payload, source=source)
            except Exception as exc:
                logger.warning("[EventBus] composite publish failed for %s: %s", event_type, exc)

    async def start(self) -> None:
        for bus in self._buses:
            try:
                await bus.start()
            except Exception as exc:
                logger.warning("[EventBus] composite start failed: %s", exc)

    async def stop(self) -> None:
        for bus in self._buses:
            try:
                await bus.stop()
            except Exception as exc:
                logger.warning("[EventBus] composite stop failed: %s", exc)

    async def subscribe(self, event_type: str, handler: EventHandler) -> str:
        if not self._buses:
            raise RuntimeError("No event bus configured")
        subscriptions: list[str] = []
        for bus in self._buses:
            sub_id = await bus.subscribe(event_type, handler)
            subscriptions.append(sub_id)
        return ",".join(subscriptions)

    async def unsubscribe(self, subscription_id: str) -> bool:
        ok = False
        sub_ids = [x.strip() for x in (subscription_id or "").split(",") if x.strip()]
        if not sub_ids:
            sub_ids = [subscription_id]
        for bus in self._buses:
            for sub_id in sub_ids:
                ok = await bus.unsubscribe(sub_id) or ok
        return ok


_event_bus: Optional[EventBus] = None
_event_bus_metrics: Dict[str, Any] = {
    "published_total": 0,
    "handled_success_total": 0,
    "handled_failure_total": 0,
    "replay_attempts_total": 0,
    "replay_dry_run_total": 0,
    "replay_rate_limited_total": 0,
    "replay_replayed_total": 0,
    "replay_failed_total": 0,
    "last_error": "",
    "per_event_type": {},
}
_event_bus_dlq: list[Dict[str, Any]] = []
_metrics_lock = asyncio.Lock()
_replay_lock = asyncio.Lock()
_last_replay_ts_ms = 0


def _event_type_metrics(event_type: str) -> Dict[str, Any]:
    per = _event_bus_metrics.setdefault("per_event_type", {})
    if event_type not in per:
        per[event_type] = {
            "published": 0,
            "handled_success": 0,
            "handled_failure": 0,
            "avg_handle_ms": 0.0,
            "last_lag_ms": 0,
        }
    return per[event_type]


async def _record_publish_metric(event_type: str) -> None:
    async with _metrics_lock:
        _event_bus_metrics["published_total"] = int(_event_bus_metrics.get("published_total", 0)) + 1
        etm = _event_type_metrics(event_type)
        etm["published"] = int(etm.get("published", 0)) + 1


async def _record_replay_metric(
    *,
    dry_run: bool,
    rate_limited: bool,
    replayed: int = 0,
    failed: int = 0,
) -> None:
    async with _metrics_lock:
        _event_bus_metrics["replay_attempts_total"] = int(_event_bus_metrics.get("replay_attempts_total", 0)) + 1
        if dry_run:
            _event_bus_metrics["replay_dry_run_total"] = int(_event_bus_metrics.get("replay_dry_run_total", 0)) + 1
        if rate_limited:
            _event_bus_metrics["replay_rate_limited_total"] = int(_event_bus_metrics.get("replay_rate_limited_total", 0)) + 1
        if replayed > 0:
            _event_bus_metrics["replay_replayed_total"] = int(_event_bus_metrics.get("replay_replayed_total", 0)) + int(replayed)
        if failed > 0:
            _event_bus_metrics["replay_failed_total"] = int(_event_bus_metrics.get("replay_failed_total", 0)) + int(failed)


async def _record_handle_metric(event_type: str, *, success: bool, handle_ms: float, lag_ms: int, error: str = "") -> None:
    async with _metrics_lock:
        etm = _event_type_metrics(event_type)
        if success:
            _event_bus_metrics["handled_success_total"] = int(_event_bus_metrics.get("handled_success_total", 0)) + 1
            etm["handled_success"] = int(etm.get("handled_success", 0)) + 1
        else:
            _event_bus_metrics["handled_failure_total"] = int(_event_bus_metrics.get("handled_failure_total", 0)) + 1
            etm["handled_failure"] = int(etm.get("handled_failure", 0)) + 1
            _event_bus_metrics["last_error"] = error
        success_count = int(etm.get("handled_success", 0))
        if success and success_count > 0:
            prev_avg = float(etm.get("avg_handle_ms", 0.0))
            etm["avg_handle_ms"] = round(((prev_avg * (success_count - 1)) + handle_ms) / success_count, 3)
        etm["last_lag_ms"] = int(lag_ms)


async def _push_dlq(event_type: str, envelope: Dict[str, Any], error: str) -> None:
    max_items = max(1, int(getattr(settings, "event_bus_dlq_max_items", 200) or 200))
    item = {
        "event_type": event_type,
        "error": error[:512],
        "ts": int(time.time() * 1000),
        "envelope": envelope,
    }
    async with _metrics_lock:
        _event_bus_dlq.append(item)
        if len(_event_bus_dlq) > max_items:
            overflow = len(_event_bus_dlq) - max_items
            if overflow > 0:
                del _event_bus_dlq[0:overflow]
    await _persist_dlq(item)


async def _persist_dlq(item: Dict[str, Any]) -> None:
    def _write() -> None:
        try:
            from core.data.base import db_session
            from core.data.models.event_dlq import EventDlqORM

            envelope = item.get("envelope", {}) or {}
            with db_session() as db:
                row = EventDlqORM(
                    event_id=str(envelope.get("event_id") or f"evt_{uuid.uuid4().hex[:16]}"),
                    event_type=str(item.get("event_type") or "unknown"),
                    error=str(item.get("error") or "unknown")[:512],
                    envelope_json=json.dumps(envelope, ensure_ascii=False),
                )
                db.add(row)
        except Exception as exc:
            logger.warning("[EventBus] persist dlq failed: %s", exc)

    await asyncio.to_thread(_write)


async def get_event_bus_runtime_status() -> Dict[str, Any]:
    async with _metrics_lock:
        return {
            **_event_bus_metrics,
            "dlq_size": len(_event_bus_dlq),
        }


async def get_event_bus_dlq(
    limit: int = 50,
    event_type: Optional[str] = None,
    since_ts: Optional[int] = None,
) -> list[Dict[str, Any]]:
    safe_limit = max(1, min(200, int(limit)))
    in_memory: list[Dict[str, Any]]
    async with _metrics_lock:
        in_memory = list(_event_bus_dlq)
    if event_type:
        in_memory = [x for x in in_memory if x.get("event_type") == event_type]
    if since_ts is not None:
        in_memory = [x for x in in_memory if int(x.get("ts", 0)) >= int(since_ts)]
    in_memory = in_memory[-safe_limit:]

    persisted = await _load_persisted_dlq(limit=safe_limit, event_type=event_type, since_ts=since_ts)
    merged = persisted + in_memory
    if len(merged) <= safe_limit:
        return merged
    return merged[-safe_limit:]


async def _load_persisted_dlq(
    *,
    limit: int,
    event_type: Optional[str],
    since_ts: Optional[int],
) -> list[Dict[str, Any]]:
    def _read() -> list[Dict[str, Any]]:
        try:
            from datetime import UTC, datetime

            from core.data.base import db_session
            from core.data.models.event_dlq import EventDlqORM

            with db_session() as db:
                query = db.query(EventDlqORM).order_by(EventDlqORM.id.desc())
                if event_type:
                    query = query.filter(EventDlqORM.event_type == event_type)
                if since_ts is not None:
                    dt = datetime.fromtimestamp(float(since_ts) / 1000.0, tz=UTC)
                    query = query.filter(EventDlqORM.created_at >= dt)
                rows = query.limit(limit).all()
                out: list[Dict[str, Any]] = []
                for row in reversed(rows):
                    try:
                        envelope = json.loads(row.envelope_json or "{}")
                    except Exception:
                        envelope = {}
                    out.append(
                        {
                            "event_type": row.event_type,
                            "error": row.error,
                            "ts": int((row.created_at.timestamp() if row.created_at else 0) * 1000),
                            "envelope": envelope,
                            "persisted": True,
                        }
                    )
                return out
        except Exception:
            return []

    return await asyncio.to_thread(_read)


async def clear_event_bus_dlq() -> int:
    async with _metrics_lock:
        n = len(_event_bus_dlq)
        _event_bus_dlq.clear()
    persisted = await _clear_persisted_dlq()
    return n + persisted


async def _clear_persisted_dlq() -> int:
    def _clear() -> int:
        try:
            from core.data.base import db_session
            from core.data.models.event_dlq import EventDlqORM

            with db_session() as db:
                deleted = db.query(EventDlqORM).delete(synchronize_session=False)
            return int(deleted or 0)
        except Exception:
            return 0

    return await asyncio.to_thread(_clear)


async def replay_event_bus_dlq(
    *,
    event_type: Optional[str] = None,
    since_ts: Optional[int] = None,
    limit: int = 20,
    dry_run: bool = False,
) -> Dict[str, Any]:
    safe_limit = _safe_replay_limit(limit)
    entries = await get_event_bus_dlq(limit=safe_limit, event_type=event_type, since_ts=since_ts)
    grouped: Dict[str, Dict[str, int]] = {}
    for item in entries:
        evt = str(item.get("event_type") or "unknown")
        grouped.setdefault(evt, {"total": 0, "replayed": 0, "failed": 0})
        grouped[evt]["total"] += 1

    if dry_run:
        await _record_replay_metric(dry_run=True, rate_limited=False, replayed=0, failed=0)
        return {
            "dry_run": True,
            "candidate": len(entries),
            "replayed": 0,
            "failed": 0,
            "grouped": grouped,
        }

    try:
        await _ensure_replay_window()
    except RuntimeError:
        await _record_replay_metric(dry_run=False, rate_limited=True, replayed=0, failed=0)
        raise

    replayed = 0
    failed = 0
    bus = get_event_bus()
    for item in entries:
        publish_args = _build_replay_publish_args(item)
        if publish_args is None:
            failed += 1
            evt = str(item.get("event_type") or "unknown")
            grouped.setdefault(evt, {"total": 0, "replayed": 0, "failed": 0})
            grouped[evt]["failed"] += 1
            continue
        try:
            replay_event_type, replay_payload, source = publish_args
            await bus.publish(replay_event_type, replay_payload, source=source)
            replayed += 1
            grouped.setdefault(replay_event_type, {"total": 0, "replayed": 0, "failed": 0})
            grouped[replay_event_type]["replayed"] += 1
        except Exception:
            failed += 1
            replay_event_type = publish_args[0]
            grouped.setdefault(replay_event_type, {"total": 0, "replayed": 0, "failed": 0})
            grouped[replay_event_type]["failed"] += 1
    await _record_replay_metric(dry_run=False, rate_limited=False, replayed=replayed, failed=failed)
    return {
        "dry_run": False,
        "candidate": len(entries),
        "replayed": replayed,
        "failed": failed,
        "grouped": grouped,
    }


def _safe_replay_limit(limit: int) -> int:
    max_batch = max(1, int(getattr(settings, "event_bus_replay_max_batch", 100) or 100))
    return max(1, min(int(limit), max_batch))


async def _ensure_replay_window() -> None:
    global _last_replay_ts_ms
    min_interval_ms = max(0, int(getattr(settings, "event_bus_replay_min_interval_ms", 1000) or 0))
    async with _replay_lock:
        now_ms = int(time.time() * 1000)
        if min_interval_ms > 0 and (_last_replay_ts_ms > 0) and (now_ms - _last_replay_ts_ms < min_interval_ms):
            raise RuntimeError("event bus replay is rate limited by min interval")
        _last_replay_ts_ms = now_ms


def _build_replay_publish_args(item: Any) -> Optional[tuple[str, Dict[str, Any], str]]:
    if not isinstance(item, dict):
        return None
    envelope = item.get("envelope", {}) if isinstance(item.get("envelope", {}), dict) else {}
    replay_event_type = str(envelope.get("event_type") or item.get("event_type") or "").strip()
    if not replay_event_type:
        return None
    payload = envelope.get("payload", {}) if isinstance(envelope, dict) else {}
    replay_payload = payload if isinstance(payload, dict) else {}
    replay_payload["_event_meta"] = {
        **(replay_payload.get("_event_meta") or {}),
        "replayed_from_dlq": True,
        "original_event_id": envelope.get("event_id"),
        "replayed_at_ms": int(time.time() * 1000),
    }
    source = str(envelope.get("source") or "event_dlq_replay")
    return replay_event_type, replay_payload, source


async def _run_handler_with_retry(handler: EventHandler, envelope: Dict[str, Any], event_type: str) -> None:
    attempts = max(1, int(getattr(settings, "event_bus_handler_retry_attempts", 1) or 1))
    delay_ms = max(0, int(getattr(settings, "event_bus_handler_retry_delay_ms", 200) or 0))
    last_exc: Optional[Exception] = None
    ts = int(envelope.get("ts") or int(time.time() * 1000))
    lag_ms = max(0, int(time.time() * 1000) - ts)
    for idx in range(attempts):
        started = time.perf_counter()
        try:
            await handler(envelope)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            await _record_handle_metric(event_type, success=True, handle_ms=elapsed_ms, lag_ms=lag_ms)
            return
        except Exception as exc:
            last_exc = exc
            if idx < attempts - 1 and delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)
    err = str(last_exc) if last_exc is not None else "unknown"
    await _record_handle_metric(event_type, success=False, handle_ms=0.0, lag_ms=lag_ms, error=err)
    await _push_dlq(event_type, envelope, err)
    logger.warning("[EventBus] handler failed for %s after retries: %s", event_type, last_exc)


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is not None:
        return _event_bus

    buses: list[EventBus] = [InProcessEventBus()]
    if bool(getattr(settings, "event_bus_enabled", False)):
        backend = str(getattr(settings, "event_bus_backend", "redis")).strip().lower()
        if backend == "redis":
            buses.append(
                RedisEventBus(
                    redis_url=str(getattr(settings, "event_bus_redis_url", "redis://127.0.0.1:6379/1")),
                    channel_prefix=str(getattr(settings, "event_bus_channel_prefix", "openvitamin:event")),
                )
            )
    _event_bus = CompositeEventBus(*buses)
    return _event_bus
