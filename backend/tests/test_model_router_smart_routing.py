from core.inference.registry.model_registry import ModelAlias
from core.inference.router.model_router import ModelRouter


class _FakeRegistry:
    def __init__(self) -> None:
        self._aliases = {
            "reasoning-model": ModelAlias(alias="reasoning-model", provider="openai", model_id="stable-v1"),
            "stable-v1": ModelAlias(alias="stable-v1", provider="openai", model_id="stable-v1"),
            "canary-v2": ModelAlias(alias="canary-v2", provider="openai", model_id="canary-v2"),
            "blue-v1": ModelAlias(alias="blue-v1", provider="openai", model_id="blue-v1"),
            "green-v2": ModelAlias(alias="green-v2", provider="openai", model_id="green-v2"),
            "worker-a": ModelAlias(alias="worker-a", provider="openai", model_id="worker-a"),
            "worker-b": ModelAlias(alias="worker-b", provider="openai", model_id="worker-b"),
        }

    def resolve(self, alias_name: str):
        return self._aliases.get(alias_name)

    def list_aliases(self):
        return list(self._aliases.keys())


def test_blue_green_admin_sticky_to_stable(monkeypatch):
    router = ModelRouter(registry=_FakeRegistry())
    monkeypatch.setattr(
        "core.inference.router.model_router.get_inference_smart_routing_policies_json",
        lambda: '{"reasoning-model":{"strategy":"blue_green","stable":"blue-v1","candidate":"green-v2","candidate_percent":100}}',
    )
    monkeypatch.setattr(
        "core.inference.router.model_router.get_inference_smart_routing_enabled",
        lambda: True,
    )
    result = router.resolve("reasoning-model", request_metadata={"role": "admin", "user_id": "u1"})
    assert result.model_id == "blue-v1"
    assert "blue_green" in result.resolved_via


def test_canary_uses_deterministic_bucket(monkeypatch):
    router = ModelRouter(registry=_FakeRegistry())
    monkeypatch.setattr(
        "core.inference.router.model_router.get_inference_smart_routing_policies_json",
        lambda: '{"reasoning-model":{"strategy":"canary","stable":"stable-v1","canary":"canary-v2","canary_percent":100}}',
    )
    monkeypatch.setattr(
        "core.inference.router.model_router.get_inference_smart_routing_enabled",
        lambda: True,
    )
    result = router.resolve("reasoning-model", request_metadata={"user_id": "normal-user"})
    assert result.model_id == "canary-v2"
    assert "canary" in result.resolved_via


def test_least_loaded_picks_lower_queue(monkeypatch):
    router = ModelRouter(registry=_FakeRegistry())
    monkeypatch.setattr(
        "core.inference.router.model_router.get_inference_smart_routing_policies_json",
        lambda: '{"reasoning-model":{"strategy":"least_loaded","candidates":["worker-a","worker-b"]}}',
    )
    monkeypatch.setattr(
        "core.inference.router.model_router.get_inference_smart_routing_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "core.inference.router.model_router.ModelRouter._queue_size",
        staticmethod(lambda model_id: 10 if model_id == "worker-a" else 2),
    )
    result = router.resolve("reasoning-model", request_metadata={"user_id": "u2"})
    assert result.model_id == "worker-b"
    assert "least_loaded" in result.resolved_via


def test_smart_routing_can_be_disabled(monkeypatch):
    router = ModelRouter(registry=_FakeRegistry())
    monkeypatch.setattr(
        "core.inference.router.model_router.get_inference_smart_routing_policies_json",
        lambda: '{"reasoning-model":{"strategy":"blue_green","stable":"blue-v1","candidate":"green-v2","candidate_percent":100}}',
    )
    monkeypatch.setattr(
        "core.inference.router.model_router.get_inference_smart_routing_enabled",
        lambda: False,
    )
    result = router.resolve("reasoning-model", request_metadata={"user_id": "u2"})
    assert result.model_id == "stable-v1"
    assert result.resolved_via == "alias"

