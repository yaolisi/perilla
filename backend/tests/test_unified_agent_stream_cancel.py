"""UnifiedModelAgent 流式取消：不误记 record_request_failed（Python 3.11+ CancelledError）。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agents.unified_agent import UnifiedModelAgent
from core.types import ChatCompletionRequest, Message


@pytest.mark.asyncio
async def test_stream_chat_cancelled_skips_record_request_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_metrics = MagicMock()
    monkeypatch.setattr("core.agents.unified_agent.get_runtime_metrics", lambda: mock_metrics)

    desc = MagicMock()
    desc.id = "model-cancel-test"
    desc.provider = "local"
    desc.runtime = "torch"

    agent = UnifiedModelAgent()
    agent.selector.resolve = MagicMock(return_value=desc)

    mock_rt = MagicMock()
    mock_rt.stream_chat = AsyncMock(side_effect=AssertionError("runtime.stream_chat should not run"))

    mock_im = MagicMock()
    mock_im.get_instance = AsyncMock(return_value=mock_rt)
    monkeypatch.setattr("core.agents.unified_agent.get_model_instance_manager", lambda: mock_im)

    async def run_stream_cancel(_agen: object, **_kwargs: object):
        if False:
            yield ""
        raise asyncio.CancelledError()

    mock_q = MagicMock()
    mock_q.run_stream = run_stream_cancel
    mock_qm = MagicMock()
    mock_qm.get_queue = lambda *_a, **_k: mock_q
    monkeypatch.setattr("core.agents.unified_agent.get_inference_queue_manager", lambda: mock_qm)

    class _Usage:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: object) -> None:
            return None

    mock_rf = MagicMock()
    mock_rf.model_usage = lambda _mid: _Usage()
    monkeypatch.setattr("core.agents.unified_agent.get_runtime_factory", lambda: mock_rf)

    req = ChatCompletionRequest(
        model="model-cancel-test",
        messages=[Message(role="user", content="ping")],
    )

    with pytest.raises(asyncio.CancelledError):
        async for _ in agent.stream_chat(req):
            pass

    mock_metrics.record_request.assert_called_once_with("model-cancel-test")
    mock_metrics.record_request_failed.assert_not_called()
