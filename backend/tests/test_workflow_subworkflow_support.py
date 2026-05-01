from __future__ import annotations

import asyncio
from types import SimpleNamespace
import types

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
from execution_kernel.engine.scheduler import Scheduler
from execution_kernel.engine.control_flow import execute_condition_node
from execution_kernel.models.node_models import NodeState
from execution_kernel.models.graph_definition import (
    EdgeDefinition,
    EdgeTrigger,
    GraphDefinition,
    NodeDefinition,
    NodeType,
)
from api.workflows import _build_execution_call_chain
from config.settings import settings
from core.agent_runtime.session import AgentSession, agent_session_state_as_dict


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


def test_graph_runtime_adapter_accepts_parallel_node() -> None:
    parallel_node = WorkflowNode(
        id="parallel-1",
        type="tool",
        config={
            "workflow_node_type": "parallel",
            "max_parallel": 3,
        },
    )
    version = _build_version(workflow_id="wf-parent", version_id="v-parent-parallel", nodes=[parallel_node])
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


@pytest.mark.asyncio
async def test_workflow_runtime_loop_control_node_supports_for_loop_and_retry(monkeypatch) -> None:
    runtime = object.__new__(WorkflowRuntime)
    context = GraphContext(global_data={"input_data": {}}, node_outputs={}, current_node_input={})
    call_history: list[int] = []
    failed_once = {"value": False}

    async def _fake_body(self, *, node_def, body_cfg, input_data, context):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0)
        idx = int(input_data.get("loop_index", -1))
        call_history.append(idx)
        if idx == 1 and not failed_once["value"]:
            failed_once["value"] = True
            raise RuntimeError("transient")
        return {"last_index": idx}

    monkeypatch.setattr(runtime, "_execute_loop_body", types.MethodType(_fake_body, runtime))
    result = await runtime._execute_loop_control_node(  # noqa: SLF001
        node_def=SimpleNamespace(id="loop-1"),
        input_data={},
        context=context,
        cfg={
            "loop_type": "for",
            "loop_count": 3,
            "max_retries": 1,
            "retry_interval_seconds": 0,
            "loop_body": {"type": "tool"},
        },
    )
    assert result["type"] == "loop_result"
    assert result["iterations"] == 3
    assert result["last_index"] == 2
    assert call_history == [0, 1, 1, 2]


def test_workflow_runtime_parallel_control_node_emits_parallel_meta() -> None:
    runtime = object.__new__(WorkflowRuntime)
    result = runtime._execute_parallel_control_node(  # noqa: SLF001
        node_def=SimpleNamespace(id="parallel-1"),
        input_data={"seed": 1},
        context=GraphContext(global_data={"input_data": {}}, node_outputs={}, current_node_input={}),
        cfg={"max_parallel": 4},
    )
    assert result["type"] == "parallel_gate"
    assert result["parallel_ready"] is True
    assert result["__workflow_parallel_meta"]["max_parallel"] == 4


def test_scheduler_select_nodes_with_parallel_limits_blocks_when_limit_reached() -> None:
    scheduler = object.__new__(Scheduler)
    graph_def = GraphDefinition(
        id="g-parallel",
        version="1.0.0",
        nodes=[
            NodeDefinition(id="parallel-1", type=NodeType.TOOL, config={"workflow_node_type": "parallel", "max_parallel": 2}),
            NodeDefinition(id="a", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
            NodeDefinition(id="b", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
            NodeDefinition(id="c", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
            NodeDefinition(id="d", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
        ],
        edges=[
            EdgeDefinition(from_node="parallel-1", to_node="a", on=EdgeTrigger.SUCCESS),
            EdgeDefinition(from_node="parallel-1", to_node="b", on=EdgeTrigger.SUCCESS),
            EdgeDefinition(from_node="parallel-1", to_node="c", on=EdgeTrigger.SUCCESS),
        ],
    )
    all_nodes = [
        SimpleNamespace(node_id="a", state=SimpleNamespace(value="running")),
        SimpleNamespace(node_id="b", state=SimpleNamespace(value="running")),
        SimpleNamespace(node_id="c", state=SimpleNamespace(value="pending")),
        SimpleNamespace(node_id="d", state=SimpleNamespace(value="pending")),
    ]
    executable_nodes = [
        SimpleNamespace(node_id="c", state=SimpleNamespace(value="pending")),
        SimpleNamespace(node_id="d", state=SimpleNamespace(value="pending")),
    ]
    selected = scheduler._select_nodes_with_parallel_limits(  # noqa: SLF001
        executable_nodes=executable_nodes,
        graph_def=graph_def,
        all_nodes=all_nodes,
        available_slots=2,
    )
    assert [n.node_id for n in selected] == ["d"]


def test_scheduler_select_nodes_with_parallel_limits_allows_within_limit() -> None:
    scheduler = object.__new__(Scheduler)
    graph_def = GraphDefinition(
        id="g-parallel-allow",
        version="1.0.0",
        nodes=[
            NodeDefinition(id="parallel-1", type=NodeType.TOOL, config={"workflow_node_type": "parallel", "max_parallel": 2}),
            NodeDefinition(id="a", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
            NodeDefinition(id="b", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
        ],
        edges=[
            EdgeDefinition(from_node="parallel-1", to_node="a", on=EdgeTrigger.SUCCESS),
            EdgeDefinition(from_node="parallel-1", to_node="b", on=EdgeTrigger.SUCCESS),
        ],
    )
    all_nodes = [
        SimpleNamespace(node_id="a", state=SimpleNamespace(value="running")),
        SimpleNamespace(node_id="b", state=SimpleNamespace(value="pending")),
    ]
    executable_nodes = [
        SimpleNamespace(node_id="b", state=SimpleNamespace(value="pending")),
    ]
    selected = scheduler._select_nodes_with_parallel_limits(  # noqa: SLF001
        executable_nodes=executable_nodes,
        graph_def=graph_def,
        all_nodes=all_nodes,
        available_slots=1,
    )
    assert [n.node_id for n in selected] == ["b"]


@pytest.mark.asyncio
async def test_scheduler_condition_branch_routes_by_amount() -> None:
    scheduler = object.__new__(Scheduler)
    graph_def = GraphDefinition(
        id="g-condition-routing",
        version="1.0.0",
        nodes=[
            NodeDefinition(id="cond-1", type=NodeType.CONDITION, config={"workflow_node_type": "condition"}),
            NodeDefinition(id="ceo-approval", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
            NodeDefinition(id="manager-approval", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
        ],
        edges=[
            EdgeDefinition(from_node="cond-1", to_node="ceo-approval", on=EdgeTrigger.CONDITION_TRUE),
            EdgeDefinition(from_node="cond-1", to_node="manager-approval", on=EdgeTrigger.CONDITION_FALSE),
        ],
    )
    all_nodes_true = [
        SimpleNamespace(node_id="cond-1", output_data={"condition_result": True}),
    ]
    node_states_true = {"cond-1": NodeState.SUCCESS}
    ceo_ready = await scheduler._check_dependencies_with_edges(  # noqa: SLF001
        "ceo-approval", graph_def, node_states_true, all_nodes_true
    )
    manager_ready = await scheduler._check_dependencies_with_edges(  # noqa: SLF001
        "manager-approval", graph_def, node_states_true, all_nodes_true
    )
    assert ceo_ready is True
    assert manager_ready is False

    all_nodes_false = [
        SimpleNamespace(node_id="cond-1", output_data={"condition_result": False}),
    ]
    node_states_false = {"cond-1": NodeState.SUCCESS}
    ceo_ready_false = await scheduler._check_dependencies_with_edges(  # noqa: SLF001
        "ceo-approval", graph_def, node_states_false, all_nodes_false
    )
    manager_ready_false = await scheduler._check_dependencies_with_edges(  # noqa: SLF001
        "manager-approval", graph_def, node_states_false, all_nodes_false
    )
    assert ceo_ready_false is False
    assert manager_ready_false is True


@pytest.mark.asyncio
async def test_workflow_runtime_loop_control_node_supports_while_condition_progress(monkeypatch) -> None:
    runtime = object.__new__(WorkflowRuntime)
    context = GraphContext(global_data={"input_data": {}}, node_outputs={}, current_node_input={})

    async def _fake_body(self, *, node_def, body_cfg, input_data, context):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0)
        remaining = int(input_data.get("remaining", 0))
        return {"remaining": max(0, remaining - 1)}

    monkeypatch.setattr(runtime, "_execute_loop_body", types.MethodType(_fake_body, runtime))
    result = await runtime._execute_loop_control_node(  # noqa: SLF001
        node_def=SimpleNamespace(id="loop-while-1"),
        input_data={"remaining": 3},
        context=context,
        cfg={
            "loop_type": "while",
            "condition_expression": "${input.remaining} > 0",
            "max_iterations": 10,
            "loop_body": {"type": "tool"},
        },
    )
    assert result["type"] == "loop_result"
    assert result["iterations"] == 3
    assert result["exit_reason"] == "condition_false"
    assert result["remaining"] == 0


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


@pytest.mark.asyncio
async def test_enterprise_flow_loop_condition_parallel_end_to_end(monkeypatch) -> None:
    runtime = object.__new__(WorkflowRuntime)
    context = GraphContext(global_data={"input_data": {}}, node_outputs={}, current_node_input={})

    # 场景1：数据同步流程，每轮将 remaining 减一，直到 0（模拟每日执行）
    async def _sync_body(self, *, node_def, body_cfg, input_data, context):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0)
        remaining = int(input_data.get("remaining", 0))
        return {"remaining": max(0, remaining - 1), "synced": True}

    monkeypatch.setattr(runtime, "_execute_loop_body", types.MethodType(_sync_body, runtime))
    loop_result = await runtime._execute_loop_control_node(  # noqa: SLF001
        node_def=SimpleNamespace(id="loop-sync-30days"),
        input_data={"remaining": 30},
        context=context,
        cfg={
            "loop_type": "while",
            "condition_expression": "${input.remaining} > 0",
            "max_iterations": 60,
            "loop_body": {"type": "tool"},
        },
    )
    assert loop_result["iterations"] == 30
    assert loop_result["remaining"] == 0
    assert loop_result["exit_reason"] == "condition_false"

    # 场景2：订单审核流程，金额 > 10w 走 CEO，否则走经理
    condition_node = NodeDefinition(
        id="order-condition",
        type=NodeType.CONDITION,
        config={"condition_expression": "${input.order_amount} > 100000"},
    )
    cond_output = await execute_condition_node(
        node_def=condition_node,
        input_data={"order_amount": 120000},
        context=context,
    )
    scheduler = object.__new__(Scheduler)
    approval_graph = GraphDefinition(
        id="approval-graph",
        version="1.0.0",
        nodes=[
            condition_node,
            NodeDefinition(id="ceo-approval", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
            NodeDefinition(id="manager-approval", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
        ],
        edges=[
            EdgeDefinition(from_node="order-condition", to_node="ceo-approval", on=EdgeTrigger.CONDITION_TRUE),
            EdgeDefinition(from_node="order-condition", to_node="manager-approval", on=EdgeTrigger.CONDITION_FALSE),
        ],
    )
    all_nodes = [SimpleNamespace(node_id="order-condition", output_data=cond_output)]
    node_states = {"order-condition": NodeState.SUCCESS}
    ceo_ready = await scheduler._check_dependencies_with_edges(  # noqa: SLF001
        "ceo-approval", approval_graph, node_states, all_nodes
    )
    manager_ready = await scheduler._check_dependencies_with_edges(  # noqa: SLF001
        "manager-approval", approval_graph, node_states, all_nodes
    )
    assert ceo_ready is True
    assert manager_ready is False

    # 场景3：并行采集流程，并发上限=2时，第三个并行任务被抑制，非并行域任务放行
    parallel_graph = GraphDefinition(
        id="parallel-collect",
        version="1.0.0",
        nodes=[
            NodeDefinition(id="parallel-collector", type=NodeType.TOOL, config={"workflow_node_type": "parallel", "max_parallel": 2}),
            NodeDefinition(id="crm", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
            NodeDefinition(id="erp", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
            NodeDefinition(id="bi", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
            NodeDefinition(id="summary", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
        ],
        edges=[
            EdgeDefinition(from_node="parallel-collector", to_node="crm", on=EdgeTrigger.SUCCESS),
            EdgeDefinition(from_node="parallel-collector", to_node="erp", on=EdgeTrigger.SUCCESS),
            EdgeDefinition(from_node="parallel-collector", to_node="bi", on=EdgeTrigger.SUCCESS),
        ],
    )
    all_parallel_nodes = [
        SimpleNamespace(node_id="crm", state=SimpleNamespace(value="running")),
        SimpleNamespace(node_id="erp", state=SimpleNamespace(value="running")),
        SimpleNamespace(node_id="bi", state=SimpleNamespace(value="pending")),
        SimpleNamespace(node_id="summary", state=SimpleNamespace(value="pending")),
    ]
    executable = [
        SimpleNamespace(node_id="bi", state=SimpleNamespace(value="pending")),
        SimpleNamespace(node_id="summary", state=SimpleNamespace(value="pending")),
    ]
    selected = scheduler._select_nodes_with_parallel_limits(  # noqa: SLF001
        executable_nodes=executable,
        graph_def=parallel_graph,
        all_nodes=all_parallel_nodes,
        available_slots=2,
    )
    assert [n.node_id for n in selected] == ["summary"]


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
    collab = agent_session_state_as_dict(updated.state).get("collaboration") or {}
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
    correlation_id, chain_items = _build_execution_call_chain(root, [other, child, root])
    assert correlation_id == "cid-1"
    ids = [item.execution_id for item in chain_items]
    assert ids == ["e-root", "e-child"]
