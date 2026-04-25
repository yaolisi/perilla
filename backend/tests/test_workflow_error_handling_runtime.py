import json
import pytest

from core.workflows.models.workflow_version import WorkflowNode
from core.workflows.runtime.graph_runtime_adapter import GraphRuntimeAdapter
from execution_kernel.events.event_model import ExecutionEvent
from execution_kernel.events.event_types import ExecutionEventType
from api.workflows import _build_node_timeline_from_events


def test_graph_runtime_adapter_maps_error_handling_retry_policy() -> None:
    node = WorkflowNode(
        id="n1",
        type="tool",
        name="tool-1",
        config={
            "tool_name": "builtin_shell.run",
            "error_handling": {
                "max_retries": 3,
                "retry_interval_seconds": 1.5,
                "on_failure": "continue",
            },
        },
    )
    adapted = GraphRuntimeAdapter._adapt_node(node)  # noqa: SLF001
    assert adapted.retry_policy.max_retries == 3
    assert adapted.retry_policy.backoff_seconds == pytest.approx(1.5)
    assert adapted.retry_policy.backoff_multiplier == pytest.approx(1.0)
    assert adapted.config["error_handling"]["on_failure"] == "continue"


def test_parse_node_error_details_from_kernel_error_payload() -> None:
    payload = {"message": "boom", "error_type": "ValueError", "stack_trace": "trace..."}
    raw = "__EKERR__:" + json.dumps(payload, ensure_ascii=False)
    parsed = GraphRuntimeAdapter._parse_node_error_details(raw)  # noqa: SLF001
    assert parsed == payload


def test_node_timeline_failed_event_contains_stack_and_strategy() -> None:
    ev = ExecutionEvent(
        instance_id="i1",
        sequence=1,
        event_type=ExecutionEventType.NODE_FAILED,
        payload={
            "node_id": "n1",
            "error_message": "boom",
            "error_type": "ValueError",
            "stack_trace": "trace...",
            "failure_strategy": "replan",
            "retry_count": 2,
        },
    )
    rows = _build_node_timeline_from_events([ev])
    assert len(rows) == 1
    row = rows[0]
    assert row["node_id"] == "n1"
    assert row["error_message"] == "boom"
    assert row["error_type"] == "ValueError"
    assert row["error_stack"] == "trace..."
    assert row["failure_strategy"] == "replan"
    assert row["retry_count"] == 2
