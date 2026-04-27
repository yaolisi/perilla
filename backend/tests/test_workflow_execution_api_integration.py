from __future__ import annotations

import asyncio
import importlib
import io
import json
import sys
import types
import zipfile
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
def test_create_execution_wait_true_returns_completed_control_flow_output(
    tmp_path,
    monkeypatch,
    fallback_probe,
):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow(session_factory)
    client = _build_client(session_factory, workflows_api)

    def _fake_create_execution(self, request, triggered_by=None):
        return WorkflowExecution(
            execution_id="exec_wait_true_1",
            workflow_id=request.workflow_id,
            version_id=request.version_id or "v-test",
            state=WorkflowExecutionState.PENDING,
            input_data=request.input_data,
            global_context=request.global_context,
            node_states=[
                WorkflowExecutionNode(
                    node_id="parallel-gate",
                    state=WorkflowExecutionNodeState.PENDING,
                ),
                WorkflowExecutionNode(
                    node_id="loop-sync",
                    state=WorkflowExecutionNodeState.PENDING,
                ),
            ],
            trigger_type=request.trigger_type,
            triggered_by=triggered_by,
        )

    async def _fake_runtime_execute(self, execution, wait_for_completion=False, **kwargs):
        await asyncio.sleep(0)
        assert wait_for_completion is True
        assert kwargs.get("wait_timeout_seconds") == 45
        now = datetime.now(timezone.utc)
        return execution.model_copy(
            update={
                "state": WorkflowExecutionState.COMPLETED,
                "started_at": now,
                "finished_at": now + timedelta(seconds=1),
                "duration_ms": 1000,
                "node_states": [
                    WorkflowExecutionNode(
                        node_id="parallel-gate",
                        state=WorkflowExecutionNodeState.SUCCESS,
                        output_data={
                            "type": "parallel_gate",
                            "__workflow_parallel_meta": {"max_parallel": 3},
                        },
                    ),
                    WorkflowExecutionNode(
                        node_id="loop-sync",
                        state=WorkflowExecutionNodeState.SUCCESS,
                        output_data={
                            "type": "loop_result",
                            "iterations": 30,
                            "exit_reason": "condition_false",
                        },
                    ),
                ],
                "output_data": {
                    "approval_path": "ceo",
                    "parallel_limit": 3,
                    "iterations": 30,
                },
            }
        )

    monkeypatch.setattr(workflows_api.WorkflowExecutionService, "create_execution", _fake_create_execution)
    monkeypatch.setattr(workflows_api.WorkflowRuntime, "execute", _fake_runtime_execute)

    resp = client.post(
        "/api/v1/workflows/wf_exec_1/executions",
        params={"wait": "true", "wait_timeout_seconds": 45},
        json=_execution_create_payload(question="enterprise control flow"),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["state"] == "completed"
    assert body["output_data"]["approval_path"] == "ceo"
    assert body["output_data"]["parallel_limit"] == 3
    assert body["output_data"]["iterations"] == 30
    node_states = {item["node_id"]: item for item in body["node_timeline"]}
    assert node_states["parallel-gate"]["state"] == "success"
    assert node_states["loop-sync"]["state"] == "success"
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
def test_create_execution_wait_true_returns_structured_loop_failure_error(
    tmp_path,
    monkeypatch,
    fallback_probe,
):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow(session_factory)
    client = _build_client(session_factory, workflows_api)

    def _fake_create_execution(self, request, triggered_by=None):
        return WorkflowExecution(
            execution_id="exec_wait_true_loop_fail",
            workflow_id=request.workflow_id,
            version_id=request.version_id or "v-test",
            state=WorkflowExecutionState.PENDING,
            input_data=request.input_data,
            global_context=request.global_context,
            node_states=[
                WorkflowExecutionNode(
                    node_id="loop-sync",
                    state=WorkflowExecutionNodeState.PENDING,
                ),
            ],
            trigger_type=request.trigger_type,
            triggered_by=triggered_by,
        )

    async def _fake_runtime_execute_raise(self, execution, wait_for_completion=False, **kwargs):
        await asyncio.sleep(0)
        assert wait_for_completion is True
        assert kwargs.get("wait_timeout_seconds") == 30
        raise RuntimeError(
            "LOOP_NODE_EXECUTION_FAILED: node=loop-sync, iteration=5, error=transient downstream error"
        )

    monkeypatch.setattr(workflows_api.WorkflowExecutionService, "create_execution", _fake_create_execution)
    monkeypatch.setattr(workflows_api.WorkflowRuntime, "execute", _fake_runtime_execute_raise)

    resp = client.post(
        "/api/v1/workflows/wf_exec_1/executions",
        params={"wait": "true", "wait_timeout_seconds": 30},
        json=_execution_create_payload(question="loop should fail"),
    )
    assert resp.status_code == 500
    body = resp.json()
    detail = str(body.get("detail") or "")
    assert "LOOP_NODE_EXECUTION_FAILED" in detail
    assert "loop-sync" in detail
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


@pytest.mark.no_fallback
def test_failure_report_endpoint_returns_audit_and_hash_fields(tmp_path, monkeypatch, fallback_probe):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow(session_factory)
    client = _build_client(session_factory, workflows_api)

    now = datetime.now(timezone.utc)
    execution = WorkflowExecution(
        execution_id="exec_failure_report_1",
        workflow_id="wf_exec_1",
        version_id="v-test",
        state=WorkflowExecutionState.FAILED,
        graph_instance_id="gi_1",
        input_data={"question": "x"},
        global_context={"env": "test"},
        error_details={"recovery_actions": [{"kind": "alert", "status": "ok"}], "api_key": "secret"},
        created_at=now,
        started_at=now,
        finished_at=now + timedelta(seconds=1),
        duration_ms=1000,
        node_states=[],
    )

    monkeypatch.setattr(workflows_api.WorkflowExecutionService, "get_execution", lambda self, _eid: execution)

    async def _fake_hydrate(ex):
        return ex

    async def _fake_timeline(_instance_id):
        return [{"node_id": "n1", "state": "failed"}]

    async def _fake_errors(**kwargs):
        return [{"node_id": "n1", "error_type": "RuntimeError"}]

    monkeypatch.setattr(workflows_api, "_hydrate_execution_live_from_kernel", _fake_hydrate)
    monkeypatch.setattr(workflows_api, "_node_timeline_from_event_store", _fake_timeline)
    monkeypatch.setattr(workflows_api, "_execution_error_logs_from_event_store", _fake_errors)

    resp = client.get("/api/v1/workflows/wf_exec_1/executions/exec_failure_report_1/failure-report")
    assert resp.status_code == 200
    body = resp.json()
    assert body["report_schema_version"] == "1.1"
    assert body["redaction_applied"] is True
    assert isinstance(body["redacted_key_count"], int)
    assert isinstance(body["report_sha256"], str) and len(body["report_sha256"]) == 64
    assert body["global_error_details"]["api_key"] == "***REDACTED***"
    assert body["recovery_actions"][0]["kind"] == "alert"
    assert fallback_probe == []


@pytest.mark.no_fallback
def test_failure_report_archive_endpoint_returns_headers_and_zip_payload(tmp_path, monkeypatch, fallback_probe):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow(session_factory)
    client = _build_client(session_factory, workflows_api)

    execution = WorkflowExecution(
        execution_id="exec_failure_bundle_1",
        workflow_id="wf_exec_1",
        version_id="v-test",
        state=WorkflowExecutionState.FAILED,
        graph_instance_id="gi_bundle_1",
        input_data={},
        global_context={},
        node_states=[],
    )
    monkeypatch.setattr(workflows_api.WorkflowExecutionService, "get_execution", lambda self, _eid: execution)

    async def _fake_hydrate(ex):
        return ex

    async def _fake_timeline(_instance_id):
        return [{"node_id": "n1", "state": "failed"}]

    async def _fake_errors(**kwargs):
        return [{"node_id": "n1", "error_type": "RuntimeError"}]

    async def _fake_events(_instance_id):
        return [{"event_id": "e1", "payload": {"token": "secret"}}]

    monkeypatch.setattr(workflows_api, "_hydrate_execution_live_from_kernel", _fake_hydrate)
    monkeypatch.setattr(workflows_api, "_node_timeline_from_event_store", _fake_timeline)
    monkeypatch.setattr(workflows_api, "_execution_error_logs_from_event_store", _fake_errors)
    monkeypatch.setattr(workflows_api, "_execution_events_from_event_store", _fake_events)

    resp = client.get("/api/v1/workflows/wf_exec_1/executions/exec_failure_bundle_1/failure-report/archive")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/zip")
    assert resp.headers.get("x-report-schema-version") == "1.1"
    assert resp.headers.get("x-redaction-applied") == "true"
    assert resp.headers.get("x-redacted-key-count") is not None
    assert isinstance(resp.headers.get("x-report-sha256"), str)

    with zipfile.ZipFile(io.BytesIO(resp.content), "r") as zf:
        names = set(zf.namelist())
        assert {"README.txt", "failure-report.json", "failure-report.sha256", "execution-events.json"}.issubset(
            names
        )
        report_payload = json.loads(zf.read("failure-report.json").decode("utf-8"))
        events_payload = json.loads(zf.read("execution-events.json").decode("utf-8"))
        readme = zf.read("README.txt").decode("utf-8")
        assert report_payload["report_schema_version"] == "1.1"
        assert report_payload["report_sha256"] == resp.headers.get("x-report-sha256")
        assert zf.read("failure-report.sha256").decode("utf-8").strip() == resp.headers.get("x-report-sha256")
        assert events_payload[0]["payload"]["token"] == "***REDACTED***"
        assert "report_sha256:" in readme
    assert fallback_probe == []
