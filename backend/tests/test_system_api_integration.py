from __future__ import annotations

import asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api import system as system_api
from api.errors import register_error_handlers


def _build_client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.middleware("http")
    async def _inject_test_user(request, call_next):  # type: ignore[no-untyped-def]
        request.state.user_id = request.headers.get("X-User-Id")
        return await call_next(request)

    app.include_router(system_api.router)
    app.dependency_overrides[system_api.require_authenticated_platform_admin] = lambda: None
    app.dependency_overrides[system_api.require_platform_admin] = lambda: None
    return TestClient(app)


@pytest.mark.no_fallback
def test_update_feature_flags_invalid_payload_returns_structured_error(fallback_probe):
    client = _build_client()

    resp = client.post("/api/system/feature-flags", json={"flags": "not-an-object"})
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("detail") == "flags must be object"
    assert body.get("error", {}).get("code") == "system_feature_flags_invalid"
    assert fallback_probe == []


def test_kernel_status_endpoint_returns_expected_shape():
    client = _build_client()

    resp = client.get("/api/system/kernel/status")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body.get("enabled"), bool)
    assert body.get("can_toggle") is True
    assert "description" in body


def test_feature_flags_update_and_fetch_roundtrip(monkeypatch):
    client = _build_client()
    saved: dict = {}

    def _fake_set_feature_flags(flags, tenant_id=None):
        saved["tenant_id"] = tenant_id
        saved["flags"] = dict(flags)
        return saved["flags"]

    def _fake_get_feature_flags(tenant_id=None):
        return saved.get("flags", {})

    monkeypatch.setattr(system_api, "set_feature_flags", _fake_set_feature_flags)
    monkeypatch.setattr(system_api, "get_feature_flags", _fake_get_feature_flags)

    update_resp = client.post("/api/system/feature-flags", json={"flags": {"beta_ui": True}})
    assert update_resp.status_code == 200
    assert update_resp.json().get("flags", {}).get("beta_ui") is True

    get_resp = client.get("/api/system/feature-flags")
    assert get_resp.status_code == 200
    assert get_resp.json().get("flags", {}).get("beta_ui") is True


def test_inference_cache_stats_endpoint(monkeypatch):
    client = _build_client()

    class _FakeGateway:
        def get_cache_stats(self):
            return {"cache_hits": 3, "cache_misses": 1, "cache_hit_rate": 0.75}

    monkeypatch.setattr(system_api, "get_inference_gateway", lambda: _FakeGateway())
    resp = client.get("/api/system/inference/cache/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("cache_hits") == 3
    assert body.get("cache_misses") == 1


def test_inference_cache_clear_endpoint_passes_model_alias(monkeypatch):
    client = _build_client()
    captured: dict[str, object] = {}

    class _FakeGateway:
        async def clear_cache(self, **kwargs):
            await asyncio.sleep(0)
            captured.update(kwargs)
            return {
                "cache_kind": kwargs.get("cache_kind", "generate"),
                "prefix": "openvitamin:inference:generate:u:u1",
                "memory_deleted": 1,
                "redis_deleted": 2,
                "total_deleted": 3,
            }

    monkeypatch.setattr(system_api, "get_inference_gateway", lambda: _FakeGateway())
    resp = client.post(
        "/api/system/inference/cache/clear",
        json={"cache_kind": "generate", "user_id": "u1", "model_alias": "reasoning-model"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("success") is True
    assert body.get("total_deleted") == 3
    assert captured.get("model_alias") == "reasoning-model"


def test_inference_cache_clear_without_scope_requires_force_all():
    client = _build_client()
    resp = client.post("/api/system/inference/cache/clear", json={"cache_kind": "generate"})
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("error", {}).get("code") == "inference_cache_clear_scope_required"


def test_inference_cache_clear_force_all_requires_confirm_text():
    client = _build_client()
    resp = client.post(
        "/api/system/inference/cache/clear",
        json={"cache_kind": "generate", "force_all": True},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("error", {}).get("code") == "inference_cache_clear_confirmation_required"


def test_inference_cache_clear_force_all_with_challenge(monkeypatch):
    client = _build_client()

    class _FakeGateway:
        async def clear_cache(self, **kwargs):
            await asyncio.sleep(0)
            return {
                "cache_kind": kwargs.get("cache_kind", "generate"),
                "prefix": "openvitamin:inference:generate",
                "memory_deleted": 2,
                "redis_deleted": 3,
                "total_deleted": 5,
            }

    monkeypatch.setattr(system_api, "get_inference_gateway", lambda: _FakeGateway())
    challenge_resp = client.post("/api/system/inference/cache/clear/challenge", headers={"X-User-Id": "u1"})
    assert challenge_resp.status_code == 200
    challenge = challenge_resp.json()
    assert challenge.get("challenge_id")
    assert challenge.get("challenge_code")

    clear_resp = client.post(
        "/api/system/inference/cache/clear",
        json={
            "cache_kind": "generate",
            "force_all": True,
            "challenge_id": challenge["challenge_id"],
            "confirm_text": challenge["challenge_code"],
        },
        headers={"X-User-Id": "u1"},
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json().get("total_deleted") == 5


def test_inference_cache_clear_challenge_cannot_cross_user(monkeypatch):
    client = _build_client()

    class _FakeGateway:
        async def clear_cache(self, **kwargs):
            await asyncio.sleep(0)
            return {"cache_kind": "generate", "prefix": "x", "memory_deleted": 0, "redis_deleted": 0, "total_deleted": 0}

    monkeypatch.setattr(system_api, "get_inference_gateway", lambda: _FakeGateway())
    challenge_resp = client.post("/api/system/inference/cache/clear/challenge", headers={"X-User-Id": "user-a"})
    assert challenge_resp.status_code == 200
    challenge = challenge_resp.json()

    cross_resp = client.post(
        "/api/system/inference/cache/clear",
        json={
            "cache_kind": "generate",
            "force_all": True,
            "challenge_id": challenge["challenge_id"],
            "confirm_text": challenge["challenge_code"],
        },
        headers={"X-User-Id": "user-b"},
    )
    assert cross_resp.status_code == 400
    assert cross_resp.json().get("error", {}).get("code") == "inference_cache_clear_confirmation_required"


def test_inference_cache_clear_challenge_rate_limited(monkeypatch):
    client = _build_client()
    monkeypatch.setattr(system_api.settings, "inference_cache_clear_challenge_rate_max_per_window", 2)
    monkeypatch.setattr(system_api.settings, "inference_cache_clear_challenge_rate_window_seconds", 60)
    system_api._INFERENCE_CACHE_CLEAR_CHALLENGE_RATE.clear()

    r1 = client.post("/api/system/inference/cache/clear/challenge", headers={"X-User-Id": "rate-user"})
    r2 = client.post("/api/system/inference/cache/clear/challenge", headers={"X-User-Id": "rate-user"})
    r3 = client.post("/api/system/inference/cache/clear/challenge", headers={"X-User-Id": "rate-user"})

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    body = r3.json()
    assert body.get("error", {}).get("code") == "inference_cache_clear_challenge_rate_limited"


def test_update_config_accepts_valid_smart_routing_policy(monkeypatch):
    client = _build_client()
    captured: dict[str, object] = {}

    class _FakeStore:
        def set_setting(self, key, value):
            captured[key] = value

    monkeypatch.setattr(system_api, "get_system_settings_store", lambda: _FakeStore())
    payload = {
        "inferenceSmartRoutingEnabled": True,
        "inferenceSmartRoutingPoliciesJson": '{"reasoning-model":{"strategy":"canary","stable":"stable-v1","canary":"canary-v2","canary_percent":10}}',
    }
    resp = client.post("/api/system/config", json=payload)
    assert resp.status_code == 200
    assert resp.json().get("success") is True
    assert captured.get("inferenceSmartRoutingEnabled") is True
    assert isinstance(captured.get("inferenceSmartRoutingPoliciesJson"), str)


def test_update_config_rejects_invalid_smart_routing_policy(monkeypatch):
    client = _build_client()

    class _FakeStore:
        def set_setting(self, key, value):
            raise AssertionError("set_setting should not be called for invalid payload")

    monkeypatch.setattr(system_api, "get_system_settings_store", lambda: _FakeStore())
    resp = client.post(
        "/api/system/config",
        json={
            "inferenceSmartRoutingPoliciesJson": '{"reasoning-model":{"strategy":"canary","stable":"stable-v1"}}'
        },
    )
    assert resp.status_code == 400
    assert resp.json().get("error", {}).get("code") == "system_config_invalid_smart_routing_policies_json"


def test_consume_cache_clear_challenge_rate_uses_redis(monkeypatch):
    class _FakeRedisCache:
        def __init__(self):
            self.current = 0

        async def incr_with_expire(self, key, ttl_seconds):
            await asyncio.sleep(0)
            self.current += 1
            return self.current

        async def ttl(self, key):
            await asyncio.sleep(0)
            return 42

    fake = _FakeRedisCache()
    monkeypatch.setattr(system_api, "get_redis_cache_client", lambda: fake)
    monkeypatch.setattr(system_api.settings, "inference_cache_clear_challenge_rate_max_per_window", 2)
    monkeypatch.setattr(system_api.settings, "inference_cache_clear_challenge_rate_window_seconds", 60)

    ok1, retry1 = asyncio.run(system_api._consume_cache_clear_challenge_rate("redis-user"))
    ok2, retry2 = asyncio.run(system_api._consume_cache_clear_challenge_rate("redis-user"))
    ok3, retry3 = asyncio.run(system_api._consume_cache_clear_challenge_rate("redis-user"))

    assert ok1 is True and retry1 == 0
    assert ok2 is True and retry2 == 0
    assert ok3 is False and retry3 == 42


def test_challenge_issue_and_validate_uses_redis(monkeypatch):
    class _FakeRedisCache:
        def __init__(self):
            self.store = {}

        async def set_json(self, key, payload, ttl_seconds):
            await asyncio.sleep(0)
            self.store[key] = dict(payload)

        async def get_json(self, key):
            await asyncio.sleep(0)
            payload = self.store.get(key)
            return dict(payload) if isinstance(payload, dict) else None

        async def delete(self, key):
            await asyncio.sleep(0)
            return self.store.pop(key, None) is not None

        async def incr_with_expire(self, key, ttl_seconds):
            await asyncio.sleep(0)
            return None

        async def ttl(self, key):
            await asyncio.sleep(0)
            if key in self.store:
                return 1
            return None

    fake = _FakeRedisCache()
    monkeypatch.setattr(system_api, "get_redis_cache_client", lambda: fake)
    system_api._INFERENCE_CACHE_CLEAR_CHALLENGES.clear()

    challenge_id, challenge_code = asyncio.run(system_api._issue_cache_clear_challenge("u-redis"))
    ok = asyncio.run(system_api._validate_cache_clear_challenge(challenge_id, challenge_code, "u-redis"))
    reused = asyncio.run(system_api._validate_cache_clear_challenge(challenge_id, challenge_code, "u-redis"))

    assert ok is True
    assert reused is False
