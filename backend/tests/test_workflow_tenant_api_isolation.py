from datetime import UTC, datetime

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from core.workflows.tenant_guard import resolve_tenant_id, namespace_matches_tenant
from tests.helpers import make_fastapi_app_router_only


def _ensure_workflow_tenant(workflow: dict, tenant_id: str) -> None:
    if not namespace_matches_tenant(workflow.get("namespace"), tenant_id):
        raise HTTPException(status_code=404, detail="Workflow not found")


def _build_app(service):
    app = make_fastapi_app_router_only()

    @app.middleware("http")
    async def inject_tenant(request: Request, call_next):
        request.state.tenant_id = request.headers.get("X-Tenant-Id", "default")
        return await call_next(request)

    @app.get("/api/v1/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str, request: Request):
        tenant_id = resolve_tenant_id(request, default_tenant="default")
        wf = service.get_workflow(workflow_id, tenant_id=tenant_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        _ensure_workflow_tenant(wf, tenant_id)
        return wf

    @app.post("/api/v1/workflows/{workflow_id}/publish")
    async def publish_workflow(workflow_id: str, version_id: str, request: Request):
        tenant_id = resolve_tenant_id(request, default_tenant="default")
        wf = service.get_workflow(workflow_id, tenant_id=tenant_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        _ensure_workflow_tenant(wf, tenant_id)
        out = service.publish_workflow(workflow_id, version_id, "u1", tenant_id=tenant_id)
        if not out:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return out

    return app


def _fake_workflow(namespace: str = "tenant-a") -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "id": "wf-1",
        "namespace": namespace,
        "name": "demo",
        "description": "demo",
        "created_at": now,
        "updated_at": now,
    }


class _FakeWorkflowService:
    def __init__(self):
        self.last_get_tenant = None
        self.last_publish_tenant = None

    def get_workflow(self, workflow_id: str, tenant_id=None):
        _ = workflow_id
        self.last_get_tenant = tenant_id
        return _fake_workflow("tenant-a") if tenant_id == "tenant-a" else None

    def publish_workflow(self, workflow_id: str, version_id: str, user_id: str, tenant_id=None):
        _ = (workflow_id, version_id, user_id)
        self.last_publish_tenant = tenant_id
        return _fake_workflow("tenant-a") if tenant_id == "tenant-a" else None


def test_get_workflow_cross_tenant_returns_404():
    service = _FakeWorkflowService()
    client = TestClient(_build_app(service))

    forbidden = client.get("/api/v1/workflows/wf-1", headers={"X-Tenant-Id": "tenant-b"})
    assert forbidden.status_code == 404

    allowed = client.get("/api/v1/workflows/wf-1", headers={"X-Tenant-Id": "tenant-a"})
    assert allowed.status_code == 200
    assert allowed.json()["namespace"] == "tenant-a"
    assert service.last_get_tenant == "tenant-a"


def test_publish_workflow_uses_tenant_scoped_query():
    service = _FakeWorkflowService()
    client = TestClient(_build_app(service))

    forbidden = client.post(
        "/api/v1/workflows/wf-1/publish",
        params={"version_id": "v1"},
        headers={"X-Tenant-Id": "tenant-b"},
    )
    assert forbidden.status_code == 404

    allowed = client.post(
        "/api/v1/workflows/wf-1/publish",
        params={"version_id": "v1"},
        headers={"X-Tenant-Id": "tenant-a"},
    )
    assert allowed.status_code == 200
    assert service.last_get_tenant == "tenant-a"
    assert service.last_publish_tenant == "tenant-a"
