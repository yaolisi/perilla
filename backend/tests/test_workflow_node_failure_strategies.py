import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from execution_kernel.engine.executor import Executor
from execution_kernel.models.graph_definition import NodeDefinition, NodeType, RetryPolicy
from execution_kernel.models.node_models import NodeRuntime, NodeState


@pytest.mark.asyncio
async def test_executor_skip_strategy_returns_degraded_payload() -> None:
    state_machine = AsyncMock()
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    state_machine.get_node = AsyncMock(
        return_value=SimpleNamespace(
            id="rt1",
            graph_instance_id="g1",
            node_id="n1",
            retry_count=0,
            input_data={},
            output_data={},
            error_message="boom",
            error_type="RuntimeError",
            started_at=None,
            finished_at=None,
            created_at=None,
            updated_at=None,
        )
    )

    async def fail_handler(*_args, **_kwargs):
        raise RuntimeError("tool boom")

    executor = Executor(
        state_machine=state_machine,
        cache=cache,
        node_handlers={"tool": fail_handler},
    )
    node_runtime = NodeRuntime(id="rt1", graph_instance_id="g1", node_id="n1", state=NodeState.PENDING)
    node_def = NodeDefinition(
        id="n1",
        type=NodeType.TOOL,
        retry_policy=RetryPolicy(max_retries=0),
        config={"error_handling": {"on_failure": "skip"}},
    )

    result = await executor.execute_with_retry(node_runtime, node_def, context=SimpleNamespace(resolve_dict=lambda d: d))
    assert result["degraded"] is True
    assert result["failure_strategy"] == "skip"
    assert result["retry_count"] == 0
    assert result["replan_requested"] is False
    state_machine.skip.assert_awaited_once()


@pytest.mark.asyncio
async def test_executor_degrade_strategy_uses_fallback_node_output() -> None:
    state_machine = AsyncMock()
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    state_machine.get_node = AsyncMock(
        return_value=SimpleNamespace(
            id="rt1",
            graph_instance_id="g1",
            node_id="n1",
            retry_count=0,
            input_data={},
            output_data={},
            error_message="boom",
            error_type="RuntimeError",
            started_at=None,
            finished_at=None,
            created_at=None,
            updated_at=None,
        )
    )

    async def fail_handler(*_args, **_kwargs):
        raise RuntimeError("primary boom")

    async def fallback_handler(_node_def, _input_data, _context):
        await asyncio.sleep(0)
        return {"response": "fallback-ok", "model": "small"}

    executor = Executor(
        state_machine=state_machine,
        cache=cache,
        node_handlers={"tool": fail_handler, "llm": fallback_handler},
    )
    node_runtime = NodeRuntime(id="rt1", graph_instance_id="g1", node_id="n1", state=NodeState.PENDING)
    node_def = NodeDefinition(
        id="n1",
        type=NodeType.TOOL,
        retry_policy=RetryPolicy(max_retries=0),
        config={
            "error_handling": {
                "on_failure": "degrade",
                "degrade": {
                    "fallback_node": {
                        "type": "llm",
                        "config": {"model_id": "qwen-small"},
                    }
                },
            }
        },
    )

    result = await executor.execute_with_retry(node_runtime, node_def, context=SimpleNamespace(resolve_dict=lambda d: d))
    assert result["degraded"] is True
    assert result["failure_strategy"] == "degrade"
    assert result["response"] == "fallback-ok"
    assert result["model"] == "small"
    state_machine.skip.assert_awaited_once()
