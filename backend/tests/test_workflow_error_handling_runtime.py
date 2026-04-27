import json
import zipfile
from io import BytesIO
import pytest

from core.workflows.models.workflow_version import WorkflowNode
from core.workflows.runtime.graph_runtime_adapter import GraphRuntimeAdapter
from execution_kernel.events.event_model import ExecutionEvent
from execution_kernel.events.event_types import ExecutionEventType
from api.workflows import (
    _build_node_timeline_from_events,
    _build_error_row_from_event,
    _build_failure_report_archive_bytes,
    _build_failure_report_payload,
    _compute_report_sha256,
    _redact_sensitive_value_with_count,
    _redact_sensitive_value,
    _error_row_match_filters,
    _parse_query_iso_datetime,
)
from core.workflows.models.workflow_execution import WorkflowExecution, WorkflowExecutionState


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


def test_parse_query_iso_datetime_supports_z_suffix() -> None:
    dt = _parse_query_iso_datetime("2026-04-27T10:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None


def test_error_row_filters_support_node_type_strategy_and_time() -> None:
    ev = ExecutionEvent(
        instance_id="i1",
        sequence=3,
        event_type=ExecutionEventType.NODE_FAILED,
        payload={
            "node_id": "collector-1",
            "error_message": "timeout",
            "error_type": "TimeoutError",
            "stack_trace": "trace",
            "failure_strategy": "degrade",
            "retry_count": 1,
        },
    )
    row = _build_error_row_from_event(ev, execution_id="ex1")
    assert isinstance(row, dict)
    assert _error_row_match_filters(
        row,
        node_id="collector-1",
        error_type="TimeoutError",
        failure_strategy="degrade",
        start_dt=_parse_query_iso_datetime("2000-01-01T00:00:00Z"),
        end_dt=_parse_query_iso_datetime("2100-01-01T00:00:00Z"),
    )


def test_build_failure_report_payload_includes_recovery_actions_and_filters() -> None:
    execution = WorkflowExecution(
        execution_id="ex1",
        workflow_id="wf1",
        version_id="v1",
        state=WorkflowExecutionState.FAILED,
        graph_instance_id="g1",
        input_data={},
        global_context={"tenant": "default"},
        trigger_type="manual",
        error_details={"error_type": "RuntimeError", "recovery_actions": [{"kind": "alert", "status": "ok"}]},
        node_states=[],
    )
    payload = _build_failure_report_payload(
        workflow_id="wf1",
        execution=execution,
        execution_payload={"created_at": "2026-01-01T00:00:00+00:00", "node_timeline": [], "node_states": []},
        error_rows=[{"node_id": "n1"}],
        selected_node_id="n1",
        error_type="RuntimeError",
        failure_strategy="degrade",
        start_time="2026-01-01T00:00:00Z",
        end_time="2026-01-01T01:00:00Z",
    )
    assert payload["workflow_id"] == "wf1"
    assert payload["execution_id"] == "ex1"
    assert payload["report_schema_version"] == "1.1"
    assert payload["recovery_actions"] == [{"kind": "alert", "status": "ok"}]
    assert payload["filtered_error_logs"] == [{"node_id": "n1"}]
    assert payload["filter_snapshot"]["selected_node_id"] == "n1"


def test_build_failure_report_archive_contains_report_and_events_files() -> None:
    report = {
        "execution_id": "ex1",
        "state": "failed",
        "report_schema_version": "1.1",
        "redaction_applied": True,
        "redacted_key_count": 3,
    }
    report["report_sha256"] = _compute_report_sha256(report)
    archive_bytes = _build_failure_report_archive_bytes(
        report=report,
        events=[{"event_id": "e1", "event_type": "node_failed"}],
    )
    zf = zipfile.ZipFile(BytesIO(archive_bytes), "r")
    names = sorted(zf.namelist())
    assert names == [
        "README.txt",
        "execution-events.json",
        "failure-report.json",
        "failure-report.sha256",
    ]
    report = json.loads(zf.read("failure-report.json").decode("utf-8"))
    events = json.loads(zf.read("execution-events.json").decode("utf-8"))
    assert report["execution_id"] == "ex1"
    assert events[0]["event_id"] == "e1"
    readme = zf.read("README.txt").decode("utf-8")
    assert "Workflow Failure Bundle" in readme
    assert "audit_summary: schema=1.1;redaction=on;redacted_keys=3" in readme
    assert f"report_sha256: {report['report_sha256']}" in readme
    sidecar = zf.read("failure-report.sha256").decode("utf-8").strip()
    assert sidecar == report["report_sha256"]


def test_redact_sensitive_value_masks_nested_sensitive_fields() -> None:
    raw = {
        "api_key": "abc",
        "nested": {
            "Authorization": "Bearer token",
            "safe": "ok",
            "child": [{"password": "p1"}, {"x": 1}],
        },
    }
    out = _redact_sensitive_value(raw)
    assert out["api_key"] == "***REDACTED***"
    assert out["nested"]["Authorization"] == "***REDACTED***"
    assert out["nested"]["safe"] == "ok"
    assert out["nested"]["child"][0]["password"] == "***REDACTED***"


def test_redact_sensitive_value_with_count_returns_total_redacted_keys() -> None:
    raw = {"api_key": "x", "nested": {"token": "y"}, "items": [{"password": "z"}, {"safe": 1}]}
    redacted, count = _redact_sensitive_value_with_count(raw)
    assert count == 3
    assert redacted["api_key"] == "***REDACTED***"
    assert redacted["nested"]["token"] == "***REDACTED***"
    assert redacted["items"][0]["password"] == "***REDACTED***"


def test_compute_report_sha256_is_stable_for_sorted_payload() -> None:
    report_a = {
        "workflow_id": "wf1",
        "execution_id": "ex1",
        "meta": {"b": 2, "a": 1},
        "items": [{"y": 2, "x": 1}],
    }
    report_b = {
        "execution_id": "ex1",
        "items": [{"x": 1, "y": 2}],
        "workflow_id": "wf1",
        "meta": {"a": 1, "b": 2},
    }
    assert _compute_report_sha256(report_a) == _compute_report_sha256(report_b)


def test_compute_report_sha256_ignores_report_sha256_field() -> None:
    base = {"workflow_id": "wf1", "execution_id": "ex1", "state": "failed"}
    h1 = _compute_report_sha256(base)
    with_self = {**base, "report_sha256": "placeholder"}
    h2 = _compute_report_sha256(with_self)
    assert h1 == h2
