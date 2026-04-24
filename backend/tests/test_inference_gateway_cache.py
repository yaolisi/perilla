from types import SimpleNamespace

from core.inference.gateway.inference_gateway import InferenceGateway
from core.inference.models.inference_request import InferenceRequest
from core.inference.router.model_router import RoutingResult


class _FakeModelRegistry:
    def __init__(self, model_type: str = "llm", version: str = "v1") -> None:
        self.model_type = model_type
        self.version = version

    def get_model(self, model_id: str):
        return SimpleNamespace(
            id=model_id,
            model_type=self.model_type,
            provider="local",
            version=self.version,
        )


def _build_gateway() -> InferenceGateway:
    gateway = InferenceGateway()
    gateway.model_registry = _FakeModelRegistry()
    return gateway


def test_generate_cache_key_contains_user_dimension() -> None:
    gateway = _build_gateway()
    routing = RoutingResult(alias=None, provider="local", model_id="test-model", resolved_via="direct")
    req_a = InferenceRequest(model_alias="test-model", prompt="hello", metadata={"user_id": "u1"})
    req_b = InferenceRequest(model_alias="test-model", prompt="hello", metadata={"user_id": "u2"})

    key_a = gateway._build_generate_cache_key(routing, req_a)
    key_b = gateway._build_generate_cache_key(routing, req_b)
    assert key_a != key_b
    assert ":u:" in key_a


def test_generate_cache_key_changes_when_model_version_changes() -> None:
    gateway = _build_gateway()
    routing = RoutingResult(alias=None, provider="local", model_id="test-model", resolved_via="direct")
    req = InferenceRequest(model_alias="test-model", prompt="hello", metadata={"user_id": "u1"})

    key_v1 = gateway._build_generate_cache_key(routing, req)
    gateway.model_registry = _FakeModelRegistry(version="v2")
    key_v2 = gateway._build_generate_cache_key(routing, req)
    assert key_v1 != key_v2


def test_cache_scope_prefix_supports_targeted_invalidation() -> None:
    gateway = _build_gateway()
    prefix = gateway._cache_scope_prefix(
        "generate",
        user_id="u1",
        model_type="llm",
        resolved_model="test-model",
    )
    assert prefix.endswith(":u:u1:mt:llm:rm:test-model")


def test_resolve_generate_cache_ttl_by_model_type_override() -> None:
    gateway = _build_gateway()
    routing = RoutingResult(alias=None, provider="local", model_id="test-model", resolved_via="direct")
    ttl = gateway._resolve_generate_cache_ttl(routing)
    assert ttl >= 1


def test_apply_request_priority_for_admin() -> None:
    request = InferenceRequest(
        model_alias="test-model",
        prompt="hello",
        metadata={"role": "admin"},
        priority="low",
    )
    InferenceGateway._apply_request_priority(request)
    assert request.priority == "high"
    assert request.metadata.get("priority_source") == "admin"

