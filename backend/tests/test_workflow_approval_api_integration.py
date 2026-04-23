from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import importlib
import sys
import types
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.data.base import Base
from core.data.models.workflow import (
    WorkflowORM,
    WorkflowExecutionORM,
    WorkflowApprovalTaskORM,
)
from api.errors import register_error_handlers


def _make_session_factory(tmp_path):
    db_file = tmp_path / "workflow_approval_api.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _load_workflows_api_module():
    runtime_stub = types.ModuleType("core.workflows.runtime")
    runtime_stub.__path__ = []  # mark as package for submodule imports

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


def _seed_workflow_execution_and_task(session_factory, *, task_status: str = "pending", expires_at=None):
    execution_id = f"exec_{uuid.uuid4().hex[:8]}"
    task_id = str(uuid.uuid4())
    with session_factory() as db:
        db.add(
            WorkflowORM(
                id="wf_1",
                namespace="default",
                name="wf",
                owner_id="u1",
                lifecycle_state="active",
                acl={},
                tags=[],
                meta_data={},
            )
        )
        db.add(
            WorkflowExecutionORM(
                execution_id=execution_id,
                workflow_id="wf_1",
                version_id="v1",
                state="paused",
                input_data={},
                output_data={},
                global_context={},
                node_states_json="[]",
                triggered_by="u1",
                trigger_type="manual",
                resource_quota={},
            )
        )
        db.add(
            WorkflowApprovalTaskORM(
                id=task_id,
                execution_id=execution_id,
                workflow_id="wf_1",
                node_id="approval_1",
                title="Approve",
                reason="Need approval",
                payload={},
                status=task_status,
                requested_by="u1",
                expires_at=expires_at,
            )
        )
        db.commit()
    return execution_id, task_id


def test_list_approvals_api(tmp_path):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    execution_id, _ = _seed_workflow_execution_and_task(session_factory)
    client = _build_client(session_factory, workflows_api)

    resp = client.get(f"/api/v1/workflows/wf_1/executions/{execution_id}/approvals")
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_id"] == execution_id
    assert data["execution_state"] == "paused"
    assert isinstance(data["items"], list)
    assert len(data["items"]) == 1
    assert data["items"][0]["status"] == "pending"
    assert data["items"][0]["node_id"] == "approval_1"

    legacy_resp = client.get(
        f"/api/v1/workflows/wf_1/executions/{execution_id}/approvals",
        params={"legacy": "true"},
    )
    assert legacy_resp.status_code == 200
    assert legacy_resp.headers.get("X-API-Deprecated") == workflows_api.settings.workflow_approvals_legacy_deprecated_header
    assert legacy_resp.headers.get("Sunset") == workflows_api.settings.workflow_approvals_legacy_sunset
    legacy_data = legacy_resp.json()
    assert isinstance(legacy_data, list)
    assert len(legacy_data) == 1
    assert legacy_data[0]["status"] == "pending"


def test_approve_moves_execution_to_pending_and_records_decision(tmp_path, monkeypatch):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    execution_id, task_id = _seed_workflow_execution_and_task(session_factory)
    client = _build_client(session_factory, workflows_api)

    monkeypatch.setattr(workflows_api, "SessionLocal", session_factory)
    scheduled = {"called": False}

    class _DummyTask:
        pass

    def _fake_create_task(coro):
        scheduled["called"] = True
        coro.close()
        return _DummyTask()

    monkeypatch.setattr(workflows_api.asyncio, "create_task", _fake_create_task)

    resp = client.post(
        f"/api/v1/workflows/wf_1/executions/{execution_id}/approvals/{task_id}/approve"
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert resp.json()["execution_state_after_decision"] == "pending"
    assert scheduled["called"] is True

    with session_factory() as db:
        execution = (
            db.query(WorkflowExecutionORM)
            .filter(WorkflowExecutionORM.execution_id == execution_id)
            .first()
        )
        assert execution is not None
        assert execution.state == "pending"
        assert (execution.global_context or {}).get("approval_decisions", {}).get("approval_1") == "approved"


def test_reject_marks_execution_failed(tmp_path):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    execution_id, task_id = _seed_workflow_execution_and_task(session_factory)
    client = _build_client(session_factory, workflows_api)

    resp = client.post(
        f"/api/v1/workflows/wf_1/executions/{execution_id}/approvals/{task_id}/reject"
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert resp.json()["execution_state_after_decision"] == "failed"

    with session_factory() as db:
        execution = (
            db.query(WorkflowExecutionORM)
            .filter(WorkflowExecutionORM.execution_id == execution_id)
            .first()
        )
        assert execution is not None
        assert execution.state == "failed"


def test_approve_expired_task_returns_409_and_fails_execution(tmp_path):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    execution_id, task_id = _seed_workflow_execution_and_task(
        session_factory,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=60),
    )
    client = _build_client(session_factory, workflows_api)

    resp = client.post(
        f"/api/v1/workflows/wf_1/executions/{execution_id}/approvals/{task_id}/approve"
    )
    assert resp.status_code == 409
    assert resp.json().get("error", {}).get("code") == "workflow_approval_task_expired"

    with session_factory() as db:
        task = db.query(WorkflowApprovalTaskORM).filter(WorkflowApprovalTaskORM.id == task_id).first()
        execution = (
            db.query(WorkflowExecutionORM)
            .filter(WorkflowExecutionORM.execution_id == execution_id)
            .first()
        )
        assert task is not None and task.status == "expired"
        assert execution is not None and execution.state == "failed"


def test_get_execution_not_found_returns_structured_error(tmp_path):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow_execution_and_task(session_factory)
    client = _build_client(session_factory, workflows_api)

    resp = client.get("/api/v1/workflows/wf_1/executions/exec_not_exists")
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("detail") == "Execution not found"
    assert body.get("error", {}).get("code") == "workflow_execution_not_found"


def test_get_execution_status_not_found_returns_structured_error(tmp_path):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow_execution_and_task(session_factory)
    client = _build_client(session_factory, workflows_api)

    resp = client.get("/api/v1/workflows/wf_1/executions/exec_not_exists/status")
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("detail") == "Execution not found"
    assert body.get("error", {}).get("code") == "workflow_execution_not_found"


def test_list_execution_approvals_not_found_returns_structured_error(tmp_path):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow_execution_and_task(session_factory)
    client = _build_client(session_factory, workflows_api)

    resp = client.get("/api/v1/workflows/wf_1/executions/exec_not_exists/approvals")
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("detail") == "Execution not found"
    assert body.get("error", {}).get("code") == "workflow_execution_not_found"


def test_reconcile_execution_not_found_returns_structured_error(tmp_path):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow_execution_and_task(session_factory)
    client = _build_client(session_factory, workflows_api)

    resp = client.post("/api/v1/workflows/wf_1/executions/exec_not_exists/reconcile")
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("detail") == "Execution not found"
    assert body.get("error", {}).get("code") == "workflow_execution_not_found"


def test_get_quota_workflow_not_found_returns_structured_error(tmp_path):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    client = _build_client(session_factory, workflows_api)

    resp = client.get("/api/v1/workflows/wf_not_exists/quota")
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("detail") == "Workflow not found"
    assert body.get("error", {}).get("code") == "workflow_not_found"


def test_set_governance_invalid_strategy_returns_structured_error(tmp_path):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow_execution_and_task(session_factory)
    client = _build_client(session_factory, workflows_api)

    resp = client.put(
        "/api/v1/workflows/wf_1/governance",
        json={"max_queue_size": 10, "backpressure_strategy": "invalid"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("detail") == "backpressure_strategy must be wait or reject"
    assert body.get("error", {}).get("code") == "workflow_governance_invalid_backpressure_strategy"


@pytest.mark.no_fallback
def test_get_workflow_not_found_returns_structured_error(tmp_path, fallback_probe):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    client = _build_client(session_factory, workflows_api)

    resp = client.get("/api/v1/workflows/wf_not_exists")
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("detail") == "Workflow not found"
    assert body.get("error", {}).get("code") == "workflow_not_found"
    assert fallback_probe == []


def test_get_version_not_found_returns_structured_error(tmp_path):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow_execution_and_task(session_factory)
    client = _build_client(session_factory, workflows_api)

    resp = client.get("/api/v1/workflows/wf_1/versions/v_nonexistent")
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("detail") == "Version not found"
    assert body.get("error", {}).get("code") == "workflow_version_not_found"


def test_diff_versions_from_missing_returns_structured_error(tmp_path):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow_execution_and_task(session_factory)
    client = _build_client(session_factory, workflows_api)

    resp = client.get(
        "/api/v1/workflows/wf_1/versions/compare",
        params={"from_version_id": "v_bad", "to_version_id": "v_bad2"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("detail") == "from_version not found"
    assert body.get("error", {}).get("code") == "workflow_diff_from_version_not_found"
