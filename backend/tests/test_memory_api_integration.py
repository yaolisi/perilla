"""`/api/memory/*` 结构化错误集成测试（mock MemoryStore）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.errors import register_error_handlers
from api import memory as memory_api


class _FakeMemoryStore:
    def list(self, *, user_id: str, limit: int = 50, include_deprecated: bool = False):
        return []

    def delete(self, *, user_id: str, memory_id: str) -> bool:
        return False

    def clear(self, *, user_id: str) -> int:
        return 0


@pytest.fixture()
def memory_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(memory_api, "_store", _FakeMemoryStore())

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(memory_api.router)

    return TestClient(app)


@pytest.mark.no_fallback
def test_delete_unknown_memory_returns_structured_404(
    memory_client: TestClient,
    fallback_probe,
):
    resp = memory_client.delete("/api/memory/nonexistent-id")
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "memory not found"
    assert body["error"]["code"] == "memory_not_found"
    assert body["error"]["details"]["memory_id"] == "nonexistent-id"
    assert fallback_probe == []
