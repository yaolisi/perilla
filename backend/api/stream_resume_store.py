"""
流式聊天断点续传：内存缓冲 SSE 帧，支持断连后继续生成并在恢复连接后从指定序号重放。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional


@dataclass
class StreamSession:
    chunks: list[str] = field(default_factory=list)
    finished: bool = False
    user_id: str = ""
    completion_id: str = ""
    model_id: str = ""
    sse_created: int = 0
    created_at: float = field(default_factory=time.time)
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)


class StreamResumeStore:
    def __init__(self, *, ttl_seconds: float = 600.0, max_sessions: int = 500) -> None:
        self._ttl = ttl_seconds
        self._max = max_sessions
        self._sessions: dict[str, StreamSession] = {}

    def create(self, stream_id: str, user_id: str) -> StreamSession:
        self._evict_if_needed()
        sess = StreamSession(user_id=user_id)
        self._sessions[stream_id] = sess
        return sess

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
