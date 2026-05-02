"""Chat `/api/sessions/*` 404 等结构化错误（与 HistoryStore mock）。"""

from __future__ import annotations

from typing import Any, List

import pytest
from fastapi.testclient import TestClient

from api import sessions as sessions_api
from tests.helpers import build_minimal_router_test_client

pytestmark = pytest.mark.no_fallback


class _FakeHistoryStore:
    def __init__(self) -> None:
        self.messages_result: List[Any] = []
        self.session_exists_flag = False

    def list_sessions(self, *, user_id: str, limit: int = 50, tenant_id: str = "default"):
        return []

    def list_messages(
        self, *, user_id: str, session_id: str, limit: int = 200, tenant_id: str = "default"
    ):
        return list(self.messages_result)

    def session_exists(self, *, user_id: str, session_id: str, tenant_id: str = "default") -> bool:
        return self.session_exists_flag

    def rename_session(
        self, *, user_id: str, session_id: str, title: str, tenant_id: str = "default"
    ) -> bool:
        return False

    def delete_session(self, *, user_id: str, session_id: str, hard: bool = True, tenant_id: str = "default") -> bool:
        return False


@pytest.fixture()
def sessions_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    fake = _FakeHistoryStore()
    monkeypatch.setattr(sessions_api, "_store", fake)

    client = build_minimal_router_test_client(sessions_api)
    client._fake_store = fake  # type: ignore[attr-defined]
    return client


def test_list_messages_unknown_session_returns_structured_404(
    sessions_client: TestClient,
    fallback_probe,
):
    fake: _FakeHistoryStore = sessions_client._fake_store  # type: ignore[assignment]
    fake.messages_result = []
    fake.session_exists_flag = False

    resp = sessions_client.get("/api/sessions/nope/messages")
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "chat session not found"
    assert body["error"]["code"] == "chat_session_not_found"
    assert body["error"]["details"]["session_id"] == "nope"
    assert fallback_probe == []


def test_rename_session_unknown_returns_structured_404(sessions_client: TestClient):
    resp = sessions_client.patch("/api/sessions/missing", params={"title": "t"})
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "chat_session_not_found"


def test_delete_session_unknown_returns_structured_404(sessions_client: TestClient):
    resp = sessions_client.delete("/api/sessions/missing")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "chat_session_not_found"
