"""RAG Trace 外部 API：须按当前请求的 user_id + tenant（与 create_trace 写入一致）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import rag_trace as rag_trace_api
from config.settings import settings
from core.rag.trace_store import RAGTraceStore, RAGTraceStoreConfig

pytestmark = pytest.mark.tenant_isolation


@pytest.fixture()
def rag_trace_app(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db = tmp_path / "rag_scope.db"
    store = RAGTraceStore(RAGTraceStoreConfig(db_path=db))
    monkeypatch.setattr(rag_trace_api, "_trace_store", store)

    app = FastAPI()
    app.include_router(rag_trace_api.router)
    return app, store


def test_trace_by_message_scopes_to_request_user(rag_trace_app: tuple[FastAPI, RAGTraceStore]) -> None:
    app, store = rag_trace_app
    mid = "msg_scope_rag_1"
    tid = store.create_trace(
        session_id="sess_1",
        message_id=mid,
        rag_id="kb1",
        rag_type="naive",
        query="q",
        embedding_model="e",
        vector_store="sqlite-vec",
        top_k=3,
        user_id="alice",
        tenant_id="default",
    )
    store.finalize_trace(tid, 0)

    client = TestClient(app)
    ok = client.get(f"/api/rag/trace/by-message/{mid}", headers={"X-User-Id": "alice"})
    assert ok.status_code == 200
    assert ok.json().get("rag_used") is True

    other = client.get(f"/api/rag/trace/by-message/{mid}", headers={"X-User-Id": "bob"})
    assert other.status_code == 200
    assert other.json().get("rag_used") is False
    assert other.json().get("trace") is None


def test_trace_by_id_scopes_to_request_user(rag_trace_app: tuple[FastAPI, RAGTraceStore]) -> None:
    app, store = rag_trace_app
    mid = "msg_scope_rag_2"
    tid = store.create_trace(
        session_id="sess_2",
        message_id=mid,
        rag_id="kb1",
        rag_type="naive",
        query="q",
        embedding_model="e",
        vector_store="sqlite-vec",
        top_k=3,
        user_id="carol",
        tenant_id="default",
    )
    store.finalize_trace(tid, 0)

    client = TestClient(app)
    ok = client.get(f"/api/rag/trace/{tid}", headers={"X-User-Id": "carol"})
    assert ok.status_code == 200
    assert ok.json().get("rag_used") is True

    other = client.get(f"/api/rag/trace/{tid}", headers={"X-User-Id": "dave"})
    assert other.status_code == 200
    assert other.json().get("rag_used") is False


def test_trace_by_message_scopes_to_request_tenant(rag_trace_app: tuple[FastAPI, RAGTraceStore]) -> None:
    app, store = rag_trace_app
    hdr = getattr(settings, "tenant_header_name", "X-Tenant-Id")
    mid = "msg_scope_rag_tenant_1"
    trace_pk = store.create_trace(
        session_id="sess_t",
        message_id=mid,
        rag_id="kb1",
        rag_type="naive",
        query="q",
        embedding_model="e",
        vector_store="sqlite-vec",
        top_k=3,
        user_id="frank",
        tenant_id="tenant_acme",
    )
    store.finalize_trace(trace_pk, 0)

    client = TestClient(app)
    ok = client.get(
        f"/api/rag/trace/by-message/{mid}",
        headers={"X-User-Id": "frank", hdr: "tenant_acme"},
    )
    assert ok.status_code == 200
    assert ok.json().get("rag_used") is True

    wrong_tenant = client.get(
        f"/api/rag/trace/by-message/{mid}",
        headers={"X-User-Id": "frank", hdr: "tenant_other"},
    )
    assert wrong_tenant.status_code == 200
    assert wrong_tenant.json().get("rag_used") is False
