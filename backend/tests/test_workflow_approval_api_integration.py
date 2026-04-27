from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
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
    WorkflowVersionORM,
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


def _seed_workflow_versions_for_impact(session_factory):
    target_version_id = f"v_target_{uuid.uuid4().hex[:6]}"
    with session_factory() as db:
        db.add(
            WorkflowVersionORM(
                version_id=target_version_id,
                workflow_id="wf_1",
                definition_id="def_target",
                version_number="1.0.0",
                dag_json=json.dumps({"nodes": [], "edges": [], "entry_node": None, "global_config": {}}),
                checksum="c1",
                state="published",
                created_by="u1",
            )
        )
        db.add(
            WorkflowVersionORM(
                version_id=f"v_parent_fixed_{uuid.uuid4().hex[:6]}",
                workflow_id="wf_parent_fixed",
                definition_id="def_pf",
                version_number="1.0.0",
                dag_json=json.dumps(
                    {
                        "nodes": [
                            {
                                "id": "sub1",
                                "type": "tool",
                                "config": {
                                    "workflow_node_type": "sub_workflow",
                                    "target_workflow_id": "wf_1",
                                    "target_version_selector": "fixed",
                                    "target_version_id": target_version_id,
                                },
                            }
                        ],
                        "edges": [],
                        "entry_node": "sub1",
                        "global_config": {},
                    }
                ),
                checksum="c2",
                state="published",
                created_by="u1",
            )
        )
        db.add(
            WorkflowVersionORM(
                version_id=f"v_parent_latest_{uuid.uuid4().hex[:6]}",
                workflow_id="wf_parent_latest",
                definition_id="def_pl",
                version_number="1.0.0",
                dag_json=json.dumps(
                    {
                        "nodes": [
                            {
                                "id": "sub2",
                                "type": "tool",
                                "config": {
                                    "workflow_node_type": "sub_workflow",
                                    "target_workflow_id": "wf_1",
                                    "target_version_selector": "latest",
                                },
                            }
                        ],
                        "edges": [],
                        "entry_node": "sub2",
                        "global_config": {},
                    }
                ),
                checksum="c3",
                state="draft",
                created_by="u1",
            )
        )
        db.commit()
    return target_version_id


def _seed_versions_for_publish_breaking_guard(session_factory):
    def _dag_json(global_config: dict) -> str:
        return json.dumps(
            {"nodes": [], "edges": [], "entry_node": None, "global_config": global_config},
            separators=(",", ":"),
        )

    baseline_json = _dag_json(
        {
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
    )
    new_json = _dag_json(
        {
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
    )
    parent_json = json.dumps(
        {
            "nodes": [
                {
                    "id": "sub1",
                    "type": "tool",
                    "config": {
                        "workflow_node_type": "sub_workflow",
                        "target_workflow_id": "wf_1",
                        "target_version_selector": "fixed",
                        "target_version_id": "v_target_new",
                    },
                }
            ],
            "edges": [],
            "entry_node": "sub1",
            "global_config": {},
        },
        separators=(",", ":"),
    )

    with session_factory() as db:
        db.add(
            WorkflowVersionORM(
                version_id="v_target_base",
                workflow_id="wf_1",
                definition_id="def_target_base",
                version_number="1.0.0",
                dag_json=baseline_json,
                checksum=hashlib.sha256(baseline_json.encode()).hexdigest(),
                state="published",
                created_by="u1",
            )
        )
        db.add(
            WorkflowVersionORM(
                version_id="v_target_new",
                workflow_id="wf_1",
                definition_id="def_target_new",
                version_number="1.0.1",
                dag_json=new_json,
                checksum=hashlib.sha256(new_json.encode()).hexdigest(),
                state="draft",
                created_by="u1",
            )
        )
        db.add(
            WorkflowVersionORM(
                version_id="v_parent_fixed_guard",
                workflow_id="wf_parent_guard",
                definition_id="def_parent_guard",
                version_number="1.0.0",
                dag_json=parent_json,
                checksum=hashlib.sha256(parent_json.encode()).hexdigest(),
                state="published",
                created_by="u1",
            )
        )
        db.commit()


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


def test_workflow_impact_api_supports_risk_summary_and_published_filter(tmp_path):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow_execution_and_task(session_factory)
    target_version_id = _seed_workflow_versions_for_impact(session_factory)
    client = _build_client(session_factory, workflows_api)

    resp_all = client.get(
        "/api/v1/workflows/wf_1/impact",
        params={"target_version_id": target_version_id},
    )
    assert resp_all.status_code == 200
    data_all = resp_all.json()
    assert data_all["total_impacted"] == 2
    assert data_all["risk_summary"]["compatible"] == 1
    assert data_all["risk_summary"]["risky"] == 1

    resp_published = client.get(
        "/api/v1/workflows/wf_1/impact",
        params={"target_version_id": target_version_id, "published_only": "true"},
    )
    assert resp_published.status_code == 200
    data_published = resp_published.json()
    assert data_published["include_only_published"] is True
    assert data_published["total_impacted"] == 1
    assert data_published["risk_summary"]["compatible"] == 1
    assert data_published["risk_summary"]["risky"] == 0


def test_execution_call_chain_api_returns_parent_child_links(tmp_path):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    execution_id, _ = _seed_workflow_execution_and_task(session_factory)
    child_execution_id = f"exec_child_{uuid.uuid4().hex[:8]}"
    child_node_states = json.dumps(
        [
            {
                "node_id": "worker_node_1",
                "state": "success",
                "output_data": {
                    "type": "agent_result",
                    "agent_id": "agent.worker",
                    "agent_session_id": "sess_worker_1",
                    "collaboration_messages": [
                        {
                            "sender": "agent.manager",
                            "receiver": "agent.worker",
                            "task_id": f"{execution_id}:agent_node_1",
                            "status": "running",
                            "timestamp": "2026-01-01T00:00:00Z",
                            "content": {"event": "attempt_started", "stage": "primary", "attempt": 1},
                        },
                        {
                            "sender": "agent.manager",
                            "receiver": "agent.worker.backup",
                            "task_id": f"{execution_id}:agent_node_1",
                            "status": "success",
                            "timestamp": "2026-01-01T00:00:01Z",
                            "content": {"event": "fallback_succeeded", "stage": "fallback", "attempt": 1},
                        },
                    ],
                    "recovery": {
                        "recovery_mode": "fallback_agent",
                        "fallback_used": True,
                        "fallback_agent_id": "agent.worker.backup",
                        "recovery_trace": [
                            {"attempt": 1, "stage": "primary", "status": "error"},
                            {"attempt": 1, "stage": "fallback", "status": "success"},
                        ],
                    },
                },
                "input_data": {},
                "error_message": None,
                "error_details": None,
                "retry_count": 0,
                "started_at": None,
                "finished_at": None,
            }
        ]
    )
    with session_factory() as db:
        db.add(
            WorkflowExecutionORM(
                execution_id=child_execution_id,
                workflow_id="wf_child",
                version_id="v1",
                state="completed",
                input_data={},
                output_data={},
                global_context={
                    "correlation_id": f"wfex_{execution_id}",
                    "parent_execution_id": execution_id,
                    "parent_node_id": "sub_node_1",
                },
                node_states_json=child_node_states,
                triggered_by="u1",
                trigger_type="workflow",
                resource_quota={},
            )
        )
        db.commit()
    client = _build_client(session_factory, workflows_api)
    resp = client.get(f"/api/v1/workflows/wf_1/executions/{execution_id}/call-chain")
    assert resp.status_code == 200
    data = resp.json()
    ids = [item["execution_id"] for item in data["items"]]
    assert execution_id in ids
    assert child_execution_id in ids
    child_item = next(item for item in data["items"] if item["execution_id"] == child_execution_id)
    assert len(child_item["recovery_summaries"]) == 1
    assert child_item["recovery_summaries"][0]["recovery"]["fallback_used"] is True
    assert len(child_item["collaboration_summaries"]) == 1
    collab = child_item["collaboration_summaries"][0]
    assert collab["message_total"] == 2
    assert collab["status_counts"]["running"] == 1
    assert collab["stage_counts"]["fallback"] == 1


def test_publish_version_blocks_on_subworkflow_breaking_impact(tmp_path):
    workflows_api = _load_workflows_api_module()
    session_factory = _make_session_factory(tmp_path)
    _seed_workflow_execution_and_task(session_factory)
    _seed_versions_for_publish_breaking_guard(session_factory)
    client = _build_client(session_factory, workflows_api)

    resp = client.post("/api/v1/workflows/wf_1/versions/v_target_new/publish")
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("error", {}).get("code") == "workflow_version_publish_invalid"
    assert "breaking contract change" in str(body.get("detail") or "").lower()
