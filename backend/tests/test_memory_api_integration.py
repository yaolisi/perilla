"""`/api/memory/*` 结构化错误集成测试（mock MemoryStore）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import memory as memory_api
from tests.helpers import build_minimal_router_test_client

pytestmark = pytest.mark.no_fallback


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

    return build_minimal_router_test_client(memory_api)


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
