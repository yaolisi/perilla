"""HistoryStore：sessions.tenant_id 隔离（跨租户不得复用 session_id）。"""

from __future__ import annotations

import tempfile

import pytest
from pathlib import Path

from core.conversation.history_store import DEFAULT_TENANT_ID, HistoryStore, HistoryStoreConfig

pytestmark = pytest.mark.tenant_isolation


def test_session_scoped_by_tenant_not_only_user():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.db"
        store = HistoryStore(HistoryStoreConfig(db_path=db))
        sid = store.create_session(user_id="u1", title="t", tenant_id="tenant-a")
        assert store.session_exists(user_id="u1", session_id=sid, tenant_id="tenant-a")
        assert not store.session_exists(user_id="u1", session_id=sid, tenant_id="tenant-b")


def test_append_message_rejects_tenant_mismatch():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.db"
        store = HistoryStore(HistoryStoreConfig(db_path=db))
        sid = store.create_session(user_id="u1", title="t", tenant_id="tenant-a")
        store.append_message(session_id=sid, role="user", content="hi", tenant_id="tenant-a")
        try:
            store.append_message(session_id=sid, role="assistant", content="no", tenant_id="tenant-b")
            raised = False
        except ValueError:
            raised = True
        assert raised


def test_default_tenant_constant():
    assert DEFAULT_TENANT_ID == "default"
