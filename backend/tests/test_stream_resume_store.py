"""stream_resume_store：缓冲与续传迭代（不加载完整应用）。"""

from __future__ import annotations

import asyncio

from api.stream_resume_store import StreamResumeStore, iter_resume_chunks


def test_iter_resume_waits_for_chunks_then_finishes() -> None:
    async def _run() -> None:
        store = StreamResumeStore(ttl_seconds=60.0, max_sessions=10)
        sid = "test-stream-id-00000000"
        sess = store.create(sid, user_id="u1")
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


def test_iter_resume_from_offset() -> None:
    async def _run() -> None:
        store = StreamResumeStore(ttl_seconds=60.0, max_sessions=10)
        sid = "test-stream-id-00000001"
        store.create(sid, user_id="u1")
        await store.append_chunk(sid, "first\n\n")
        await store.append_chunk(sid, "second\n\n")
        await store.finish(sid)

        got: list[str] = []
        async for piece in iter_resume_chunks(store, sid, 1, wait_timeout=1.0):
            got.append(piece)
        assert got == ["second\n\n"]

    asyncio.run(_run())
