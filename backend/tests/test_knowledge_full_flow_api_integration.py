from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import knowledge as knowledge_api
from api.errors import register_error_handlers
from core.knowledge.knowledge_base_store import KnowledgeBaseConfig, KnowledgeBaseStore
from core.knowledge.status import DocumentStatus


def _create_embedding_chunks_table(store: KnowledgeBaseStore) -> None:
    with store._connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_chunks (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                knowledge_base_id VARCHAR NOT NULL,
                document_id VARCHAR NOT NULL,
                chunk_id VARCHAR NOT NULL,
                content TEXT NOT NULL,
                version_id TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_embedding_chunks_kb_id ON embedding_chunks (knowledge_base_id)"
        )
        conn.commit()


@pytest.fixture()
def knowledge_full_flow_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[TestClient, KnowledgeBaseStore]:
    db_path = tmp_path / "platform.db"
    store = KnowledgeBaseStore(KnowledgeBaseConfig(db_path=db_path, embedding_dim=4))
    _create_embedding_chunks_table(store)

    class _FakeEmbeddingModel:
        id = "embedding:test"
        metadata = {"embedding_dim": 4}

    class _FakeRegistry:
        def get_model(self, model_id: str):
            if model_id == "embedding:test":
                return _FakeEmbeddingModel()
            return None

    class _FakeEmbedResp:
        embeddings = [[0.11, 0.22, 0.33, 0.44]]

    class _FakeInferenceClient:
        async def embed(self, model: str, input_text, metadata=None):
            await asyncio.sleep(0)
            return _FakeEmbedResp()

    def _fake_save_file(kb_id: str, doc_id: str, file_content: bytes, filename: str) -> Path:
        p = tmp_path / kb_id
        p.mkdir(parents=True, exist_ok=True)
        fp = p / f"{doc_id}{Path(filename).suffix}"
        fp.write_bytes(file_content)
        return fp

    def _fake_bg_index(
        kb_id: str,
        doc_id: str,
        file_path: Path,
        doc_type: str | None,
        content_hash: str | None = None,
        version_id: str | None = None,
    ) -> None:
        resolved_ver = version_id or store.ensure_default_kb_version(kb_id)
        store.update_document_status(
            doc_id=doc_id,
            status=DocumentStatus.INDEXED,
            chunks_count=1,
            error_message=None,
        )
        store.update_document_content_hash(doc_id, content_hash)
        store.add_document_version(
            document_id=doc_id,
            knowledge_base_id=kb_id,
            version_id=resolved_ver,
            content_hash=content_hash,
        )
        with store._connect() as conn:
            conn.execute(
                """
                INSERT INTO embedding_chunks
                (knowledge_base_id, document_id, chunk_id, content, version_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (kb_id, doc_id, f"chunk_{doc_id[-4:]}", "OpenVINO GPU 设备配置示例", resolved_ver),
            )
            conn.commit()
        store.upsert_graph_triples(
            kb_id=kb_id,
            version_id=resolved_ver,
            source_doc_id=doc_id,
            triples=[{"source": "Intel", "relation": "开发", "target": "OpenVINO", "confidence": 0.9}],
        )

    def _fake_search_chunks(
        self,
        knowledge_base_id: str,
        query_embedding,
        limit: int = 5,
        max_distance=None,
        version_id: str | None = None,
    ):
        return store.search_chunks_keyword_multi_kb(
            knowledge_base_ids=[knowledge_base_id],
            query_text="OpenVINO GPU",
            limit=limit,
            version_id=version_id,
        )

    monkeypatch.setattr(knowledge_api, "_db_path", db_path)
    monkeypatch.setattr(knowledge_api, "_kb_store", store)
    monkeypatch.setattr(knowledge_api.FileStorage, "save_file", staticmethod(_fake_save_file))
    monkeypatch.setattr(knowledge_api, "index_document_background", _fake_bg_index)
    monkeypatch.setattr("core.models.registry.get_model_registry", lambda: _FakeRegistry())
    monkeypatch.setattr("core.inference.get_inference_client", lambda: _FakeInferenceClient())
    monkeypatch.setattr(KnowledgeBaseStore, "_ensure_vec_table_dimension", lambda self, kb_id, dim: None)
    monkeypatch.setattr(KnowledgeBaseStore, "search_chunks", _fake_search_chunks)

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(knowledge_api.router)
    return TestClient(app), store


def test_knowledge_full_flow_with_version_label(knowledge_full_flow_client: tuple[TestClient, KnowledgeBaseStore]):
    client, _store = knowledge_full_flow_client

    kb_resp = client.post(
        "/api/knowledge-bases",
        json={
            "name": "KB",
            "description": "test",
            "embedding_model_id": "embedding:test",
            "chunk_size": 128,
            "chunk_overlap": 16,
            "chunk_size_overrides": {},
        },
    )
    assert kb_resp.status_code == 200
    kb_id = kb_resp.json()["id"]

    ver_resp = client.post(
        f"/api/knowledge-bases/{kb_id}/versions",
        json={"version_label": "v2", "notes": "release v2"},
    )
    assert ver_resp.status_code == 200

    upload_resp = client.post(
        f"/api/knowledge-bases/{kb_id}/documents",
        files={"file": ("gpu.txt", b"OpenVINO GPU guide", "text/plain")},
    )
    assert upload_resp.status_code == 200
    doc_id = upload_resp.json()["id"]
    assert doc_id

    search_resp = client.post(
        f"/api/knowledge-bases/{kb_id}/search",
        json={"query": "OpenVINO GPU", "top_k": 3, "version_label": "v2"},
    )
    assert search_resp.status_code == 200
    search_body = search_resp.json()
    assert search_body["data"]
    assert search_body["data"][0]["version_id"] is not None
    assert search_body["data"][0]["doc_source"] == "gpu.txt"

    graph_resp = client.post(
        f"/api/knowledge-bases/{kb_id}/graph/search",
        json={"query": "Intel 开发", "top_k": 5, "version_id": ver_resp.json()["id"]},
    )
    assert graph_resp.status_code == 200
    graph_body = graph_resp.json()
    assert graph_body["data"]
    assert graph_body["data"][0]["target_entity"] == "OpenVINO"


def test_reindex_skip_when_content_not_changed(knowledge_full_flow_client: tuple[TestClient, KnowledgeBaseStore]):
    client, store = knowledge_full_flow_client
    kb_resp = client.post(
        "/api/knowledge-bases",
        json={
            "name": "KB2",
            "description": "test",
            "embedding_model_id": "embedding:test",
            "chunk_size": 128,
            "chunk_overlap": 16,
            "chunk_size_overrides": {},
        },
    )
    kb_id = kb_resp.json()["id"]
    ver_id = store.ensure_default_kb_version(kb_id)

    upload_resp = client.post(
        f"/api/knowledge-bases/{kb_id}/documents",
        files={"file": ("same.txt", b"same-content", "text/plain")},
    )
    assert upload_resp.status_code == 200
    doc_id = upload_resp.json()["id"]

    doc = store.get_document(doc_id)
    assert doc is not None
    assert doc.get("content_hash") == hashlib.sha256(b"same-content").hexdigest()

    reindex_resp = client.post(f"/api/knowledge-bases/{kb_id}/documents/{doc_id}/reindex")
    assert reindex_resp.status_code == 200
    assert "Skipped re-indexing" in reindex_resp.json()["message"]
    assert store.get_latest_document_hash(doc_id) == hashlib.sha256(b"same-content").hexdigest()
    assert store.resolve_kb_version_id(kb_id=kb_id, version_id=ver_id) == ver_id

