"""异步聊天任务：轮询须匹配提交时的 user_id + tenant_id。"""

from __future__ import annotations

import pytest

from core.runtime.queue.async_chat_jobs import AsyncChatJobManager

pytestmark = pytest.mark.tenant_isolation


@pytest.mark.asyncio
async def test_async_chat_job_get_requires_matching_user_and_tenant() -> None:
    mgr = AsyncChatJobManager()

    async def runner() -> dict[str, bool]:
        return {"ok": True}

    rid = await mgr.submit(runner, user_id="user_acme", tenant_id="tenant_alpha")
    seen = await mgr.get(rid, user_id="user_acme", tenant_id="tenant_alpha")
    assert seen is not None
    assert seen.request_id == rid

    assert await mgr.get(rid, user_id="other_user", tenant_id="tenant_alpha") is None
    assert await mgr.get(rid, user_id="user_acme", tenant_id="tenant_beta") is None


@pytest.mark.asyncio
async def test_async_chat_job_get_unknown_returns_none() -> None:
    mgr = AsyncChatJobManager()
    assert await mgr.get("job_nonexistent", user_id="u", tenant_id="t") is None
