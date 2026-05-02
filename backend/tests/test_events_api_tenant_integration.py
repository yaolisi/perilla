"""GET /api/events/instance/{id}：workflow_executions 租户门禁 + 共享 SQLite 集成。"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api import events as events_api
from config.settings import settings
from core.data.base import Base as CoreBase
from core.data.models.workflow import WorkflowExecutionORM
from execution_kernel.events.event_store import EventStore
from execution_kernel.events.event_types import ExecutionEventType
from execution_kernel.persistence.db import Database
from tests.helpers import make_fastapi_app_router_only

pytestmark = [pytest.mark.tenant_isolation, pytest.mark.no_fallback]


def _build_shared_db(tmp_path):
    db_file = tmp_path / "events_api_tenant.db"
    sync_url = f"sqlite:///{db_file}"
    async_url = f"sqlite+aiosqlite:///{db_file}"
    sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False})
    CoreBase.metadata.create_all(bind=sync_engine)
    ek_db = Database(async_url)
    asyncio.run(ek_db.create_tables())
    SessionSync = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return ek_db, SessionSync, sync_engine


async def _emit_graph_started(db_ek: Database, instance_id: str) -> None:
    async with db_ek.async_session() as session:
        store = EventStore(session)
        await store.emit_event(
            instance_id,
            ExecutionEventType.GRAPH_STARTED,
            {"graph_id": "g_integration", "initial_context": {}},
        )


def test_get_instance_events_respects_workflow_execution_tenant(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    ek_db, SessionSync, sync_engine = _build_shared_db(tmp_path)
    monkeypatch.setattr(events_api, "_get_db", lambda: ek_db)
    monkeypatch.setattr(events_api, "get_events_strict_workflow_binding", lambda: False)

    @contextmanager
    def _scoped_session():
        s = SessionSync()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(events_api, "db_session", _scoped_session)

    gi = str(uuid.uuid4())
    exec_id = str(uuid.uuid4())
    with SessionSync() as db:
        db.add(
            WorkflowExecutionORM(
                execution_id=exec_id,
                tenant_id="tenant_alpha",
                workflow_id="wf_evt_it",
                version_id="v1",
                graph_instance_id=gi,
                state="completed",
                input_data={},
                output_data={},
                global_context={},
                node_states_json="[]",
                triggered_by="u1",
                trigger_type="manual",
                resource_quota={},
            )
        )
        db.commit()

    asyncio.run(_emit_graph_started(ek_db, gi))

    app = make_fastapi_app_router_only(events_api)

    @app.middleware("http")
    async def _tenant(request: Request, call_next):  # type: ignore[no-untyped-def]
        hdr = getattr(settings, "tenant_header_name", "X-Tenant-Id")
        raw = (request.headers.get(hdr) or "").strip()
        default = str(getattr(settings, "tenant_default_id", "default") or "default").strip() or "default"
        request.state.tenant_id = raw or default
        return await call_next(request)

    client = TestClient(app)
    hdr = getattr(settings, "tenant_header_name", "X-Tenant-Id")

    ok = client.get(f"/api/events/instance/{gi}", headers={hdr: "tenant_alpha"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body.get("instance_id") == gi
    assert body.get("total", 0) >= 1

    forbidden = client.get(f"/api/events/instance/{gi}", headers={hdr: "tenant_beta"})
    assert forbidden.status_code == 404
    err = forbidden.json().get("error") or {}
    assert err.get("code") == "execution_instance_not_found"

    asyncio.run(ek_db.close())
    sync_engine.dispose()
