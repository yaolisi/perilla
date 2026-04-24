"""
V2.9 Runtime Stabilization Layer - Inference queue.

Per-model concurrency limit via asyncio.Semaphore.
"""
import asyncio
import threading
from typing import Dict, TypeVar, AsyncIterator, Optional, Literal
from log import logger

from core.runtime.config import get_max_concurrency

T = TypeVar("T")
QueuePriority = Literal["high", "medium", "low"]


class InferenceQueue:
    """
    Limits concurrent inference for one model.
    Uses a semaphore; run(coro) runs the coroutine under the semaphore.
    """

    def __init__(self, model_id: str, max_concurrency: int):
        self.model_id = model_id
        self._max_concurrency = max(1, max_concurrency)
        self._available_slots = self._max_concurrency
        self._in_flight = 0
        self._waiting = 0
        self._waiting_high = 0
        self._waiting_medium = 0
        self._waiting_low = 0
        self._lock = asyncio.Lock()
        self._cond = asyncio.Condition(self._lock)

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    def try_update_max_concurrency(self, new_max: int) -> bool:
        """
        Best-effort update of max_concurrency for this queue.

        Safety:
        - Only updates when idle (no waiting + no in-flight), so we don't change
          semaphore behavior mid-run.
        - Returns False if queue is busy or new_max is invalid/same.
        """
        new_max = max(1, int(new_max))
        if new_max == self._max_concurrency:
            return False
        # Best-effort check (not atomic); good enough to avoid surprising changes.
        if self._in_flight != 0 or self._waiting != 0:
            return False
        self._max_concurrency = new_max
        self._available_slots = new_max
        return True

    async def _inc_usage(self) -> None:
        async with self._lock:
            self._in_flight += 1
            self._notify_queue_size()

    async def _dec_usage(self) -> None:
        async with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._notify_queue_size()

    def _notify_queue_size(self) -> None:
        try:
            from core.runtime.manager.runtime_metrics import get_runtime_metrics
            get_runtime_metrics().set_queue_size(self.model_id, self._waiting + self._in_flight)
        except Exception:
            pass

    @staticmethod
    def _normalize_priority(priority: str | None) -> QueuePriority:
        val = (priority or "medium").strip().lower()
        if val in {"high", "medium", "low"}:
            return val  # type: ignore[return-value]
        return "medium"

    async def _acquire_slot(self, priority: QueuePriority) -> None:
        async with self._cond:
            self._waiting += 1
            if priority == "high":
                self._waiting_high += 1
            elif priority == "low":
                self._waiting_low += 1
            else:
                self._waiting_medium += 1
            self._notify_queue_size()
            try:
                await self._cond.wait_for(lambda: self._can_run(priority))
                self._available_slots -= 1
            finally:
                self._waiting = max(0, self._waiting - 1)
                if priority == "high":
                    self._waiting_high = max(0, self._waiting_high - 1)
                elif priority == "low":
                    self._waiting_low = max(0, self._waiting_low - 1)
                else:
                    self._waiting_medium = max(0, self._waiting_medium - 1)
                self._notify_queue_size()

    async def _release_slot(self) -> None:
        async with self._cond:
            self._available_slots = min(self._max_concurrency, self._available_slots + 1)
            self._cond.notify_all()

    def _can_run(self, priority: QueuePriority) -> bool:
        if self._available_slots <= 0:
            return False
        if priority == "high":
            return True
        if priority == "medium":
            return self._waiting_high == 0
        return self._waiting_high == 0 and self._waiting_medium == 0

    def current_usage(self) -> int:
        """Best-effort: in-flight count (waiting not tracked atomically)."""
        return self._in_flight

    async def run(self, coro, priority: str = "medium"):
        """
        Run coroutine with concurrency limit.
        Returns the result of the coroutine.
        """
        normalized_priority = self._normalize_priority(priority)
        acquired = False
        try:
            await self._acquire_slot(normalized_priority)
            acquired = True
            await self._inc_usage()
            try:
                return await coro
            finally:
                await self._dec_usage()
        finally:
            if acquired:
                await self._release_slot()

    async def run_stream(self, agen: AsyncIterator[T], priority: str = "medium") -> AsyncIterator[T]:
        """
        Run async generator under the semaphore.
        Semaphore is held for the entire consumption of the stream.
        """
        normalized_priority = self._normalize_priority(priority)
        acquired = False
        try:
            await self._acquire_slot(normalized_priority)
            acquired = True
            await self._inc_usage()
            try:
                async for item in agen:
                    yield item
            finally:
                await self._dec_usage()
        finally:
            if acquired:
                await self._release_slot()


class InferenceQueueManager:
    """
    Per-model inference queues.
    Creates one InferenceQueue per model_id with max_concurrency from config (by runtime_type).
    """

    def __init__(self):
        self._queues: Dict[str, InferenceQueue] = {}
        self._lock = threading.Lock()

    def get_queue(self, model_id: str, runtime_type: str) -> InferenceQueue:
        """Get or create queue for model_id; concurrency from model metadata > settings > MODEL_RUNTIME_CONFIG."""
        with self._lock:
            max_concurrency = get_max_concurrency(runtime_type, model_id=model_id)
            if model_id in self._queues:
                q = self._queues[model_id]
                if q.try_update_max_concurrency(max_concurrency):
                    logger.info(
                        "[RuntimeStabilization] Updated queue max_concurrency model_id=%s runtime=%s max_concurrency=%s",
                        model_id,
                        runtime_type,
                        max_concurrency,
                    )
                return q
            q = InferenceQueue(model_id=model_id, max_concurrency=max_concurrency)
            self._queues[model_id] = q
            return q

    def list_queues(self) -> Dict[str, InferenceQueue]:
        with self._lock:
            return dict(self._queues)


# Singleton (thread-safe for first access)
_queue_manager: Optional[InferenceQueueManager] = None
_queue_manager_lock = threading.Lock()


def get_inference_queue_manager() -> InferenceQueueManager:
    global _queue_manager
    with _queue_manager_lock:
        if _queue_manager is None:
            _queue_manager = InferenceQueueManager()
        return _queue_manager
