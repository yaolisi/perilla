from __future__ import annotations

import asyncio
import json
from typing import TypedDict

from fastapi.testclient import TestClient

from api.stream_resume_store import StreamResumeStore


class ChatDeltaPayload(TypedDict):
    content: str


class ChatChoicePayload(TypedDict):
    index: int
    delta: ChatDeltaPayload


class ChatChunkPayload(TypedDict):
    id: str
    object: str
    created: int
    model: str
    choices: list[ChatChoicePayload]


def chat_prime_csrf(client: TestClient) -> str:
    """Prime CSRF cookie/token via safe GET and return token value."""
    r = client.get("/_ping")
    assert r.status_code == 200, r.text
    token = client.cookies.get("csrf_token")
    assert token, "CSRF cookie should be set after safe GET"
    return token


def chat_build_chunk(completion_id: str, created: int, model: str, content: str) -> ChatChunkPayload:
    """Build one OpenAI-compatible chat.completion.chunk payload."""
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {"content": content}}],
    }


def chat_seed_stream_store(
    store: StreamResumeStore,
    *,
    stream_id: str,
    user_id: str,
    completion_id: str,
    model_id: str = "dummy-model",
    created: int = 1700000000,
    contents: list[str] | None = None,
    append_done: bool = True,
    finish: bool = True,
) -> None:
    """Seed StreamResumeStore with test chunks (optionally DONE/finish)."""

    async def _fill() -> None:
        sess = store.create(stream_id, user_id=user_id)
        sess.completion_id = completion_id
        sess.model_id = model_id
        sess.sse_created = created
        for content in (contents or []):
            chunk = chat_build_chunk(completion_id, created, model_id, content)
            await store.append_chunk(stream_id, f"data: {json.dumps(chunk)}\n\n")
        if append_done:
            await store.append_chunk(stream_id, "data: [DONE]\n\n")
        if finish:
            await store.finish(stream_id)

    asyncio.run(_fill())
