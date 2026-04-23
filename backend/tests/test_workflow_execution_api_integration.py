from __future__ import annotations

import asyncio
import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from typing import Optional

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
from tests.idempotency_testkit import (
    FakeClaim,
    build_fixed_idempotency_service,
    build_keyed_hash_idempotency_service,
    make_workflow_execution_create_stub,
)


def _execution_create_payload(
    *,
    question: str = "hello",
    trace_id: Optional[str] = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "workflow_id": "wf_exec_1",
        "version_id": "v-test",
        "input_data": {"question": question},
        "global_context": {},
        "trigger_type": "api",
    }
    if trace_id is not None:
        payload["global_context"] = {"trace_id": trace_id}
    return payload


def _make_session_factory(tmp_path):
    db_file = tmp_path / "workflow_execution_api.db"
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
                name="workflow-exec",
                owner_id="u1",
                lifecycle_state="active",
                acl={},
                tags=[],
                meta_data={},
            )
        )
        db.commit()


@pytest.mark.no_fallback
def test_create_and_get_execution_status_flow(tmp_path, monkeypatch, fallback_probe):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow(session_factory)
    client = _build_client(session_factory, workflows_api)

    store: dict[str, WorkflowExecution] = {}

    def _fake_create_execution(self, request, triggered_by=None):
        execution = WorkflowExecution(
            execution_id="exec_test_1",
            workflow_id=request.workflow_id,
            version_id=request.version_id or "v-test",
            state=WorkflowExecutionState.PENDING,
            input_data=request.input_data,
            global_context=request.global_context,
            node_states=[
                WorkflowExecutionNode(
                    node_id="node-1",
                    state=WorkflowExecutionNodeState.RUNNING,
                )
            ],
            trigger_type=request.trigger_type,
            triggered_by=triggered_by,
        )
        store[execution.execution_id] = execution
        return execution

    def _fake_get_execution(self, execution_id):
        return store.get(execution_id)

    monkeypatch.setattr(workflows_api.WorkflowExecutionService, "create_execution", _fake_create_execution)
    monkeypatch.setattr(workflows_api.WorkflowExecutionService, "get_execution", _fake_get_execution)
    monkeypatch.setattr(workflows_api, "_schedule_background_execution_task", lambda **kwargs: None)

    create_resp = client.post(
        "/api/v1/workflows/wf_exec_1/executions",
        params={"wait": "false"},
        json=_execution_create_payload(trace_id="t-1"),
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["execution_id"] == "exec_test_1"
    assert created["workflow_id"] == "wf_exec_1"
    assert created["state"] == "pending"
    assert created["triggered_by"] == "u1"
    assert created["node_timeline"][0]["node_id"] == "node-1"
    assert created["node_timeline"][0]["state"] == "running"

    now = datetime.now(timezone.utc)
    finished = now + timedelta(seconds=2)
    store["exec_test_1"] = store["exec_test_1"].model_copy(
        update={
            "state": WorkflowExecutionState.COMPLETED,
            "started_at": now,
            "finished_at": finished,
            "duration_ms": 2000,
            "node_states": [
                WorkflowExecutionNode(
                    node_id="node-1",
                    state=WorkflowExecutionNodeState.SUCCESS,
                    started_at=now,
                    finished_at=finished,
                )
            ],
            "output_data": {"answer": "ok"},
        }
    )

    status_resp = client.get("/api/v1/workflows/wf_exec_1/executions/exec_test_1/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["state"] == "completed"
    assert status_data["duration_ms"] == 2000
    assert status_data["node_timeline"][0]["node_id"] == "node-1"
    assert status_data["node_timeline"][0]["state"] == "success"

    detail_resp = client.get("/api/v1/workflows/wf_exec_1/executions/exec_test_1")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["state"] == "completed"
    assert detail["output_data"]["answer"] == "ok"
    assert detail["replay"]["execution_id"] == "exec_test_1"
    assert fallback_probe == []


@pytest.mark.no_fallback
def test_create_execution_idempotency_conflict_returns_structured_error(tmp_path, monkeypatch, fallback_probe):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow(session_factory)
    client = _build_client(session_factory, workflows_api)

    monkeypatch.setattr(
        workflows_api,
        "IdempotencyService",
        build_fixed_idempotency_service(FakeClaim(conflict=True, is_new=False, record_id=1)),
    )

    resp = client.post(
        "/api/v1/workflows/wf_exec_1/executions",
        params={"wait": "false"},
        headers={"Idempotency-Key": "idem-workflow-conflict"},
        json=_execution_create_payload(),
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body.get("error", {}).get("code") == "idempotency_conflict"
    assert fallback_probe == []


@pytest.mark.no_fallback
def test_create_execution_idempotency_in_progress_returns_structured_error(
    tmp_path,
    monkeypatch,
    fallback_probe,
):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow(session_factory)
    client = _build_client(session_factory, workflows_api)

    monkeypatch.setattr(
        workflows_api,
        "IdempotencyService",
        build_fixed_idempotency_service(FakeClaim(conflict=False, is_new=False, record_id=2)),
    )

    resp = client.post(
        "/api/v1/workflows/wf_exec_1/executions",
        params={"wait": "false"},
        headers={"Idempotency-Key": "idem-workflow-in-progress"},
        json=_execution_create_payload(),
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body.get("error", {}).get("code") == "idempotency_in_progress"
    assert fallback_probe == []


@pytest.mark.no_fallback
def test_create_execution_same_key_different_payload_returns_conflict(
    tmp_path,
    monkeypatch,
    fallback_probe,
):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow(session_factory)
    client = _build_client(session_factory, workflows_api)

    monkeypatch.setattr(
        workflows_api,
        "IdempotencyService",
        build_keyed_hash_idempotency_service(record_id=9),
    )
    monkeypatch.setattr(
        workflows_api.WorkflowExecutionService,
        "create_execution",
        make_workflow_execution_create_stub("exec_hash_1"),
    )
    monkeypatch.setattr(workflows_api, "_schedule_background_execution_task", lambda **kwargs: None)

    headers = {"Idempotency-Key": "idem-workflow-hash-mismatch"}
    payload_a = _execution_create_payload(question="hello")
    payload_b = _execution_create_payload(question="changed")

    resp_a = client.post(
        "/api/v1/workflows/wf_exec_1/executions",
        params={"wait": "false"},
        headers=headers,
        json=payload_a,
    )
    assert resp_a.status_code == 201

    resp_b = client.post(
        "/api/v1/workflows/wf_exec_1/executions",
        params={"wait": "false"},
        headers=headers,
        json=payload_b,
    )
    assert resp_b.status_code == 409
    body = resp_b.json()
    assert body.get("error", {}).get("code") == "idempotency_conflict"
    assert fallback_probe == []
