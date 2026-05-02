"""
聊天异步任务管理器：提交后立即返回 request_id，结果可轮询查询。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from config.settings import settings


@dataclass
class AsyncChatJob:
    request_id: str
    status: str  # queued | running | succeeded | failed
    created_at: float
    updated_at: float
    user_id: str = ""
    tenant_id: str = ""
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class AsyncChatJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, AsyncChatJob] = {}
        self._lock = asyncio.Lock()
        self._running_tasks: set[asyncio.Task[Any]] = set()

    async def submit(self, runner, *, user_id: str, tenant_id: str) -> str:
        request_id = f"job_{uuid.uuid4().hex}"
        now = time.time()
        job = AsyncChatJob(
            request_id=request_id,
            status="queued",
            created_at=now,
            updated_at=now,
            user_id=str(user_id or ""),
            tenant_id=str(tenant_id or ""),
        )
        async with self._lock:
            self._jobs[request_id] = job
            self._cleanup_locked()
        task = asyncio.create_task(self._run_job(request_id=request_id, runner=runner))
        self._running_tasks.add(task)
        task.add_done_callback(self._running_tasks.discard)
        return request_id

    async def _run_job(self, request_id: str, runner) -> None:
        async with self._lock:
            job = self._jobs.get(request_id)
            if not job:
                return
            job.status = "running"
            job.updated_at = time.time()
        try:
            result = await runner()
            async with self._lock:
                job = self._jobs.get(request_id)
                if not job:
                    return
                job.status = "succeeded"
                job.result = result
                job.updated_at = time.time()
        except Exception as e:
            async with self._lock:
                job = self._jobs.get(request_id)
                if not job:
                    return
                job.status = "failed"
                job.error = str(e)
                job.updated_at = time.time()

    async def get(
        self,
        request_id: str,
        *,
        user_id: str,
        tenant_id: str,
    ) -> Optional[AsyncChatJob]:
        uid = str(user_id or "")
        tid = str(tenant_id or "")
        async with self._lock:
            self._cleanup_locked()
            job = self._jobs.get(request_id)
            if not job:
                return None
            if job.user_id != uid or job.tenant_id != tid:
                return None
            return job

    def _cleanup_locked(self) -> None:
        ttl_seconds = max(60, int(getattr(settings, "async_chat_job_ttl_seconds", 1800) or 1800))
        max_jobs = max(100, int(getattr(settings, "async_chat_job_max_entries", 2000) or 2000))
        now = time.time()
        expired = [k for k, v in self._jobs.items() if now - v.updated_at > ttl_seconds]
        for k in expired:
            self._jobs.pop(k, None)
        if len(self._jobs) <= max_jobs:
            return
        # 删除最旧记录，避免无限增长
        sorted_items = sorted(self._jobs.items(), key=lambda kv: kv[1].updated_at)
        for key, _ in sorted_items[: max(0, len(self._jobs) - max_jobs)]:
            self._jobs.pop(key, None)


_manager: Optional[AsyncChatJobManager] = None


def get_async_chat_job_manager() -> AsyncChatJobManager:
    global _manager
    if _manager is None:
        _manager = AsyncChatJobManager()
    return _manager
