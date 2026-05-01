"""推理网关流式取消：Prometheus in-flight 不得泄漏；CancelledError 不计入 errors_total。"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from core.inference.gateway.inference_gateway import InferenceGateway
from core.inference.models.inference_request import InferenceRequest
from core.inference.router.model_router import RoutingResult


@pytest.mark.asyncio
async def test_stream_asyncio_cancelled_calls_observe_cancel_not_failed() -> None:
    gateway = InferenceGateway()
    mock_pm = MagicMock()
    gateway.prom_metrics = mock_pm

    gateway.router.resolve = MagicMock(
        return_value=RoutingResult(
            alias=None,
            provider="test-provider",
            model_id="mid-1",
            resolved_via="alias",
        )
    )

    async def raising_stream(*_args, **_kwargs):
        raise asyncio.CancelledError()
        yield  # pragma: no cover

    gateway.adapter.stream = raising_stream

    req = InferenceRequest(model_alias="any", prompt="hi")

    with pytest.raises(asyncio.CancelledError):
        async for _ in gateway.stream(req):
            pass

    mock_pm.observe_inference_started.assert_called_once_with(operation="stream")
    mock_pm.observe_inference_cancelled.assert_called_once_with(operation="stream", provider="test-provider")
    mock_pm.observe_inference_failed.assert_not_called()
    mock_pm.observe_inference_finished.assert_not_called()
