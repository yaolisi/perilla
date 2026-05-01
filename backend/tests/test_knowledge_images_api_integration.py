from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.errors import register_error_handlers
from api import knowledge as knowledge_api
from api import images as images_api

pytestmark = pytest.mark.no_fallback


@pytest.fixture()
def knowledge_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    class _FakeKBStore:
        def get_knowledge_base(self, kb_id: str, user_id: str = "default"):
            return None

    monkeypatch.setattr(knowledge_api, "_kb_store", _FakeKBStore())
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(knowledge_api.router)
    return TestClient(app)


@pytest.fixture()
def images_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(images_api, "_db_get_latest_warmup", lambda model: None)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(images_api.router)
    return TestClient(app)


def test_knowledge_get_not_found_is_structured_without_fallback(
    knowledge_client: TestClient,
    fallback_probe,
):
    resp = knowledge_client.get("/api/knowledge-bases/kb_missing")
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "knowledge base not found"
    assert body["error"]["code"] == "knowledge_base_not_found"
    assert body["error"]["details"]["knowledge_base_id"] == "kb_missing"
    assert fallback_probe == []


def test_images_latest_warmup_not_found_is_structured_without_fallback(
    images_client: TestClient,
    fallback_probe,
):
    resp = images_client.get("/api/v1/images/warmup/latest", params={"model": "m1"})
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "image generation warmup target not found"
    assert body["error"]["code"] == "image_generation_warmup_not_found"
    assert body["error"]["details"]["model"] == "m1"
    assert fallback_probe == []
