"""
流式聊天断点续传：内存缓冲 SSE 帧，支持断连后继续生成并在恢复连接后从指定序号重放。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from log import logger, log_structured


async def _finalize_evicted_session(victim: "StreamSession") -> None:
    """驱逐出字典后仍可能被 iter_resume_chunks 持有的会话：标记结束并唤醒等待端。"""
    async with victim.cond:
        victim.finished = True
        victim.cond.notify_all()


def schedule_finalize_evicted_session(victim: "StreamSession") -> None:
    try:
        asyncio.get_running_loop().create_task(_finalize_evicted_session(victim))
    except RuntimeError:
        # 无运行中的事件循环（如同步单测）；会话留在内存直至 GC，续传迭代器较少与此路径相交
        pass


@dataclass
class StreamSession:
    chunks: list[str] = field(default_factory=list)
    finished: bool = False
    # chat_stream_resume_max_sessions 压力下被弹出全局表；iter_resume_chunks 仍可能持有引用
    pressure_evicted: bool = False
    user_id: str = ""
    tenant_id: str = ""
    completion_id: str = ""
    model_id: str = ""
    sse_created: int = 0
    created_at: float = field(default_factory=time.time)
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    # 与首流一致：续传时若曾 gzip 则对续传 body 同样做 gzip
    use_gzip: bool = False
    stream_format: str = "openai"


class StreamResumeStore:
    def __init__(self, *, ttl_seconds: float = 600.0, max_sessions: int = 500) -> None:
        self._ttl = ttl_seconds
        self._max = max(1, int(max_sessions))
        self._sessions: dict[str, StreamSession] = {}

    def _notify_pressure_eviction(self, evicted_id: str, victim: StreamSession) -> None:
        try:
            from core.observability import get_prometheus_business_metrics

            get_prometheus_business_metrics().observe_stream_resume_store_pressure_eviction()
        except Exception:
            pass
        log_structured(
            "StreamResume",
            "stream_resume_store_pressure_evict",
            level="warning",
            evicted_stream_id=str(evicted_id)[:48],
            evicted_finished=bool(victim.finished),
            evicted_chunk_count=len(victim.chunks),
        )
        logger.warning(
            "[StreamResumeStore] pressure eviction evicted_stream_id=%s finished=%s chunks=%s",
            str(evicted_id)[:24],
            victim.finished,
            len(victim.chunks),
        )
        schedule_finalize_evicted_session(victim)

    def create(self, stream_id: str, user_id: str, tenant_id: str) -> StreamSession:
        from config.settings import settings

        tid = (tenant_id or "").strip() or str(getattr(settings, "tenant_default_id", "default") or "default").strip() or "default"
        self._evict_if_needed()
        while len(self._sessions) >= self._max:
            oldest_key = min(self._sessions.keys(), key=lambda k: self._sessions[k].created_at)
            victim = self._sessions.pop(oldest_key)
            victim.pressure_evicted = True
            self._notify_pressure_eviction(oldest_key, victim)
        sess = StreamSession(user_id=user_id, tenant_id=tid)
        self._sessions[stream_id] = sess
        self._publish_session_count()
        return sess

    def _publish_session_count(self) -> None:
        try:
            from core.observability import get_prometheus_business_metrics

            get_prometheus_business_metrics().set_stream_resume_store_sessions(len(self._sessions))
        except Exception:
            pass

    def get(self, stream_id: str) -> Optional[StreamSession]:
        return self._sessions.get(stream_id)

    def _evict_if_needed(self) -> None:
        now = time.time()
        dead = [k for k, s in self._sessions.items() if s.finished and (now - s.created_at) > self._ttl]
        for k in dead:
            del self._sessions[k]
        while len(self._sessions) > self._max:
            oldest_key = min(self._sessions.keys(), key=lambda k: self._sessions[k].created_at)
            if self._sessions[oldest_key].finished:
                del self._sessions[oldest_key]
            else:
                break

    async def append_chunk(self, stream_id: str, sse_fragment: str) -> None:
        sess = self._sessions.get(stream_id)
        if not sess:
            return
        async with sess.cond:
            sess.chunks.append(sse_fragment)
            sess.cond.notify_all()

    async def finish(self, stream_id: str) -> None:
        sess = self._sessions.get(stream_id)
        if not sess:
            return
        async with sess.cond:
            sess.finished = True
            sess.cond.notify_all()


_store: Optional[StreamResumeStore] = None


def get_stream_resume_store() -> StreamResumeStore:
    global _store
    if _store is None:
        from config.settings import settings

        ttl = float(getattr(settings, "chat_stream_resume_ttl_seconds", 600) or 600)
        cap = int(getattr(settings, "chat_stream_resume_max_sessions", 500) or 500)
        _store = StreamResumeStore(ttl_seconds=ttl, max_sessions=cap)
    return _store


async def iter_resume_chunks(
    store: StreamResumeStore,
    stream_id: str,
    start_idx: int,
    *,
    wait_timeout: float = 120.0,
) -> AsyncIterator[str]:
    """从下标 start_idx 开始重放已缓冲帧；若生成未完成则阻塞等待新帧。"""
    sess = store.get(stream_id)
    if not sess:
        raise KeyError(stream_id)
    idx = start_idx
    while True:
        async with sess.cond:
            while idx >= len(sess.chunks) and not sess.finished:
                await asyncio.wait_for(sess.cond.wait(), timeout=wait_timeout)
            while idx < len(sess.chunks):
                yield sess.chunks[idx]
                idx += 1
            if sess.finished and idx >= len(sess.chunks):
                return
