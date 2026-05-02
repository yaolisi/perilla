"""KnowledgeBaseStore：knowledge_base / document 行级 tenant_id 隔离。"""

from __future__ import annotations

import tempfile

import pytest
from pathlib import Path

from core.knowledge.knowledge_base_store import (
    DEFAULT_KB_TENANT_ID,
    KnowledgeBaseConfig,
    KnowledgeBaseStore,
)

pytestmark = pytest.mark.tenant_isolation


def test_list_knowledge_bases_scoped_by_tenant():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "kb.db"
        store = KnowledgeBaseStore(KnowledgeBaseConfig(db_path=db, embedding_dim=4))
        store.create_knowledge_base(
            "A",
            None,
            "emb:x",
            user_id="u1",
            tenant_id="ta",
        )
        store.create_knowledge_base(
            "B",
            None,
            "emb:x",
            user_id="u1",
            tenant_id="tb",
        )
        la = store.list_knowledge_bases(user_id="u1", tenant_id="ta")
        lb = store.list_knowledge_bases(user_id="u1", tenant_id="tb")
        assert len(la) == 1 and la[0]["name"] == "A"
        assert len(lb) == 1 and lb[0]["name"] == "B"


def test_get_kb_denies_cross_tenant():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "kb.db"
        store = KnowledgeBaseStore(KnowledgeBaseConfig(db_path=db, embedding_dim=4))
        kb_id = store.create_knowledge_base(
            "K",
            None,
            "emb:x",
            user_id="u1",
            tenant_id="ta",
        )
        from core.utils.user_context import UserAccessDeniedError

        try:
            store.get_knowledge_base(kb_id, user_id="u1", tenant_id="wrong")
            assert False, "expected UserAccessDeniedError"
        except UserAccessDeniedError:
            pass


def test_default_constant():
    assert DEFAULT_KB_TENANT_ID == "default"
