"""
/v1/vlm/generate 单次 HTTP 集成测试：TestClient + 推理层/队列/指标/落库等全面 mock（不打真实 VLM、不写 platform.db）。
"""

from __future__ import annotations

import asyncio
import base64
import json
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import api.vlm as vlm_mod

from tests.helpers import make_fastapi_app_router_only
from core.models.descriptor import ModelDescriptor


# 1×1 透明 PNG（与 vlm 单测中占位图一致，满足 _sniff_mime + 非空 image）
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

_MOCK_INFER_TEXT = "MOCK_VLM_INFER_OK"


class _MockHistoryStore:
    def __init__(self) -> None:
        self._n = 0
        self._known: set[str] = set()
        self.appended: list[dict[str, Any]] = []

    def session_exists(self, *, user_id: str, session_id: str) -> bool:
        return session_id in self._known

    def create_session(self, *, user_id: str, title: str, last_model: str | None = None) -> str:
        self._n += 1
        sid = f"mock-sess-{self._n}"
        self._known.add(sid)
        return sid

    def append_message(self, **kwargs: Any) -> None:
        self.appended.append(dict(kwargs))

    def touch_session(self, **kwargs: Any) -> None:
        return None

    def get_session(self, *, user_id: str, session_id: str) -> dict | None:
        return None


class _FakeVlmRuntime:
    is_loaded: bool = True

    async def initialize(self, model_path: str | None = None, **kwargs: Any) -> None:
        await asyncio.sleep(0)

    async def infer(
        self,
        *,
        image: bytes,
        prompt: str,
        system_prompt: str | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> str:
        await asyncio.sleep(0)
        return _MOCK_INFER_TEXT


class _FakeRuntimeFactory:
    def __init__(self) -> None:
        self._rt = _FakeVlmRuntime()

    async def auto_release_unused_local_runtimes(
        self, *, keep_model_ids: set[str], reason: str
    ) -> None:
        await asyncio.sleep(0)

    def create_vlm_runtime(self, model: ModelDescriptor) -> Any:
        return self._rt

    @asynccontextmanager
    async def model_usage(self, model_id: str) -> Any:
        await asyncio.sleep(0)
        yield
        await asyncio.sleep(0)


class _FakeQueue:
    async def run(self, coro: Any, priority: str = "medium") -> Any:
        return await coro


class _FakeQueueManager:
    def get_queue(self, model_id: str, runtime_type: str) -> _FakeQueue:
        return _FakeQueue()


class _FakeMetrics:
    def record_request(self, *a: Any, **k: Any) -> None:
        return None

    def record_latency(self, *a: Any, **k: Any) -> None:
        return None

    def record_tokens(self, *a: Any, **k: Any) -> None:
        return None

    def record_request_failed(self, *a: Any, **k: Any) -> None:
        return None


def _resolve_patch(
    request: Request, user_id: str, raw_model: str, user_prompt: str
) -> ModelDescriptor:
    request.state.chat_routing_metadata = {
        "resolved_model": "test:vlm-mock",
        "resolved_via": "test_direct",
    }
    return ModelDescriptor(
        id="test:vlm-mock",
        name="Mock VLM",
        model_type="vlm",
        provider="local",
        provider_model_id="mock",
        runtime="mock_vlm",
    )


@pytest.fixture
def vlm_test_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, _MockHistoryStore]:
    store = _MockHistoryStore()
    fac = _FakeRuntimeFactory()
    qm = _FakeQueueManager()
    metrics = _FakeMetrics()

    monkeypatch.setattr(vlm_mod, "_history_store", store)
    monkeypatch.setattr(vlm_mod, "_resolve_vlm_model_descriptor", _resolve_patch)
    monkeypatch.setattr(vlm_mod, "get_runtime_factory", lambda: fac)
    monkeypatch.setattr(vlm_mod, "get_inference_queue_manager", lambda: qm)
    monkeypatch.setattr(vlm_mod, "get_runtime_metrics", lambda: metrics)
    monkeypatch.setattr(vlm_mod, "get_auto_unload_local_model_on_switch", lambda: False)
    monkeypatch.setattr(vlm_mod, "record_inference", lambda *a, **k: None)
    monkeypatch.setattr(vlm_mod, "estimate_tokens", lambda _t: 3)
    monkeypatch.setattr(vlm_mod, "log_structured", lambda *a, **k: None)

    return TestClient(make_fastapi_app_router_only(vlm_mod)), store


def test_vlm_generate_http_success(
    vlm_test_client: tuple[TestClient, _MockHistoryStore],
) -> None:
    client, store = vlm_test_client
    payload = {
        "model": "test:vlm-mock",
        "prompt": "describe the image",
        "temperature": 0.2,
        "max_tokens": 64,
    }
    resp = client.post(
        "/v1/vlm/generate",
        data={"request": json.dumps(payload, ensure_ascii=False)},
        files={"image": ("ping.png", _TINY_PNG, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["model"] == "test:vlm-mock"
    assert data["text"] == _MOCK_INFER_TEXT
    assert data["metadata"] == {
        "resolved_model": "test:vlm-mock",
        "resolved_via": "test_direct",
    }
    assert "usage" in data
    # 会话与落库（user + assistant）
    assert resp.headers.get("X-Session-Id", "").startswith("mock-sess-")
    assert len(store.appended) == 2
    assert store.appended[0]["role"] == "user"
    assert store.appended[0].get("meta", {}).get("vlm") is True
    assert "routing" in (store.appended[0].get("meta") or {})
    assert store.appended[1]["role"] == "assistant"
    assert store.appended[1].get("content") == _MOCK_INFER_TEXT
    assert store.appended[1].get("meta", {}).get("vlm") is True


def test_vlm_generate_http_rejects_empty_image(
    vlm_test_client: tuple[TestClient, _MockHistoryStore],
) -> None:
    client, _store = vlm_test_client
    payload = {"model": "test:vlm-mock", "prompt": "x"}
    resp = client.post(
        "/v1/vlm/generate",
        data={"request": json.dumps(payload)},
        files={"image": ("e.png", b"", "image/png")},
    )
    assert resp.status_code == 400
    body = resp.json()
    err = body.get("error", {})
    assert err.get("code") == "vlm_empty_image"


def test_vlm_generate_http_rejects_invalid_request_json(
    vlm_test_client: tuple[TestClient, _MockHistoryStore],
) -> None:
    client, _ = vlm_test_client
    resp = client.post(
        "/v1/vlm/generate",
        data={"request": "{not valid json"},
        files={"image": ("a.png", _TINY_PNG, "image/png")},
    )
    assert resp.status_code == 400
    err = resp.json().get("error", {})
    assert err.get("code") == "vlm_invalid_request_json"
