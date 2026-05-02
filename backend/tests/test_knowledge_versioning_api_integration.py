from __future__ import annotations

import asyncio
import pytest
from fastapi.testclient import TestClient

from api import knowledge as knowledge_api
from tests.helpers import build_minimal_router_test_client


@pytest.fixture()
def knowledge_version_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, dict]:
    calls: dict = {}

    class _FakeEmbeddingModel:
        id = "embedding:test"
        metadata = {"embedding_dim": 4}

    class _FakeRegistry:
        def get_model(self, model_id: str):
            if model_id == "embedding:test":
                return _FakeEmbeddingModel()
            return None

    class _FakeEmbedResp:
        embeddings = [[0.1, 0.2, 0.3, 0.4]]

    class _FakeInferenceClient:
        async def embed(self, model: str, input_text, metadata=None):
            await asyncio.sleep(0)
            return _FakeEmbedResp()

    class _FakeKBStore:
        config = type("Cfg", (), {"embedding_dim": 4})()

        def get_knowledge_base(
            self, kb_id: str, user_id: str = "default", tenant_id: str = "default"
        ):
            return {"id": kb_id, "embedding_model_id": "embedding:test"}

        def resolve_kb_version_id(self, kb_id: str, version_id=None, version_label=None):
            calls["resolved"] = (kb_id, version_id, version_label)
            if version_id:
                return version_id
            if version_label == "v2":
                return "kbv_2"
            return "kbv_latest"

        def search_chunks(self, knowledge_base_id: str, query_embedding, limit=5, max_distance=None, version_id=None):
            calls["search_chunks_version_id"] = version_id
            return [
                {
                    "content": "OpenVINO GPU 配置",
                    "distance": 0.2,
                    "version_id": version_id,
                    "document_id": "doc_1",
                    "chunk_id": "chunk_1",
                    "doc_source": "gpu.md",
                }
            ]

        def search_graph_relations(self, kb_id: str, query_text: str, limit: int = 10, version_id=None):
            calls["graph_version_id"] = version_id
            return [
                {
                    "source_entity": "Intel",
                    "relation": "开发",
                    "target_entity": "OpenVINO",
                    "version_id": version_id,
                }
            ]

        def list_kb_versions(self, kb_id: str):
            return [{"id": "kbv_1", "version_label": "v1"}, {"id": "kbv_2", "version_label": "v2"}]

        def create_kb_version(self, kb_id: str, version_label: str, notes=None, status="ACTIVE"):
            return "kbv_new"

        def _ensure_vec_table_dimension(self, kb_id: str, required_dim: int) -> None:
            _ = (kb_id, required_dim)

    monkeypatch.setattr(knowledge_api, "_kb_store", _FakeKBStore())
    monkeypatch.setattr(knowledge_api, "get_model_registry", lambda: _FakeRegistry(), raising=False)
    monkeypatch.setattr("core.models.registry.get_model_registry", lambda: _FakeRegistry())
    monkeypatch.setattr("core.inference.get_inference_client", lambda: _FakeInferenceClient())

    client = build_minimal_router_test_client(knowledge_api)
    return client, calls


@pytest.mark.no_fallback
def test_search_resolves_version_label_and_returns_version_fields(
    knowledge_version_client: tuple[TestClient, dict],
):
    client, calls = knowledge_version_client
    resp = client.post(
        "/api/knowledge-bases/kb_1/search",
        json={"query": "OpenVINO GPU", "top_k": 3, "version_label": "v2"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["version_id"] == "kbv_2"
    assert body["data"][0]["document_id"] == "doc_1"
    assert calls["resolved"] == ("kb_1", None, "v2")
    assert calls["search_chunks_version_id"] == "kbv_2"


@pytest.mark.no_fallback
def test_graph_search_accepts_version_id(
    knowledge_version_client: tuple[TestClient, dict],
):
    client, calls = knowledge_version_client
    resp = client.post(
        "/api/knowledge-bases/kb_1/graph/search",
        json={"query": "Intel 开发", "top_k": 5, "version_id": "kbv_1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["target_entity"] == "OpenVINO"
    assert calls["graph_version_id"] == "kbv_1"

