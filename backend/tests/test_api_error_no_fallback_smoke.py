from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import images as images_api
from api import knowledge as knowledge_api
from api import memory as memory_api
from api import sessions as sessions_api

from tests.helpers import make_fastapi_app_router_only

pytestmark = pytest.mark.no_fallback


def test_sessions_not_found_does_not_hit_fallback(monkeypatch: pytest.MonkeyPatch, fallback_probe):
    class _FakeHistoryStore:
        def list_sessions(self, *, user_id: str, limit: int = 50):
            return []

        def list_messages(self, *, user_id: str, session_id: str, limit: int = 200):
            return []

        def session_exists(self, *, user_id: str, session_id: str) -> bool:
            return False

        def rename_session(self, *, user_id: str, session_id: str, title: str) -> bool:
            return False

        def delete_session(self, *, user_id: str, session_id: str, hard: bool = True) -> bool:
            return False

    monkeypatch.setattr(sessions_api, "_store", _FakeHistoryStore())
    client = TestClient(make_fastapi_app_router_only(sessions_api))

    resp = client.get("/api/sessions/smoke-missing/messages")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "chat_session_not_found"
    assert fallback_probe == []


def test_memory_not_found_does_not_hit_fallback(monkeypatch: pytest.MonkeyPatch, fallback_probe):
    class _FakeMemoryStore:
        def list(self, *, user_id: str, limit: int = 50, include_deprecated: bool = False):
            return []

        def delete(self, *, user_id: str, memory_id: str) -> bool:
            return False

        def clear(self, *, user_id: str) -> int:
            return 0

    monkeypatch.setattr(memory_api, "_store", _FakeMemoryStore())
    client = TestClient(make_fastapi_app_router_only(memory_api))

    resp = client.delete("/api/memory/smoke-memory-id")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "memory_not_found"
    assert fallback_probe == []


def test_knowledge_not_found_does_not_hit_fallback(monkeypatch: pytest.MonkeyPatch, fallback_probe):
    class _FakeKBStore:
        def get_knowledge_base(self, kb_id: str, user_id: str = "default"):
            return None

    monkeypatch.setattr(knowledge_api, "_kb_store", _FakeKBStore())
    client = TestClient(make_fastapi_app_router_only(knowledge_api))

    resp = client.get("/api/knowledge-bases/smoke-kb-id")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "knowledge_base_not_found"
    assert fallback_probe == []


def test_images_warmup_not_found_does_not_hit_fallback(monkeypatch: pytest.MonkeyPatch, fallback_probe):
    monkeypatch.setattr(images_api, "_db_get_latest_warmup", lambda model: None)
    client = TestClient(make_fastapi_app_router_only(images_api))

    resp = client.get("/api/v1/images/warmup/latest", params={"model": "smoke-model"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "image_generation_warmup_not_found"
    assert fallback_probe == []
