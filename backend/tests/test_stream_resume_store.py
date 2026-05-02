"""stream_resume_store：缓冲与续传迭代（不加载完整应用）。"""

from __future__ import annotations

import asyncio

import pytest

from api.stream_resume_store import StreamResumeStore, iter_resume_chunks


def test_iter_resume_waits_for_chunks_then_finishes() -> None:
    async def _run() -> None:
        store = StreamResumeStore(ttl_seconds=60.0, max_sessions=10)
        sid = "test-stream-id-00000000"
        sess = store.create(sid, user_id="u1", tenant_id="default")
        sess.model_id = "m"
        sess.sse_created = 1
        sess.completion_id = "chatcmpl-x"

        out: list[str] = []

        async def producer() -> None:
            await asyncio.sleep(0.01)
            await store.append_chunk(sid, 'data: {"a":1}\n\n')
            await asyncio.sleep(0.01)
            await store.append_chunk(sid, "data: [DONE]\n\n")
            await store.finish(sid)

        task = asyncio.create_task(producer())
        async for piece in iter_resume_chunks(store, sid, 0, wait_timeout=2.0):
            out.append(piece)
        await task

        assert "data: " in out[0]
        assert out[-1].strip().endswith("data: [DONE]")

    asyncio.run(_run())


@pytest.mark.asyncio
async def test_pressure_eviction_finishes_victim_so_resume_iterator_unblocks() -> None:
    """驱逐时会标记 victim finished，持有 Session 的 iter_resume_chunks 应迅速结束，而非卡到 wait_timeout。"""
    store = StreamResumeStore(ttl_seconds=3600.0, max_sessions=1)
    store.create("s_first", "u1", "default")
    await store.append_chunk("s_first", 'data: {"x":1}\n\n')

    chunks_out: list[str] = []

    async def drain() -> None:
        async for piece in iter_resume_chunks(store, "s_first", 0, wait_timeout=60.0):
            chunks_out.append(piece)

    task = asyncio.create_task(drain())
    await asyncio.sleep(0.02)
    store.create("s_second", "u2", "default")
    await asyncio.wait_for(task, timeout=2.0)
    assert len(chunks_out) >= 1
    assert 'data: {"x":1}' in chunks_out[0] or "x" in chunks_out[0]
    assert store.get("s_first") is None


def test_create_evicts_oldest_when_at_cap_even_if_unfinished() -> None:
    """生产边界：仅已完成 TTL 回收不足以腾出槽位时，驱逐最旧会话，防止内存无限增长。"""
    store = StreamResumeStore(ttl_seconds=3600.0, max_sessions=2)
    store.create("s1", user_id="u1", tenant_id="default")
    store.create("s2", user_id="u2", tenant_id="default")
    assert len(store._sessions) == 2
    victim_ref = store.get("s1")
    assert victim_ref is not None
    store.create("s3", user_id="u3", tenant_id="default")
    assert len(store._sessions) == 2
    assert store.get("s1") is None
    assert victim_ref.pressure_evicted is True
    assert store.get("s2") is not None
    assert store.get("s3") is not None


def test_iter_resume_from_offset() -> None:
    async def _run() -> None:
        store = StreamResumeStore(ttl_seconds=60.0, max_sessions=10)
        sid = "test-stream-id-00000001"
        store.create(sid, user_id="u1", tenant_id="default")
        await store.append_chunk(sid, "first\n\n")
        await store.append_chunk(sid, "second\n\n")
        await store.finish(sid)

        got: list[str] = []
        async for piece in iter_resume_chunks(store, sid, 1, wait_timeout=1.0):
            got.append(piece)
        assert got == ["second\n\n"]

    asyncio.run(_run())
