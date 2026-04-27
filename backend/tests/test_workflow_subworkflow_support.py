from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.workflows.models.workflow_version import (
    WorkflowDAG,
    WorkflowNode,
    WorkflowVersion,
    WorkflowVersionState,
)
from core.workflows.models.workflow_execution import WorkflowExecution, WorkflowExecutionState
from core.workflows.runtime.graph_runtime_adapter import GraphRuntimeAdapter
from core.workflows.runtime.workflow_runtime import WorkflowRuntime
import core.workflows.runtime.workflow_runtime as workflow_runtime_module
from core.workflows.runtime.subworkflow import apply_output_mapping, build_child_input
from core.workflows.services.workflow_version_service import WorkflowVersionService
from execution_kernel.engine.context import GraphContext
from api.workflows import _build_execution_call_chain
from config.settings import settings
from core.agent_runtime.session import AgentSession


def _build_version(*, workflow_id: str, version_id: str, nodes: list[WorkflowNode]) -> WorkflowVersion:
    dag = WorkflowDAG(nodes=nodes, edges=[], entry_node=nodes[0].id if nodes else None, global_config={})
    return WorkflowVersion(
        version_id=version_id,
        workflow_id=workflow_id,
        definition_id=f"def-{workflow_id}",
        version_number="1.0.0",
        dag=dag,
        checksum=dag.compute_checksum(),
        state=WorkflowVersionState.PUBLISHED,
    )


def test_graph_runtime_adapter_accepts_sub_workflow_node() -> None:
    sub_node = WorkflowNode(
        id="sub-1",
        type="tool",
        config={
            "workflow_node_type": "sub_workflow",
            "target_workflow_id": "wf-child",
            "target_version_selector": "fixed",
            "target_version": "1.0.0",
        },
    )
    version = _build_version(workflow_id="wf-parent", version_id="v-parent", nodes=[sub_node])
    errors = GraphRuntimeAdapter.validate_compatibility(version)
    assert errors == []


def test_graph_runtime_adapter_accepts_multi_agent_role_nodes() -> None:
    nodes = [
        WorkflowNode(id="manager-1", type="tool", config={"workflow_node_type": "manager", "agent_id": "agent.manager"}),
        WorkflowNode(id="worker-1", type="tool", config={"workflow_node_type": "worker", "agent_id": "agent.worker"}),
        WorkflowNode(id="reflector-1", type="tool", config={"workflow_node_type": "reflector", "agent_id": "agent.reflector"}),
    ]
    version = _build_version(workflow_id="wf-parent", version_id="v-parent-roles", nodes=nodes)
    errors = GraphRuntimeAdapter.validate_compatibility(version)
    assert errors == []


def test_workflow_runtime_resolve_reflector_retry_config(monkeypatch) -> None:
    runtime = object.__new__(WorkflowRuntime)

    class _DummyStore:
        @staticmethod
        def get_setting(_key, default):
            return default

    monkeypatch.setattr(workflow_runtime_module, "get_system_settings_store", lambda: _DummyStore())
    cfg = runtime._resolve_reflector_retry_config(  # noqa: SLF001
        {
            "reflector_max_retries": "3",
            "reflector_retry_interval_seconds": "0.5",
            "reflector_fallback_agent_id": "agent.backup",
        },
        global_ctx={},
    )
    assert cfg["max_retries"] == 3
    assert cfg["retry_interval_seconds"] == pytest.approx(0.5)
    assert cfg["fallback_agent_id"] == "agent.backup"


def test_workflow_runtime_resolve_reflector_retry_config_supports_workflow_global_default(monkeypatch) -> None:
    runtime = object.__new__(WorkflowRuntime)

    class _DummyStore:
        @staticmethod
        def get_setting(_key, default):
            return default

    monkeypatch.setattr(workflow_runtime_module, "get_system_settings_store", lambda: _DummyStore())
    cfg = runtime._resolve_reflector_retry_config(  # noqa: SLF001
        {},
        global_ctx={
            "workflow_global_config": {
                "reflector": {
                    "max_retries": 2,
                    "retry_interval_seconds": 2.5,
                    "fallback_agent_id": "agent.global.backup",
                }
            }
        },
    )
    assert cfg["max_retries"] == 2
    assert cfg["retry_interval_seconds"] == pytest.approx(2.5)
    assert cfg["fallback_agent_id"] == "agent.global.backup"


def test_workflow_runtime_agent_output_includes_recovery_metadata() -> None:
    runtime = object.__new__(WorkflowRuntime)
    session = AgentSession(
        session_id="s-1",
        agent_id="agent.primary",
        user_id="u1",
        status="finished",
        messages=[],
        state={"workflow_agent_context": {"node_role": "reflector"}},
    )
    output = runtime._build_agent_output(  # noqa: SLF001
        session,
        "agent.primary",
        "node-1",
        recovery_meta={"fallback_used": True, "fallback_agent_id": "agent.backup"},
    )
    assert output["agent_role"] == "reflector"
    assert output["recovery"]["fallback_used"] is True


def test_workflow_runtime_agent_output_includes_collaboration_messages() -> None:
    runtime = object.__new__(WorkflowRuntime)
    session = AgentSession(
        session_id="s-2",
        agent_id="agent.worker",
        user_id="u1",
        status="finished",
        messages=[],
        state={
            "workflow_agent_context": {"node_role": "worker"},
            "collaboration": {
                "messages": [
                    {
                        "sender": "agent.manager",
                        "receiver": "agent.worker",
                        "task_id": "ex-1:node-2",
                        "status": "running",
                        "content": {"event": "attempt_started", "stage": "primary"},
                    }
                ]
            },
        },
    )
    output = runtime._build_agent_output(session, "agent.worker", "node-2")  # noqa: SLF001
    assert output["agent_role"] == "worker"
    assert isinstance(output.get("collaboration_messages"), list)
    assert output["collaboration_messages"][0]["receiver"] == "agent.worker"


def test_workflow_runtime_records_collaboration_messages_for_agent_attempts() -> None:
    runtime = object.__new__(WorkflowRuntime)
    session = AgentSession(
        session_id="wf_ex-1_node-1",
        agent_id="agent.primary",
        user_id="u1",
        status="idle",
        messages=[],
        state={
            "workflow_agent_context": {
                "workflow_execution_id": "ex-1",
                "source_node_id": "node-1",
            },
            "collaboration": {
                "correlation_id": "wfex_ex-1",
                "orchestrator_agent_id": "agent.manager",
            },
        },
    )
    updated = runtime._record_agent_collaboration_event(  # noqa: SLF001
        session,
        receiver="agent.primary",
        status="running",
        stage="primary",
        attempt=1,
        event="attempt_started",
    )
    collab = updated.state.get("collaboration") if isinstance(updated.state, dict) else {}
    messages = collab.get("messages") if isinstance(collab, dict) else []
    assert isinstance(messages, list)
    assert len(messages) == 1
    msg = messages[0]
    assert msg["sender"] == "agent.manager"
    assert msg["receiver"] == "agent.primary"
    assert msg["task_id"] == "ex-1:node-1"
    assert msg["status"] == "running"
    assert msg["content"]["event"] == "attempt_started"


def test_graph_runtime_adapter_parses_reflector_runtime_error_details() -> None:
    details_json = (
        '{"error_code":"AGENT_NODE_RUNTIME_ERROR","message":"primary failed",'
        '"recovery_trace":[{"attempt":1,"stage":"primary","status":"error"}]}'
    )
    parsed = GraphRuntimeAdapter._parse_node_error_details(  # noqa: SLF001
        f"AGENT_NODE_RUNTIME_ERROR_DETAILS: {details_json}"
    )
    assert isinstance(parsed, dict)
    assert parsed["error_code"] == "AGENT_NODE_RUNTIME_ERROR"
    assert parsed["message"] == "primary failed"
    assert isinstance(parsed["recovery_trace"], list)


def test_workflow_version_service_accepts_reflector_global_config() -> None:
    WorkflowVersionService._validate_workflow_global_config(  # noqa: SLF001
        {
            "reflector": {
                "max_retries": 2,
                "retry_interval_seconds": 1.5,
                "fallback_agent_id": "agent.backup",
            }
        }
    )


def test_workflow_version_service_rejects_invalid_reflector_global_config() -> None:
    with pytest.raises(ValueError, match="unsupported keys"):
        WorkflowVersionService._validate_workflow_global_config(  # noqa: SLF001
            {"reflector": {"unknown": 1}}
        )
    with pytest.raises(ValueError, match="max_retries out of range"):
        WorkflowVersionService._validate_workflow_global_config(  # noqa: SLF001
            {"reflector": {"max_retries": 999}}
        )
    with pytest.raises(ValueError, match="retry_interval_seconds out of range"):
        WorkflowVersionService._validate_workflow_global_config(  # noqa: SLF001
            {"reflector": {"retry_interval_seconds": 999.0}}
        )


def test_subworkflow_mapping_helpers_support_expression_and_output_mapping() -> None:
    context = GraphContext(
        global_data={"tenant": "t1", "input_data": {"seed": 7}},
        node_outputs={"n1": {"score": 88}},
        current_node_input={"user": {"name": "alice"}, "x": 1},
    )
    child_input = build_child_input(
        input_mapping={
            "name": {"type": "path", "from": "input.user.name"},
            "tenant": "${global.tenant}",
            "score": {"type": "path", "from": "nodes.n1.output.score"},
        },
        context=context,
        node_input={"user": {"name": "alice"}, "x": 1},
    )
    assert child_input == {"name": "alice", "tenant": "t1", "score": 88}

    mapped = apply_output_mapping(
        child_output={"result": {"ok": True}, "score": 90},
        output_mapping={"approved": "output.result.ok", "final_score": "score"},
    )
    assert mapped == {"approved": True, "final_score": 90}


def test_workflow_version_service_detects_subworkflow_cycles() -> None:
    service = WorkflowVersionService(db=None)  # type: ignore[arg-type]
    root_dag = WorkflowDAG(
        nodes=[
            WorkflowNode(
                id="sub-b",
                type="tool",
                config={
                    "workflow_node_type": "sub_workflow",
                    "target_workflow_id": "wf-b",
                    "target_version_selector": "fixed",
                    "target_version_id": "v-b",
                },
            )
        ],
        edges=[],
        entry_node="sub-b",
        global_config={},
    )
    wf_b_version = _build_version(
        workflow_id="wf-b",
        version_id="v-b",
        nodes=[
            WorkflowNode(
                id="sub-a",
                type="tool",
                config={
                    "workflow_node_type": "sub_workflow",
                    "target_workflow_id": "wf-a",
                    "target_version_selector": "fixed",
                    "target_version_id": "v-a",
                },
            )
        ],
    )
    wf_a_version = _build_version(
        workflow_id="wf-a",
        version_id="v-a",
        nodes=root_dag.nodes,
    )

    def _get_version_by_id(version_id: str):
        if version_id == "v-b":
            return wf_b_version
        if version_id == "v-a":
            return wf_a_version
        return None

    service.repository = SimpleNamespace(  # type: ignore[assignment]
        get_version_by_id=_get_version_by_id,
        get_version_by_number=lambda workflow_id, version: None,
        get_published_version=lambda workflow_id: None,
    )

    with pytest.raises(ValueError, match="Sub-workflow cycle detected"):
        service._validate_sub_workflow_cycles("wf-a", "v-a", root_dag)  # noqa: SLF001


def test_workflow_version_service_impact_analysis_marks_fixed_and_latest() -> None:
    service = WorkflowVersionService(db=None)  # type: ignore[arg-type]
    target_version = _build_version(
        workflow_id="wf-target",
        version_id="v-target-1",
        nodes=[WorkflowNode(id="n0", type="tool", config={"tool_name": "builtin_shell.run"})],
    )
    fixed_parent = _build_version(
        workflow_id="wf-parent-fixed",
        version_id="v-parent-fixed",
        nodes=[
            WorkflowNode(
                id="sub-fixed",
                type="tool",
                config={
                    "workflow_node_type": "sub_workflow",
                    "target_workflow_id": "wf-target",
                    "target_version_selector": "fixed",
                    "target_version_id": "v-target-1",
                },
            )
        ],
    )
    latest_parent = _build_version(
        workflow_id="wf-parent-latest",
        version_id="v-parent-latest",
        nodes=[
            WorkflowNode(
                id="sub-latest",
                type="tool",
                config={
                    "workflow_node_type": "sub_workflow",
                    "target_workflow_id": "wf-target",
                    "target_version_selector": "latest",
                },
            )
        ],
    )
    service.repository = SimpleNamespace(  # type: ignore[assignment]
        get_version_by_id=lambda version_id: target_version if version_id == "v-target-1" else None,
        list_versions=lambda state=None, limit=5000, offset=0: [fixed_parent, latest_parent],
        list_versions_by_workflow=lambda workflow_id, state=None, limit=20, offset=0: [],
    )

    impact = service.analyze_subworkflow_impact("wf-target", target_version_id="v-target-1")
    assert impact["total_impacted"] == 2
    kinds = {item["impact_kind"] for item in impact["impacted"]}
    assert kinds == {"fixed_version_match", "latest_reference"}


def test_workflow_version_service_impact_analysis_marks_breaking_when_contract_breaks() -> None:
    service = WorkflowVersionService(db=None)  # type: ignore[arg-type]
    baseline = _build_version(
        workflow_id="wf-target",
        version_id="v-target-base",
        nodes=[WorkflowNode(id="n0", type="tool", config={"tool_name": "builtin_shell.run"})],
    )
    target = _build_version(
        workflow_id="wf-target",
        version_id="v-target-new",
        nodes=[WorkflowNode(id="n0", type="tool", config={"tool_name": "builtin_shell.run"})],
    )
    baseline = baseline.model_copy(
        update={
            "dag": baseline.dag.model_copy(
                update={
                    "global_config": {
                        "input_schema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": [],
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {"ok": {"type": "boolean"}},
                        },
                    }
                }
            )
        }
    )
    target = target.model_copy(
        update={
            "dag": target.dag.model_copy(
                update={
                    "global_config": {
                        "input_schema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                            "required": ["age"],
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {},
                        },
                    }
                }
            )
        }
    )
    parent = _build_version(
        workflow_id="wf-parent-fixed",
        version_id="v-parent-fixed",
        nodes=[
            WorkflowNode(
                id="sub-fixed",
                type="tool",
                config={
                    "workflow_node_type": "sub_workflow",
                    "target_workflow_id": "wf-target",
                    "target_version_selector": "fixed",
                    "target_version_id": "v-target-new",
                },
            )
        ],
    )
    def _get_version_by_id(version_id: str):
        if version_id == "v-target-new":
            return target
        if version_id == "v-target-base":
            return baseline
        return None

    service.repository = SimpleNamespace(  # type: ignore[assignment]
        get_version_by_id=_get_version_by_id,
        list_versions=lambda state=None, limit=5000, offset=0: [parent],
        list_versions_by_workflow=lambda workflow_id, state=None, limit=20, offset=0: [target, baseline],
    )

    impact = service.analyze_subworkflow_impact(
        "wf-target",
        target_version_id="v-target-new",
        baseline_version_id="v-target-base",
    )
    assert impact["risk_summary"]["breaking"] == 1
    assert impact["contract_diff"]["breaking_changes"]
    assert impact["impacted"][0]["risk_level"] == "breaking"
    assert "breaking contract changes" in impact["impacted"][0]["impact_reason"]


def test_workflow_version_service_contract_policy_and_exemption_controls_risk() -> None:
    service = WorkflowVersionService(db=None)  # type: ignore[arg-type]
    baseline = _build_version(
        workflow_id="wf-target",
        version_id="v-base",
        nodes=[WorkflowNode(id="n0", type="tool", config={"tool_name": "builtin_shell.run"})],
    )
    target = _build_version(
        workflow_id="wf-target",
        version_id="v-new",
        nodes=[WorkflowNode(id="n0", type="tool", config={"tool_name": "builtin_shell.run"})],
    )
    baseline = baseline.model_copy(
        update={
            "dag": baseline.dag.model_copy(
                update={
                    "global_config": {
                        "input_schema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": [],
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {"ok": {"type": "boolean"}},
                        },
                    }
                }
            )
        }
    )
    target = target.model_copy(
        update={
            "dag": target.dag.model_copy(
                update={
                    "global_config": {
                        "input_schema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                            "required": ["age"],
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {"ok": {"type": "boolean"}, "debug": {"type": "string"}},
                        },
                    }
                }
            )
        }
    )
    parent = _build_version(
        workflow_id="wf-parent",
        version_id="v-parent",
        nodes=[
            WorkflowNode(
                id="sub-fixed",
                type="tool",
                config={
                    "workflow_node_type": "sub_workflow",
                    "target_workflow_id": "wf-target",
                    "target_version_selector": "fixed",
                    "target_version_id": "v-new",
                },
            )
        ],
    )
    def _get_version_by_id(version_id: str):
        if version_id == "v-new":
            return target
        if version_id == "v-base":
            return baseline
        return None

    service.repository = SimpleNamespace(  # type: ignore[assignment]
        get_version_by_id=_get_version_by_id,
        list_versions=lambda state=None, limit=5000, offset=0: [parent],
        list_versions_by_workflow=lambda workflow_id, state=None, limit=20, offset=0: [target, baseline],
    )

    old_required_policy = settings.workflow_contract_required_input_added_breaking
    old_output_policy = settings.workflow_contract_output_added_risky
    old_exemptions = settings.workflow_contract_field_exemptions
    try:
        settings.workflow_contract_required_input_added_breaking = False
        settings.workflow_contract_output_added_risky = False
        settings.workflow_contract_field_exemptions = "input.age"
        impact = service.analyze_subworkflow_impact(
            "wf-target",
            target_version_id="v-new",
            baseline_version_id="v-base",
        )
        assert impact["risk_summary"]["breaking"] == 0
        assert impact["risk_summary"]["risky"] == 0
        assert impact["contract_diff"]["info_changes"]
        assert impact["contract_diff"]["policy"]["required_input_added_breaking"] is False
    finally:
        settings.workflow_contract_required_input_added_breaking = old_required_policy
        settings.workflow_contract_output_added_risky = old_output_policy
        settings.workflow_contract_field_exemptions = old_exemptions


def test_build_execution_call_chain_collects_parent_and_child_by_correlation() -> None:
    root = WorkflowExecution(
        execution_id="e-root",
        workflow_id="wf-a",
        version_id="v1",
        state=WorkflowExecutionState.RUNNING,
        global_context={"correlation_id": "cid-1"},
    )
    child = WorkflowExecution(
        execution_id="e-child",
        workflow_id="wf-b",
        version_id="v2",
        state=WorkflowExecutionState.COMPLETED,
        global_context={
            "correlation_id": "cid-1",
            "parent_execution_id": "e-root",
            "parent_node_id": "sub-1",
        },
    )
    other = WorkflowExecution(
        execution_id="e-other",
        workflow_id="wf-c",
        version_id="v3",
        state=WorkflowExecutionState.COMPLETED,
        global_context={"correlation_id": "cid-2"},
    )
    chain = _build_execution_call_chain(root, [other, child, root])
    assert chain["correlation_id"] == "cid-1"
    ids = [item["execution_id"] for item in chain["items"]]
    assert ids == ["e-root", "e-child"]
