"""chat 解析路径写入 request.state 与响应 metadata（resolved_model / resolved_via）。"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from api import chat as chat_api
from core.inference.router.model_router import RoutingResult
from core.models.descriptor import ModelDescriptor
from core.types import ChatCompletionRequest, Message


def _minimal_http_scope() -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/v1/chat/completions",
        "raw_path": b"/v1/chat/completions",
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 80),
    }


def _desc(model_id: str) -> ModelDescriptor:
    return ModelDescriptor(
        id=model_id,
        name="t",
        provider="ollama",
        provider_model_id="pm",
        runtime="ollama",
    )


def test_resolve_sets_routing_metadata_for_explicit_model(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMR:
        def resolve(self, model_alias, max_depth=10, request_metadata=None, _skip_policy=False):
            return RoutingResult(None, "auto", "routed-id", "direct+canary")

    class FakeSel:
        def resolve(self, model_id=None, model_require=None, messages=None):
            return _desc("routed-id")

    monkeypatch.setattr(chat_api, "ModelRouter", FakeMR)
    monkeypatch.setattr(chat_api, "get_model_selector", lambda: FakeSel())

    request = Request(_minimal_http_scope())
    req = ChatCompletionRequest(
        model="alias-a",
        messages=[Message(role="user", content="hi")],
        stream=False,
        metadata={"role": "admin", "is_admin": True},
    )
    mid = chat_api._resolve_model_for_request(req, request, "user-1")
    assert mid == "routed-id"
    md = request.state.chat_routing_metadata
    assert md["resolved_model"] == "routed-id"
    assert md["resolved_via"] == "direct+canary"


def test_resolve_registry_remap_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMR:
        def resolve(self, model_alias, max_depth=10, request_metadata=None, _skip_policy=False):
            return RoutingResult(None, "auto", "pre-id", "alias")

    class FakeSel:
        def resolve(self, model_id=None, model_require=None, messages=None):
            return _desc("final-id")

    monkeypatch.setattr(chat_api, "ModelRouter", FakeMR)
    monkeypatch.setattr(chat_api, "get_model_selector", lambda: FakeSel())

    request = Request(_minimal_http_scope())
    req = ChatCompletionRequest(model="alias-a", messages=[Message(role="user", content="hi")], stream=False)
    mid = chat_api._resolve_model_for_request(req, request, "u")
    assert mid == "final-id"
    assert request.state.chat_routing_metadata["resolved_model"] == "final-id"
    assert request.state.chat_routing_metadata["resolved_via"] == "alias+registry"


def test_resolve_auto_skips_inference_router(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    class FakeMR:
        def resolve(self, model_alias, max_depth=10, request_metadata=None, _skip_policy=False):
            called.append(model_alias)
            return RoutingResult(None, "auto", "x", "direct")

    class FakeSel:
        def resolve(self, model_id=None, model_require=None, messages=None):
            return _desc("picked")

    monkeypatch.setattr(chat_api, "ModelRouter", FakeMR)
    monkeypatch.setattr(chat_api, "get_model_selector", lambda: FakeSel())

    request = Request(_minimal_http_scope())
    req = ChatCompletionRequest(model="auto", messages=[Message(role="user", content="hi")], stream=False)
    mid = chat_api._resolve_model_for_request(req, request, "u")
    assert mid == "picked"
    assert called == []
    assert request.state.chat_routing_metadata["resolved_via"] == "selector"


def test_chat_completion_response_optional_metadata() -> None:
    from core.types import ChatCompletionResponse

    body = ChatCompletionResponse(
        id="c1",
        created=1,
        model="m",
        choices=[],
        metadata={"resolved_model": "m", "resolved_via": "direct"},
    )
    dumped = body.model_dump()
    assert dumped["metadata"]["resolved_via"] == "direct"


def test_routing_submeta_for_persist() -> None:
    from starlette.requests import Request

    from api import chat as chat_api

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 80),
    }
    request = Request(scope)
    assert chat_api._routing_submeta_for_persist(request) is None
    request.state.chat_routing_metadata = {"resolved_model": "m1", "resolved_via": "selector"}
    assert chat_api._routing_submeta_for_persist(request) == {
        "resolved_model": "m1",
        "resolved_via": "selector",
    }
