"""
Execution Manager

执行管理器，协调 Workflow 的执行治理。
整合 ConcurrencyLimiter 和 QuotaManager。
"""

from typing import Optional, Dict, Any, List, Literal, cast
from dataclasses import dataclass
from datetime import datetime, timezone
import asyncio

from config.settings import settings
from core.data.base import SessionLocal
from core.data.models.workflow import WorkflowExecutionQueueORM
from core.workflows.repository import WorkflowExecutionQueueRepository
from core.workflows.governance.concurrency_limiter import ConcurrencyLimiter
from core.workflows.governance.quota_manager import QuotaManager, QuotaConfig
from log import logger


@dataclass
class ExecutionRequest:
    """执行请求"""
    execution_id: str
    workflow_id: str
    version_id: str
    priority: int = 0  # 优先级，数字越小优先级越高
    estimated_tokens: Optional[int] = None
    timeout_seconds: Optional[float] = None


@dataclass
class ExecutionResult:
    """执行结果"""
    allowed: bool
    execution_id: str
    reason: Optional[str] = None
    queue_position: Optional[int] = None
    estimated_wait_seconds: Optional[float] = None
    queued_at: Optional[str] = None
    wait_duration_ms: Optional[int] = None


class ExecutionManager:
    """
    执行管理器
    
    协调并发控制和配额管理，提供统一的执行治理接口。
    """
    
    def __init__(
        self,
        global_concurrency_limit: int = 10,
        per_workflow_concurrency_limit: int = 3,
        max_queue_size: int = 200,
        backpressure_strategy: Literal["wait", "reject"] = "wait",
        pending_warn_seconds: float = 8.0,
        pending_warn_interval_seconds: float = 5.0,
    ):
        self.concurrency_limiter = ConcurrencyLimiter(
            global_limit=global_concurrency_limit,
            per_workflow_limit=per_workflow_concurrency_limit
        )
        self.quota_manager = QuotaManager()
        self._max_queue_size = max(1, int(max_queue_size))
        self._backpressure_strategy: Literal["wait", "reject"] = (
            "reject" if backpressure_strategy == "reject" else "wait"
        )
        # workflow 级覆盖（可选）
        self._workflow_overrides: Dict[str, Dict[str, Any]] = {}
        
        # 执行队列（按优先级排序）
        self._execution_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        
        # 队列中的执行 ID
        self._queued_executions: set = set()
        self._queued_by_workflow: Dict[str, int] = {}
        self._queued_meta: Dict[str, Dict[str, Any]] = {}
        self._queue_order: int = 0
        self._recent_wait_ms_by_workflow: Dict[str, List[int]] = {}
        self._recent_reject_count_by_workflow: Dict[str, int] = {}
        self._queue_processor_task: Optional[asyncio.Task] = None
        self._pending_warn_seconds: float = max(1.0, float(pending_warn_seconds))
        self._pending_warn_interval_seconds: float = max(1.0, float(pending_warn_interval_seconds))
        self._lease_owner: str = f"exec-manager-{id(self)}"
        self._recover_persisted_queue()

    async def request_execution(
        self,
        request: ExecutionRequest
    ) -> ExecutionResult:
        """
        请求执行
        
        检查配额和并发限制，决定是否允许执行。
        """
        # 1. 检查配额
        quota_allowed, quota_reason = self.quota_manager.check_quota(
            request.workflow_id,
            request.estimated_tokens
        )
        
        if not quota_allowed:
            return ExecutionResult(
                allowed=False,
                execution_id=request.execution_id,
                reason=f"Quota check failed: {quota_reason}"
            )
        
        # 2. 尝试获取并发槽位
        acquired = await self.concurrency_limiter.acquire(
            request.execution_id,
            request.workflow_id,
            timeout=0  # 非阻塞尝试
        )
        
        if acquired:
            # 记录执行开始
            self.quota_manager.record_execution_start(request.workflow_id)
            
            return ExecutionResult(
                allowed=True,
                execution_id=request.execution_id
            )
        
        # 3. backpressure / queue capacity 检查
        wf_cfg = self._workflow_overrides.get(request.workflow_id, {})
        strategy: Literal["wait", "reject"] = (
            "reject" if wf_cfg.get("backpressure_strategy") == "reject" else self._backpressure_strategy
        )
        queue_limit = int(wf_cfg.get("max_queue_size") or self._max_queue_size)
        queue_size = len(self._queued_executions)

        if strategy == "reject":
            self._recent_reject_count_by_workflow[request.workflow_id] = (
                self._recent_reject_count_by_workflow.get(request.workflow_id, 0) + 1
            )
            return ExecutionResult(
                allowed=False,
                execution_id=request.execution_id,
                reason=f"Backpressure reject (strategy=reject, queue_size={queue_size})",
                queue_position=None,
                estimated_wait_seconds=None,
            )
        if queue_size >= queue_limit:
            self._recent_reject_count_by_workflow[request.workflow_id] = (
                self._recent_reject_count_by_workflow.get(request.workflow_id, 0) + 1
            )
            return ExecutionResult(
                allowed=False,
                execution_id=request.execution_id,
                reason=f"Queue full ({queue_size}/{queue_limit})",
                queue_position=None,
                estimated_wait_seconds=None,
            )

        # 4. 无法立即获取槽位，加入队列
        await self._enqueue(request)
        self._kick_queue_processor()
        
        queue_position = self._get_queue_position(request.execution_id)
        queued_meta = self._queued_meta.get(request.execution_id) or {}
        queued_at_iso = None
        queued_at = queued_meta.get("queued_at")
        if isinstance(queued_at, datetime):
            queued_at_iso = queued_at.isoformat()
        
        return ExecutionResult(
            allowed=False,
            execution_id=request.execution_id,
            reason="Concurrency limit reached, queued",
            queue_position=queue_position,
            estimated_wait_seconds=self._estimate_wait_time(queue_position),
            queued_at=queued_at_iso,
        )

    async def wait_for_execution(
        self,
        request: ExecutionRequest
    ) -> ExecutionResult:
        """
        等待执行
        
        阻塞直到获取执行槽位。
        """
        # 首先尝试非阻塞获取
        result = await self.request_execution(request)

        if result.allowed:
            return result

        # 如果已经在队列中，等待
        if request.execution_id in self._queued_executions:
            queued_result = await self._await_queued_execution(request)
            if queued_result is not None:
                return queued_result

        # 直接尝试获取槽位（带超时）
        acquired = await self.concurrency_limiter.acquire(
            request.execution_id,
            request.workflow_id,
            timeout=request.timeout_seconds
        )

        if acquired:
            self.quota_manager.record_execution_start(request.workflow_id)
            return ExecutionResult(
                allowed=True,
                execution_id=request.execution_id
            )

        return ExecutionResult(
            allowed=False,
            execution_id=request.execution_id,
            reason="Timeout waiting for execution slot"
        )

    async def _await_queued_execution(self, request: ExecutionRequest) -> Optional[ExecutionResult]:
        queue_position = self._get_queue_position(request.execution_id)
        queued_meta = self._queued_meta.get(request.execution_id) or {}
        queued_at = queued_meta.get("queued_at")
        queued_at_iso = queued_at.isoformat() if isinstance(queued_at, datetime) else None
        queue_entered_ts = (
            queued_at.timestamp()
            if isinstance(queued_at, datetime)
            else datetime.now(timezone.utc).timestamp()
        )
        next_warn_ts = queue_entered_ts + self._pending_warn_seconds

        while request.execution_id in self._queued_executions:
            now_ts = datetime.now(timezone.utc).timestamp()
            if now_ts >= next_warn_ts:
                self._log_pending_wait_warning(request, queue_entered_ts, now_ts)
                next_warn_ts = now_ts + self._pending_warn_interval_seconds
            await asyncio.sleep(0.1)

        return await self._try_acquire_after_queue_wait(
            request=request,
            queue_position=queue_position,
            queued_at=queued_at,
            queued_at_iso=queued_at_iso,
        )

    def _log_pending_wait_warning(
        self, request: ExecutionRequest, queue_entered_ts: float, now_ts: float
    ) -> None:
        queued_for_s = max(0.0, now_ts - queue_entered_ts)
        status = self.concurrency_limiter.get_status()
        wf_active = int(status.get("per_workflow_active", {}).get(request.workflow_id, 0))
        wf_waiting = int(status.get("per_workflow_waiting", {}).get(request.workflow_id, 0))
        logger.warning(
            "[ExecutionManager] Pending execution exceeded threshold: "
            f"execution_id={request.execution_id} workflow_id={request.workflow_id} "
            f"queued_for_s={queued_for_s:.1f} queue_position={self._get_queue_position(request.execution_id)} "
            f"queue_size={len(self._queued_executions)} workflow_queue_size={self._queued_by_workflow.get(request.workflow_id, 0)} "
            f"slots(global_active={status.get('global_active')}/{status.get('global_limit')}, "
            f"global_available={status.get('global_available')}, global_waiting={status.get('global_waiting')}, "
            f"workflow_active={wf_active}/{status.get('per_workflow_limit')}, workflow_waiting={wf_waiting})"
        )

    async def _try_acquire_after_queue_wait(
        self,
        *,
        request: ExecutionRequest,
        queue_position: Optional[int],
        queued_at: Any,
        queued_at_iso: Optional[str],
    ) -> Optional[ExecutionResult]:
        if self.concurrency_limiter.is_acquired(request.execution_id):
            wait_duration_ms = self._compute_wait_duration_ms(request.workflow_id, queued_at)
            return self._build_queued_allowed_result(
                request=request,
                queue_position=queue_position,
                queued_at_iso=queued_at_iso,
                wait_duration_ms=wait_duration_ms,
            )

        acquired = await self.concurrency_limiter.acquire(
            request.execution_id,
            request.workflow_id,
            timeout=request.timeout_seconds
        )
        if not acquired:
            return None
        self.quota_manager.record_execution_start(request.workflow_id)
        wait_duration_ms = self._compute_wait_duration_ms(request.workflow_id, queued_at)
        return self._build_queued_allowed_result(
            request=request,
            queue_position=queue_position,
            queued_at_iso=queued_at_iso,
            wait_duration_ms=wait_duration_ms,
        )

    def _compute_wait_duration_ms(self, workflow_id: str, queued_at: Any) -> Optional[int]:
        if not isinstance(queued_at, datetime):
            return None
        wait_duration_ms = int((datetime.now(timezone.utc) - queued_at).total_seconds() * 1000)
        self._record_wait_duration(workflow_id, wait_duration_ms)
        return wait_duration_ms

    def _build_queued_allowed_result(
        self,
        *,
        request: ExecutionRequest,
        queue_position: Optional[int],
        queued_at_iso: Optional[str],
        wait_duration_ms: Optional[int],
    ) -> ExecutionResult:
        return ExecutionResult(
            allowed=True,
            execution_id=request.execution_id,
            queue_position=queue_position,
            estimated_wait_seconds=self._estimate_wait_time(queue_position),
            queued_at=queued_at_iso,
            wait_duration_ms=wait_duration_ms,
        )

    def complete_execution(
        self,
        execution_id: str,
        workflow_id: str,
        tokens_consumed: int = 0
    ) -> None:
        """完成执行"""
        # 释放并发槽位
        self.concurrency_limiter.release(execution_id)

        # 记录执行结束
        self.quota_manager.record_execution_end(workflow_id, tokens_consumed)

        # 处理队列中的下一个请求
        self._kick_queue_processor()
        self._persist_mark_done(execution_id)

        logger.info(
            f"[ExecutionManager] Completed execution {execution_id} "
            f"for workflow {workflow_id}"
        )

    def cancel_execution(self, execution_id: str, workflow_id: str) -> bool:
        """取消执行"""
        # 如果在队列中，从队列移除
        if execution_id in self._queued_executions:
            self._queued_executions.discard(execution_id)
            self._queued_by_workflow[workflow_id] = max(0, self._queued_by_workflow.get(workflow_id, 0) - 1)
            self._queued_meta.pop(execution_id, None)
            self._persist_mark_cancelled(execution_id)
            logger.info(f"[ExecutionManager] Cancelled queued execution {execution_id}")
            return True

        # 如果已获取槽位，释放槽位
        if self.concurrency_limiter.is_acquired(execution_id):
            self.concurrency_limiter.release(execution_id)
            self.quota_manager.record_execution_end(workflow_id, 0)
            self._persist_mark_cancelled(execution_id)
            logger.info(f"[ExecutionManager] Cancelled running execution {execution_id}")
            return True

        return False

    def set_quota(self, workflow_id: str, config: QuotaConfig) -> None:
        """设置工作流配额"""
        self.quota_manager.set_quota(workflow_id, config)

    def get_status(self) -> Dict[str, Any]:
        """获取执行管理器状态"""
        return {
            "concurrency": self.concurrency_limiter.get_status(),
            "queue_size": len(self._queued_executions),
            "governance_config": {
                "max_queue_size": self._max_queue_size,
                "backpressure_strategy": self._backpressure_strategy,
            },
        }

    def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """获取工作流状态"""
        wf_cfg = self._workflow_overrides.get(workflow_id, {})
        wait_samples = self._recent_wait_ms_by_workflow.get(workflow_id, [])
        avg_wait_ms = int(sum(wait_samples) / len(wait_samples)) if wait_samples else None
        return {
            "quota": self.quota_manager.get_quota_status(workflow_id),
            "concurrency": {
                "active_slots": sum(
                    1 for slot in self.concurrency_limiter._slots.values()
                    if slot.workflow_id == workflow_id
                )
            },
            "queue": {
                "queued_executions": self._queued_by_workflow.get(workflow_id, 0),
                "max_queue_size": int(wf_cfg.get("max_queue_size") or self._max_queue_size),
                "backpressure_strategy": (
                    "reject" if wf_cfg.get("backpressure_strategy") == "reject" else self._backpressure_strategy
                ),
                "recent_reject_count": int(self._recent_reject_count_by_workflow.get(workflow_id, 0)),
                "average_wait_ms": avg_wait_ms,
            },
        }

    def set_global_governance_config(
        self,
        *,
        max_queue_size: Optional[int] = None,
        backpressure_strategy: Optional[str] = None,
    ) -> None:
        """设置全局治理参数"""
        if max_queue_size is not None:
            self._max_queue_size = max(1, int(max_queue_size))
        if backpressure_strategy is not None:
            self._backpressure_strategy = "reject" if backpressure_strategy == "reject" else "wait"

    def set_workflow_governance_config(
        self,
        workflow_id: str,
        *,
        max_queue_size: Optional[int] = None,
        backpressure_strategy: Optional[str] = None,
    ) -> None:
        """设置 workflow 级治理参数覆盖"""
        cfg = dict(self._workflow_overrides.get(workflow_id, {}))
        if max_queue_size is not None:
            cfg["max_queue_size"] = max(1, int(max_queue_size))
        if backpressure_strategy is not None:
            cfg["backpressure_strategy"] = "reject" if backpressure_strategy == "reject" else "wait"
        self._workflow_overrides[workflow_id] = cfg

    async def _enqueue(self, request: ExecutionRequest) -> None:
        """将请求加入队列"""
        if request.execution_id in self._queued_executions:
            logger.debug(f"[ExecutionManager] Skip duplicate enqueue for {request.execution_id}")
            return
        # 优先级队列：(priority, timestamp, request)
        await self._execution_queue.put((
            request.priority,
            datetime.now(timezone.utc).timestamp(),
            request
        ))
        self._queued_executions.add(request.execution_id)
        self._queued_by_workflow[request.workflow_id] = self._queued_by_workflow.get(request.workflow_id, 0) + 1
        self._queue_order += 1
        self._queued_meta[request.execution_id] = {
            "workflow_id": request.workflow_id,
            "priority": request.priority,
            "queued_at": datetime.now(timezone.utc),
            "order": self._queue_order,
        }
        self._persist_enqueue(request, self._queue_order)

        logger.debug(f"[ExecutionManager] Enqueued execution {request.execution_id}")

    def _get_queue_position(self, execution_id: str) -> Optional[int]:
        """获取队列位置"""
        target = self._queued_meta.get(execution_id)
        if not target:
            return None
        target_priority = int(target.get("priority", 0))
        target_order = int(target.get("order", 0))
        position = 1
        for eid, meta in self._queued_meta.items():
            if eid == execution_id:
                continue
            p = int(meta.get("priority", 0))
            o = int(meta.get("order", 0))
            if p < target_priority or (p == target_priority and o < target_order):
                position += 1
        return position

    def _estimate_wait_time(self, queue_position: Optional[int]) -> Optional[float]:
        """估计等待时间"""
        if queue_position is None:
            return None
        # 假设每个执行平均 30 秒
        return queue_position * 30.0

    async def _process_queue(self) -> None:
        """处理队列中的请求"""
        leased = self._lease_next()
        if leased is None:
            return
        leased_any = cast(Any, leased)
        request = ExecutionRequest(
            execution_id=cast(str, leased_any.execution_id),
            workflow_id=cast(str, leased_any.workflow_id),
            version_id=cast(str, leased_any.version_id),
            priority=int(cast(int, leased_any.priority) or 0),
        )
        queued_meta = self._queued_meta.pop(request.execution_id, {})
        queued_at = queued_meta.get("queued_at")

        acquired = await self.concurrency_limiter.acquire(
            request.execution_id,
            request.workflow_id,
            timeout=0
        )
        if acquired:
            self._queued_executions.discard(request.execution_id)
            self._queued_by_workflow[request.workflow_id] = max(
                0, self._queued_by_workflow.get(request.workflow_id, 0) - 1
            )
            self.quota_manager.record_execution_start(request.workflow_id)
            self._persist_mark_done(request.execution_id)
            if isinstance(queued_at, datetime):
                wait_duration_ms = int((datetime.now(timezone.utc) - queued_at).total_seconds() * 1000)
                self._record_wait_duration(request.workflow_id, wait_duration_ms)
            logger.info(
                f"[ExecutionManager] Dequeued and started execution {request.execution_id}"
            )
        else:
            # 释放 lease，回到 queued 等待下次处理
            self._persist_enqueue(request, int(queued_meta.get("order") or 0))
            if request.execution_id not in self._queued_executions:
                self._queued_executions.add(request.execution_id)
                self._queued_by_workflow[request.workflow_id] = self._queued_by_workflow.get(request.workflow_id, 0) + 1

    def _kick_queue_processor(self) -> None:
        """确保队列处理任务被调度（幂等）。"""
        task = self._queue_processor_task
        if task is not None and not task.done():
            return
        self._queue_processor_task = asyncio.create_task(self._process_queue())

    def _record_wait_duration(self, workflow_id: str, wait_duration_ms: int) -> None:
        samples = self._recent_wait_ms_by_workflow.setdefault(workflow_id, [])
        samples.append(max(0, int(wait_duration_ms)))
        if len(samples) > 100:
            del samples[: len(samples) - 100]

    def _persist_enqueue(self, request: ExecutionRequest, queue_order: int) -> None:
        with SessionLocal() as db:
            repo = WorkflowExecutionQueueRepository(db)
            repo.enqueue(
                execution_id=request.execution_id,
                workflow_id=request.workflow_id,
                version_id=request.version_id,
                priority=request.priority,
                queue_order=queue_order,
            )

    def _persist_mark_done(self, execution_id: str) -> None:
        with SessionLocal() as db:
            WorkflowExecutionQueueRepository(db).mark_done(execution_id)

    def _persist_mark_cancelled(self, execution_id: str) -> None:
        with SessionLocal() as db:
            WorkflowExecutionQueueRepository(db).mark_cancelled(execution_id)

    def _lease_next(self) -> Optional[WorkflowExecutionQueueORM]:
        with SessionLocal() as db:
            return WorkflowExecutionQueueRepository(db).lease_next(lease_owner=self._lease_owner, lease_seconds=30)

    def _recover_persisted_queue(self) -> None:
        try:
            with SessionLocal() as db:
                rows = WorkflowExecutionQueueRepository(db).list_active()
            for row in rows:
                row_any = cast(Any, row)
                req = ExecutionRequest(
                    execution_id=cast(str, row_any.execution_id),
                    workflow_id=cast(str, row_any.workflow_id),
                    version_id=cast(str, row_any.version_id),
                    priority=int(cast(int, row_any.priority) or 0),
                )
                if req.execution_id in self._queued_executions:
                    continue
                self._queue_order = max(self._queue_order, int(cast(int, row_any.queue_order) or 0))
                queued_at = cast(Optional[datetime], row_any.queued_at)
                self._queued_executions.add(req.execution_id)
                self._queued_by_workflow[req.workflow_id] = self._queued_by_workflow.get(req.workflow_id, 0) + 1
                self._queued_meta[req.execution_id] = {
                    "workflow_id": req.workflow_id,
                    "priority": req.priority,
                    "queued_at": queued_at,
                    "order": int(cast(int, row_any.queue_order) or 0),
                }
                self._execution_queue.put_nowait((req.priority, float(int(cast(int, row_any.queue_order) or 0)), req))
            if rows:
                logger.info(f"[ExecutionManager] Recovered persisted queue items: {len(rows)}")
        except Exception as e:
            logger.warning(f"[ExecutionManager] Failed to recover persisted queue: {e}")


_execution_manager: Optional["ExecutionManager"] = None


def get_execution_manager(
    global_concurrency_limit: int = 10,
    per_workflow_concurrency_limit: int = 3,
    max_queue_size: int = 200,
    backpressure_strategy: Literal["wait", "reject"] = "wait",
    pending_warn_seconds: Optional[float] = None,
    pending_warn_interval_seconds: Optional[float] = None,
) -> "ExecutionManager":
    """
    获取全局 ExecutionManager 单例。

    Workflow API/Runtime 需要共享同一份治理状态，否则每个请求都 new 一个 Manager 会导致：
    - 并发控制失效（每个请求都有独立 semaphore）
    - 队列/背压无法生效
    """
    global _execution_manager
    if _execution_manager is None:
        warn_seconds = (
            float(pending_warn_seconds)
            if pending_warn_seconds is not None
            else float(getattr(settings, "workflow_pending_warn_seconds", 8.0))
        )
        warn_interval_seconds = (
            float(pending_warn_interval_seconds)
            if pending_warn_interval_seconds is not None
            else float(getattr(settings, "workflow_pending_warn_interval_seconds", 5.0))
        )
        _execution_manager = ExecutionManager(
            global_concurrency_limit=global_concurrency_limit,
            per_workflow_concurrency_limit=per_workflow_concurrency_limit,
            max_queue_size=max_queue_size,
            backpressure_strategy=backpressure_strategy,
            pending_warn_seconds=warn_seconds,
            pending_warn_interval_seconds=warn_interval_seconds,
        )
    return _execution_manager
