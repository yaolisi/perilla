from __future__ import annotations

import asyncio
import importlib
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.errors import register_error_handlers
from core.data.base import Base
from core.data.models.workflow import WorkflowORM
from core.workflows.models.workflow_execution import (
    WorkflowExecution,
    WorkflowExecutionNode,
    WorkflowExecutionNodeState,
    WorkflowExecutionState,
)
from core.workflows.runtime.workflow_runtime import WorkflowRuntime
from execution_kernel.engine.context import GraphContext
from execution_kernel.engine.scheduler import Scheduler
from execution_kernel.models.graph_definition import EdgeDefinition, EdgeTrigger, GraphDefinition, NodeDefinition, NodeType


def _make_session_factory(tmp_path):
    db_file = tmp_path / "workflow_control_flow_regression.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _load_workflows_api_module():
    runtime_stub = types.ModuleType("core.workflows.runtime")
    runtime_stub.__path__ = []

    class _WorkflowRuntimeStub:
        def __init__(self, db, execution_manager):
            self.db = db
            self.execution_manager = execution_manager

        async def execute(self, execution, wait_for_completion=False, **kwargs):
            await asyncio.sleep(0)
            return execution

    runtime_stub.WorkflowRuntime = _WorkflowRuntimeStub
    adapter_stub = types.ModuleType("core.workflows.runtime.graph_runtime_adapter")

    class _GraphRuntimeAdapterStub:
        @staticmethod
        async def extract_execution_result_from_kernel(*args, **kwargs):
            return {}

    adapter_stub.GraphRuntimeAdapter = _GraphRuntimeAdapterStub
    sys.modules["core.workflows.runtime"] = runtime_stub
    sys.modules["core.workflows.runtime.graph_runtime_adapter"] = adapter_stub
    sys.modules.pop("api.workflows", None)
    return importlib.import_module("api.workflows")


def _build_client(session_factory, workflows_api):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(workflows_api.router)

    def _override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[workflows_api.get_db] = _override_get_db
    app.dependency_overrides[workflows_api.get_current_user] = lambda: "u1"
    return TestClient(app)


def _seed_workflow(session_factory):
    with session_factory() as db:
        db.add(
            WorkflowORM(
                id="wf_exec_1",
                namespace="default",
                name="workflow-control-flow",
                owner_id="u1",
                lifecycle_state="active",
                acl={},
                tags=[],
                meta_data={},
            )
        )
        db.commit()


def _execution_create_payload(question: str = "control-flow-regression") -> dict[str, object]:
    return {
        "workflow_id": "wf_exec_1",
        "version_id": "v-test",
        "input_data": {"question": question},
        "global_context": {},
        "trigger_type": "api",
    }


@pytest.mark.asyncio
async def test_runtime_loop_and_scheduler_parallel_regression(monkeypatch) -> None:
    runtime = object.__new__(WorkflowRuntime)
    context = GraphContext(global_data={"input_data": {}}, node_outputs={}, current_node_input={})

    async def _fake_body(self, *, node_def, body_cfg, input_data, context):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0)
        remaining = int(input_data.get("remaining", 0))
        return {"remaining": max(0, remaining - 1)}

    monkeypatch.setattr(runtime, "_execute_loop_body", types.MethodType(_fake_body, runtime))
    loop_result = await runtime._execute_loop_control_node(  # noqa: SLF001
        node_def=types.SimpleNamespace(id="loop-regression"),
        input_data={"remaining": 5},
        context=context,
        cfg={
            "loop_type": "while",
            "condition_expression": "${input.remaining} > 0",
            "max_iterations": 10,
            "loop_body": {"type": "tool"},
        },
    )
    assert loop_result["iterations"] == 5
    assert loop_result["remaining"] == 0

    scheduler = object.__new__(Scheduler)
    graph_def = GraphDefinition(
        id="g-regression",
        version="1.0.0",
        nodes=[
            NodeDefinition(id="parallel-1", type=NodeType.TOOL, config={"workflow_node_type": "parallel", "max_parallel": 2}),
            NodeDefinition(id="a", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
            NodeDefinition(id="b", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
            NodeDefinition(id="c", type=NodeType.TOOL, config={"workflow_node_type": "tool"}),
        ],
        edges=[
            EdgeDefinition(from_node="parallel-1", to_node="a", on=EdgeTrigger.SUCCESS),
            EdgeDefinition(from_node="parallel-1", to_node="b", on=EdgeTrigger.SUCCESS),
            EdgeDefinition(from_node="parallel-1", to_node="c", on=EdgeTrigger.SUCCESS),
        ],
    )
    all_nodes = [
        types.SimpleNamespace(node_id="a", state=types.SimpleNamespace(value="running")),
        types.SimpleNamespace(node_id="b", state=types.SimpleNamespace(value="running")),
        types.SimpleNamespace(node_id="c", state=types.SimpleNamespace(value="pending")),
    ]
    selected = scheduler._select_nodes_with_parallel_limits(  # noqa: SLF001
        executable_nodes=[types.SimpleNamespace(node_id="c", state=types.SimpleNamespace(value="pending"))],
        graph_def=graph_def,
        all_nodes=all_nodes,
        available_slots=1,
    )
    assert selected == []


@pytest.mark.no_fallback
def test_api_wait_true_control_flow_success_regression(tmp_path, monkeypatch, fallback_probe):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow(session_factory)
    client = _build_client(session_factory, workflows_api)

    def _fake_create_execution(self, request, triggered_by=None):
        return WorkflowExecution(
            execution_id="exec_reg_success",
            workflow_id=request.workflow_id,
            version_id=request.version_id or "v-test",
            state=WorkflowExecutionState.PENDING,
            input_data=request.input_data,
            global_context=request.global_context,
            node_states=[WorkflowExecutionNode(node_id="loop-sync", state=WorkflowExecutionNodeState.PENDING)],
            trigger_type=request.trigger_type,
            triggered_by=triggered_by,
        )

    async def _fake_runtime_execute(self, execution, wait_for_completion=False, **kwargs):
        await asyncio.sleep(0)
        assert wait_for_completion is True
        return execution.model_copy(
            update={
                "state": WorkflowExecutionState.COMPLETED,
                "started_at": datetime.now(timezone.utc),
                "finished_at": datetime.now(timezone.utc) + timedelta(seconds=1),
                "output_data": {"iterations": 30, "parallel_limit": 3, "approval_path": "ceo"},
                "node_states": [
                    WorkflowExecutionNode(
                        node_id="loop-sync",
                        state=WorkflowExecutionNodeState.SUCCESS,
                        output_data={"type": "loop_result", "iterations": 30},
                    )
                ],
            }
        )

    monkeypatch.setattr(workflows_api.WorkflowExecutionService, "create_execution", _fake_create_execution)
    monkeypatch.setattr(workflows_api.WorkflowRuntime, "execute", _fake_runtime_execute)

    resp = client.post(
        "/api/v1/workflows/wf_exec_1/executions",
        params={"wait": "true", "wait_timeout_seconds": 60},
        json=_execution_create_payload(),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["state"] == "completed"
    assert body["output_data"]["iterations"] == 30
    assert body["output_data"]["parallel_limit"] == 3
    assert body["output_data"]["approval_path"] == "ceo"
    assert fallback_probe == []


@pytest.mark.no_fallback
def test_api_wait_true_loop_failure_regression(tmp_path, monkeypatch, fallback_probe):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow(session_factory)
    client = _build_client(session_factory, workflows_api)

    def _fake_create_execution(self, request, triggered_by=None):
        return WorkflowExecution(
            execution_id="exec_reg_loop_fail",
            workflow_id=request.workflow_id,
            version_id=request.version_id or "v-test",
            state=WorkflowExecutionState.PENDING,
            input_data=request.input_data,
            global_context=request.global_context,
            node_states=[WorkflowExecutionNode(node_id="loop-sync", state=WorkflowExecutionNodeState.PENDING)],
            trigger_type=request.trigger_type,
            triggered_by=triggered_by,
        )

    async def _fake_runtime_execute_raise(self, execution, wait_for_completion=False, **kwargs):
        await asyncio.sleep(0)
        assert wait_for_completion is True
        raise RuntimeError("LOOP_NODE_EXECUTION_FAILED: node=loop-sync, iteration=7, error=mock-failure")

    monkeypatch.setattr(workflows_api.WorkflowExecutionService, "create_execution", _fake_create_execution)
    monkeypatch.setattr(workflows_api.WorkflowRuntime, "execute", _fake_runtime_execute_raise)

    resp = client.post(
        "/api/v1/workflows/wf_exec_1/executions",
        params={"wait": "true", "wait_timeout_seconds": 60},
        json=_execution_create_payload("loop-failure"),
    )
    assert resp.status_code == 500
    detail = str(resp.json().get("detail") or "")
    assert "LOOP_NODE_EXECUTION_FAILED" in detail
    assert "loop-sync" in detail
    assert fallback_probe == []
