"""Chat SSE：关闭断点续传时客户端断开须走不完整落库分支，不得当作 chat_llm_done 成功。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from core.types import ChatCompletionRequest, Message
from api import chat as chat_api


@pytest.mark.asyncio
async def test_disconnect_without_resume_calls_disconnect_handler_not_success(monkeypatch: pytest.MonkeyPatch) -> None:
    prev_resume = bool(getattr(settings, "chat_stream_resume_enabled", True))
    settings.chat_stream_resume_enabled = False
    monkeypatch.setattr(chat_api, "get_chat_stream_wall_clock_max_seconds", lambda: 0)

    disconnect_payload: dict[str, object] = {}
    success_calls: list[bool] = []

    def _capture_disconnect(**kwargs: object) -> None:
        disconnect_payload["full_text"] = kwargs.get("full_text")

    monkeypatch.setattr(chat_api, "_stream_handle_client_disconnect", _capture_disconnect)

    def _never_success(_final: str, _stream_ok: bool) -> None:
        success_calls.append(True)

    class _Agent:
        async def stream_chat(self, req: object) -> object:
            yield "a"
            yield "b"

    mock_request = MagicMock()
    mock_request.state = SimpleNamespace()
    mock_request.is_disconnected = AsyncMock(side_effect=[False, True])

    req = ChatCompletionRequest(
        model="dummy-model",
        messages=[Message(role="user", content="hello")],
        stream=True,
    )

    pieces: list[str] = []
    async for piece in chat_api._stream_event_generator(
        req=req,
        request=mock_request,
        agent=_Agent(),
        session_id=None,
        completion_id="chatcmpl-test",
        created_time=1700000000,
        trace_id=None,
        retrieved_count=0,
        rag_extra=None,
        user_text="hello",
        user_id="u1",
        persistence_mode="off",
        request_id=None,
        conv_manager=MagicMock(),
        persist_success_turn=_never_success,
        stream_format="openai",
        use_gzip=False,
    ):
        pieces.append(piece)

    try:
        assert success_calls == [], "must not treat disconnect-stop as successful completion"
        assert disconnect_payload.get("full_text") == "ab"
        assert len(pieces) >= 1 and "a" in "".join(pieces)
    finally:
        settings.chat_stream_resume_enabled = prev_resume
