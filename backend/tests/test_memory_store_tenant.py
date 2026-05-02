"""MemoryStore：memory_items.tenant_id 隔离。"""

from __future__ import annotations

import tempfile

import pytest
from pathlib import Path

from core.memory.memory_item import MemoryCandidate
from core.memory.memory_store import DEFAULT_MEMORY_TENANT_ID, MemoryStore, MemoryStoreConfig

pytestmark = pytest.mark.tenant_isolation


def test_list_scoped_by_tenant():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "m.db"
        store = MemoryStore(
            MemoryStoreConfig(db_path=db, vector_enabled=False, key_schema_enforced=False)
        )
        store.add_candidates(
            [MemoryCandidate(type="fact", content="alpha")],
            user_id="u1",
            tenant_id="ta",
        )
        store.add_candidates(
            [MemoryCandidate(type="fact", content="beta")],
            user_id="u1",
            tenant_id="tb",
        )
        la = store.list(user_id="u1", limit=10, tenant_id="ta")
        lb = store.list(user_id="u1", limit=10, tenant_id="tb")
        assert len(la) == 1 and la[0].content == "alpha"
        assert len(lb) == 1 and lb[0].content == "beta"


def test_delete_respects_tenant():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "m.db"
        store = MemoryStore(
            MemoryStoreConfig(db_path=db, vector_enabled=False, key_schema_enforced=False)
        )
        created = store.add_candidates(
            [MemoryCandidate(type="fact", content="x")],
            user_id="u1",
            tenant_id="ta",
        )
        mid = created[0].id
        assert not store.delete(user_id="u1", memory_id=mid, tenant_id="wrong")
        assert store.delete(user_id="u1", memory_id=mid, tenant_id="ta")


def test_default_constant():
    assert DEFAULT_MEMORY_TENANT_ID == "default"
