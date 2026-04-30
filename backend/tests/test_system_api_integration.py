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
    assert body.get("detail") == "invalid system feature flags"
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


def test_config_schema_endpoint_exposes_workflow_contract_policy_examples():
    client = _build_client()
    resp = client.get("/api/system/config/schema")
    assert resp.status_code == 200
    body = resp.json()
    assert "allowed_keys" in body
    assert "schema_hints" in body
    assert "examples" in body
    assert "query_examples" in body
    hints = body.get("schema_hints", {})
    assert "workflowContractRequiredInputAddedBreaking" in hints
    assert "workflowContractOutputAddedRisky" in hints
    assert "workflowContractFieldExemptions" in hints
    example = body.get("examples", {}).get("workflow_contract_policy", {})
    assert "workflowContractRequiredInputAddedBreaking" in example
    assert "workflowContractOutputAddedRisky" in example
    assert "workflowContractFieldExemptions" in example
    assert "workflowGovernanceHealthyThreshold" in hints
    assert "workflowGovernanceWarningThreshold" in hints
    query_examples = body.get("query_examples", {})
    assert "combined" in query_examples
    assert "compact=true" in str(query_examples.get("combined"))


def test_config_schema_endpoint_supports_keys_filter():
    client = _build_client()
    resp = client.get(
        "/api/system/config/schema",
        params={"keys": "workflowContractOutputAddedRisky,workflowContractFieldExemptions"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert sorted(body.get("allowed_keys", [])) == sorted(
        ["workflowContractOutputAddedRisky", "workflowContractFieldExemptions"]
    )
    hints = body.get("schema_hints", {})
    assert "workflowContractOutputAddedRisky" in hints
    assert "workflowContractFieldExemptions" in hints
    assert "workflowContractRequiredInputAddedBreaking" not in hints


def test_config_schema_endpoint_supports_repeated_keys_query():
    client = _build_client()
    resp = client.get(
        "/api/system/config/schema?keys=workflowContractOutputAddedRisky&keys=workflowContractFieldExemptions"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert sorted(body.get("allowed_keys", [])) == sorted(
        ["workflowContractOutputAddedRisky", "workflowContractFieldExemptions"]
    )


def test_config_schema_endpoint_can_skip_examples():
    client = _build_client()
    resp = client.get("/api/system/config/schema", params={"include_examples": "false"})
    assert resp.status_code == 200
    body = resp.json()
    assert "allowed_keys" in body
    assert "schema_hints" in body
    assert "examples" not in body


def test_config_schema_endpoint_compact_mode_trims_hint_fields():
    client = _build_client()
    resp = client.get("/api/system/config/schema", params={"compact": "true"})
    assert resp.status_code == 200
    body = resp.json()
    hints = body.get("schema_hints", {})
    assert "workflowContractOutputAddedRisky" in hints
    hint = hints["workflowContractOutputAddedRisky"]
    assert set(hint.keys()).issubset({"type", "default", "recommended"})
    assert "description" not in hint


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


def test_runtime_metrics_endpoint_includes_priority_slo_panel(monkeypatch):
    client = _build_client()

    class _FakeRuntimeMetrics:
        def get_metrics(self):
            return {
                "summary": {"total_requests": 5, "total_requests_failed": 1, "total_latency_ms": 1000.0, "total_tokens_generated": 200, "models_count": 1},
                "by_priority_summary": {
                    "high": {
                        "requests": 3,
                        "requests_failed": 0,
                        "avg_latency_ms": 120.0,
                        "p95_latency_ms": 210.0,
                        "slo_target_ms": 3000,
                        "slo_met_count": 3,
                        "slo_met_rate": 1.0,
                    }
                },
                "by_model": {},
            }

    class _FakeQueue:
        preemptions_total = 2
        preemption_skipped_limit_total = 1
        preemption_skipped_cooldown_total = 4

    class _FakeQueueManager:
        def list_queues(self):
            return {"model-a": _FakeQueue()}

    monkeypatch.setattr("core.runtime.get_runtime_metrics", lambda: _FakeRuntimeMetrics())
    monkeypatch.setattr("core.runtime.get_inference_queue_manager", lambda: _FakeQueueManager())
    monkeypatch.setattr(system_api, "get_inference_priority_panel_high_slo_critical_rate", lambda: 0.95)
    monkeypatch.setattr(system_api, "get_inference_priority_panel_high_slo_warning_rate", lambda: 0.99)
    monkeypatch.setattr(
        system_api,
        "get_inference_priority_panel_preemption_cooldown_busy_threshold",
        lambda: 10,
    )
    resp = client.get("/api/system/runtime-metrics")
    assert resp.status_code == 200
    body = resp.json()
    panel = body.get("priority_slo_panel", {})
    assert panel.get("high_priority", {}).get("p95_latency_ms") == pytest.approx(210.0)
    assert panel.get("high_priority", {}).get("slo_met_rate") == pytest.approx(1.0)
    preemption = panel.get("queue_preemption", {})
    assert preemption.get("preemptions_total") == 2
    assert preemption.get("preemption_skipped_limit_total") == 1
    assert preemption.get("preemption_skipped_cooldown_total") == 4
    assert preemption.get("by_model", {}).get("model-a", {}).get("preemptions_total") == 2
    thresholds = panel.get("thresholds", {})
    assert thresholds.get("high_slo_critical_rate") == pytest.approx(0.95)
    assert thresholds.get("high_slo_warning_rate") == pytest.approx(0.99)
    assert thresholds.get("preemption_cooldown_busy_threshold") == 10


def test_inference_cache_clear_endpoint_passes_model_alias(monkeypatch):
    client = _build_client()
    captured: dict[str, object] = {}

    class _FakeGateway:
        async def clear_cache(self, **kwargs):
            await asyncio.sleep(0)
            captured.update(kwargs)
            return {
                "cache_kind": kwargs.get("cache_kind", "generate"),
                "prefix": "perilla:inference:generate:u:u1",
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
                "prefix": "perilla:inference:generate",
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
        "workflowContractRequiredInputAddedBreaking": False,
        "workflowContractOutputAddedRisky": True,
        "workflowContractFieldExemptions": "input.age,output.debug",
        "workflowGovernanceHealthyThreshold": 0.1,
        "workflowGovernanceWarningThreshold": 0.3,
    }
    resp = client.post("/api/system/config", json=payload)
    assert resp.status_code == 200
    assert resp.json().get("success") is True
    assert captured.get("inferenceSmartRoutingEnabled") is True
    assert isinstance(captured.get("inferenceSmartRoutingPoliciesJson"), str)
    assert captured.get("workflowContractRequiredInputAddedBreaking") is False
    assert captured.get("workflowContractOutputAddedRisky") is True
    assert captured.get("workflowContractFieldExemptions") == "input.age,output.debug"
    assert float(captured.get("workflowGovernanceHealthyThreshold")) == pytest.approx(0.1)
    assert float(captured.get("workflowGovernanceWarningThreshold")) == pytest.approx(0.3)


def test_update_config_rejects_invalid_governance_threshold_order(monkeypatch):
    client = _build_client()

    class _FakeStore:
        def set_setting(self, key, value):
            raise AssertionError("set_setting should not be called for invalid payload")

    monkeypatch.setattr(system_api, "get_system_settings_store", lambda: _FakeStore())
    resp = client.post(
        "/api/system/config",
        json={
            "workflowGovernanceHealthyThreshold": 0.4,
            "workflowGovernanceWarningThreshold": 0.2,
        },
    )
    assert resp.status_code == 400
    assert resp.json().get("error", {}).get("code") == "system_config_invalid_governance_thresholds"


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


def test_event_bus_dlq_replay_idempotency_hit_returns_cached_result(monkeypatch):
    client = _build_client()
    calls = {"n": 0}

    class _FakeDB:
        def commit(self):
            return None

        def close(self):
            return None

    class _FakeRecord:
        def __init__(self, request_hash: str):
            self.request_hash = request_hash
            self.status = "processing"
            self.error_message = None
            self.response_ref = None

    class _FakeClaim:
        def __init__(self, record, is_new: bool, conflict: bool):
            self.record = record
            self.is_new = is_new
            self.conflict = conflict

    class _FakeIdempotencyService:
        _store: dict[tuple[str, str, str], _FakeRecord] = {}

        def __init__(self, db):
            self.db = db

        def claim(self, *, scope, owner_id, key, request_hash, ttl_seconds=3600):
            _ = ttl_seconds
            k = (scope, owner_id, key)
            row = self._store.get(k)
            if row is not None:
                return _FakeClaim(row, is_new=False, conflict=row.request_hash != request_hash)
            row = _FakeRecord(request_hash=request_hash)
            self._store[k] = row
            return _FakeClaim(row, is_new=True, conflict=False)

    async def _fake_replay(**kwargs):
        _ = kwargs
        await asyncio.sleep(0)
        calls["n"] += 1
        return {"dry_run": False, "candidate": 1, "replayed": 1, "failed": 0, "grouped": {"x": {"total": 1, "replayed": 1, "failed": 0}}}

    monkeypatch.setattr(system_api, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(system_api, "IdempotencyService", _FakeIdempotencyService)
    monkeypatch.setattr(system_api, "replay_event_bus_dlq", _fake_replay)

    headers = {"Idempotency-Key": "idem-replay-hit-1"}
    body = {"confirm": True, "dry_run": False, "limit": 1}
    resp1 = client.post("/api/system/event-bus/dlq/replay", json=body, headers=headers)
    resp2 = client.post("/api/system/event-bus/dlq/replay", json=body, headers=headers)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert calls["n"] == 1
    assert resp2.json().get("replayed") == 1


def test_event_bus_dlq_replay_idempotency_conflict(monkeypatch):
    client = _build_client()

    class _FakeDB:
        def commit(self):
            return None

        def close(self):
            return None

    class _FakeRecord:
        def __init__(self, request_hash: str):
            self.request_hash = request_hash
            self.status = "processing"
            self.error_message = None
            self.response_ref = None

    class _FakeClaim:
        def __init__(self, record, is_new: bool, conflict: bool):
            self.record = record
            self.is_new = is_new
            self.conflict = conflict

    class _FakeIdempotencyService:
        _store: dict[tuple[str, str, str], _FakeRecord] = {}

        def __init__(self, db):
            self.db = db

        def claim(self, *, scope, owner_id, key, request_hash, ttl_seconds=3600):
            _ = ttl_seconds
            k = (scope, owner_id, key)
            row = self._store.get(k)
            if row is not None:
                return _FakeClaim(row, is_new=False, conflict=row.request_hash != request_hash)
            row = _FakeRecord(request_hash=request_hash)
            self._store[k] = row
            return _FakeClaim(row, is_new=True, conflict=False)

    async def _fake_replay(**kwargs):
        _ = kwargs
        await asyncio.sleep(0)
        return {"dry_run": False, "candidate": 1, "replayed": 1, "failed": 0, "grouped": {}}

    monkeypatch.setattr(system_api, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(system_api, "IdempotencyService", _FakeIdempotencyService)
    monkeypatch.setattr(system_api, "replay_event_bus_dlq", _fake_replay)

    headers = {"Idempotency-Key": "idem-replay-conflict-1"}
    resp1 = client.post("/api/system/event-bus/dlq/replay", json={"confirm": True, "dry_run": False, "limit": 1}, headers=headers)
    resp2 = client.post("/api/system/event-bus/dlq/replay", json={"confirm": True, "dry_run": True, "limit": 1}, headers=headers)

    assert resp1.status_code == 200
    assert resp2.status_code == 409
    assert resp2.json().get("error", {}).get("code") == "idempotency_conflict"


def test_event_bus_dlq_replay_dry_run_response_shape(monkeypatch):
    client = _build_client()

    async def _fake_replay(**kwargs):
        await asyncio.sleep(0)
        assert kwargs.get("dry_run") is True
        return {
            "dry_run": True,
            "candidate": 3,
            "replayed": 0,
            "failed": 0,
            "grouped": {"agent.status.changed": {"total": 3, "replayed": 0, "failed": 0}},
        }

    monkeypatch.setattr(system_api, "replay_event_bus_dlq", _fake_replay)

    resp = client.post(
        "/api/system/event-bus/dlq/replay",
        json={"confirm": True, "dry_run": True, "limit": 5, "event_type": "agent.status.changed"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("success") is True
    assert body.get("dry_run") is True
    assert body.get("candidate") == 3
    assert "agent.status.changed" in (body.get("grouped") or {})


def test_event_bus_dlq_replay_rate_limited_returns_structured_error(monkeypatch):
    client = _build_client()

    async def _fake_replay(**kwargs):
        _ = kwargs
        await asyncio.sleep(0)
        raise RuntimeError("event bus replay is rate limited by min interval")

    monkeypatch.setattr(system_api, "replay_event_bus_dlq", _fake_replay)

    resp = client.post(
        "/api/system/event-bus/dlq/replay",
        json={"confirm": True, "dry_run": False, "limit": 1},
    )
    assert resp.status_code == 429
    body = resp.json()
    assert body.get("error", {}).get("code") == "event_bus_dlq_replay_rate_limited"


def test_event_bus_dlq_clear_requires_confirm():
    client = _build_client()
    resp = client.post("/api/system/event-bus/dlq/clear", json={"confirm": False})
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("error", {}).get("code") == "event_bus_dlq_clear_confirmation_required"


def test_event_bus_dlq_replay_requires_confirm():
    client = _build_client()
    resp = client.post(
        "/api/system/event-bus/dlq/replay",
        json={"confirm": False, "dry_run": True, "limit": 5},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("error", {}).get("code") == "event_bus_dlq_replay_confirmation_required"


def test_event_bus_dlq_limit_validation():
    client = _build_client()
    resp = client.get("/api/system/event-bus/dlq", params={"limit": 0})
    assert resp.status_code == 422


@pytest.mark.parametrize("header_name", ["Idempotency-Key", "X-Idempotency-Key", "X-Request-Id"])
def test_event_bus_dlq_replay_accepts_multiple_idempotency_headers(monkeypatch, header_name: str):
    client = _build_client()
    calls = {"n": 0}

    class _FakeDB:
        def commit(self):
            return None

        def close(self):
            return None

    class _FakeRecord:
        def __init__(self, request_hash: str):
            self.request_hash = request_hash
            self.status = "processing"
            self.error_message = None
            self.response_ref = None

    class _FakeClaim:
        def __init__(self, record, is_new: bool, conflict: bool):
            self.record = record
            self.is_new = is_new
            self.conflict = conflict

    class _FakeIdempotencyService:
        _store: dict[tuple[str, str, str], _FakeRecord] = {}

        def __init__(self, db):
            self.db = db

        def claim(self, *, scope, owner_id, key, request_hash, ttl_seconds=3600):
            _ = ttl_seconds
            k = (scope, owner_id, key)
            row = self._store.get(k)
            if row is not None:
                return _FakeClaim(row, is_new=False, conflict=row.request_hash != request_hash)
            row = _FakeRecord(request_hash=request_hash)
            self._store[k] = row
            return _FakeClaim(row, is_new=True, conflict=False)

    async def _fake_replay(**kwargs):
        _ = kwargs
        await asyncio.sleep(0)
        calls["n"] += 1
        return {"dry_run": False, "candidate": 1, "replayed": 1, "failed": 0, "grouped": {}}

    monkeypatch.setattr(system_api, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(system_api, "IdempotencyService", _FakeIdempotencyService)
    monkeypatch.setattr(system_api, "replay_event_bus_dlq", _fake_replay)

    headers = {header_name: f"idem-{header_name}"}
    body = {"confirm": True, "dry_run": False, "limit": 1}
    resp1 = client.post("/api/system/event-bus/dlq/replay", json=body, headers=headers)
    resp2 = client.post("/api/system/event-bus/dlq/replay", json=body, headers=headers)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert calls["n"] == 1


def test_event_bus_dlq_replay_idempotency_header_priority(monkeypatch):
    client = _build_client()
    observed = {"key": None}

    class _FakeDB:
        def commit(self):
            return None

        def close(self):
            return None

    class _FakeRecord:
        def __init__(self, request_hash: str):
            self.request_hash = request_hash
            self.status = "processing"
            self.error_message = None
            self.response_ref = None

    class _FakeClaim:
        def __init__(self, record, is_new: bool, conflict: bool):
            self.record = record
            self.is_new = is_new
            self.conflict = conflict

    class _FakeIdempotencyService:
        def __init__(self, db):
            self.db = db

        def claim(self, *, scope, owner_id, key, request_hash, ttl_seconds=3600):
            _ = (scope, owner_id, request_hash, ttl_seconds)
            observed["key"] = key
            return _FakeClaim(_FakeRecord(request_hash=request_hash), is_new=True, conflict=False)

    async def _fake_replay(**kwargs):
        _ = kwargs
        await asyncio.sleep(0)
        return {"dry_run": False, "candidate": 1, "replayed": 1, "failed": 0, "grouped": {}}

    monkeypatch.setattr(system_api, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(system_api, "IdempotencyService", _FakeIdempotencyService)
    monkeypatch.setattr(system_api, "replay_event_bus_dlq", _fake_replay)

    headers = {
        "Idempotency-Key": "primary-key",
        "X-Idempotency-Key": "secondary-key",
        "X-Request-Id": "request-id-key",
    }
    resp = client.post(
        "/api/system/event-bus/dlq/replay",
        json={"confirm": True, "dry_run": False, "limit": 1},
        headers=headers,
    )
    assert resp.status_code == 200
    assert observed["key"] == "primary-key"


def test_event_bus_dlq_replay_idempotency_in_progress(monkeypatch):
    client = _build_client()

    class _FakeDB:
        def commit(self):
            return None

        def close(self):
            return None

    class _FakeRecord:
        def __init__(self):
            self.request_hash = "h1"
            self.status = "processing"
            self.error_message = None
            self.response_ref = None

    class _FakeClaim:
        def __init__(self, record, is_new: bool, conflict: bool):
            self.record = record
            self.is_new = is_new
            self.conflict = conflict

    class _FakeIdempotencyService:
        def __init__(self, db):
            self.db = db

        def claim(self, **kwargs):
            _ = kwargs
            return _FakeClaim(_FakeRecord(), is_new=False, conflict=False)

    monkeypatch.setattr(system_api, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(system_api, "IdempotencyService", _FakeIdempotencyService)

    resp = client.post(
        "/api/system/event-bus/dlq/replay",
        headers={"Idempotency-Key": "idem-replay-processing"},
        json={"confirm": True, "dry_run": False, "limit": 1},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body.get("error", {}).get("code") == "idempotency_in_progress"


def test_event_bus_dlq_replay_idempotency_previous_failed(monkeypatch):
    client = _build_client()

    class _FakeDB:
        def commit(self):
            return None

        def close(self):
            return None

    class _FakeRecord:
        def __init__(self):
            self.request_hash = "h1"
            self.status = "failed"
            self.error_message = "previous replay failed"
            self.response_ref = None

    class _FakeClaim:
        def __init__(self, record, is_new: bool, conflict: bool):
            self.record = record
            self.is_new = is_new
            self.conflict = conflict

    class _FakeIdempotencyService:
        def __init__(self, db):
            self.db = db

        def claim(self, **kwargs):
            _ = kwargs
            return _FakeClaim(_FakeRecord(), is_new=False, conflict=False)

    monkeypatch.setattr(system_api, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(system_api, "IdempotencyService", _FakeIdempotencyService)

    resp = client.post(
        "/api/system/event-bus/dlq/replay",
        headers={"Idempotency-Key": "idem-replay-failed"},
        json={"confirm": True, "dry_run": False, "limit": 1},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body.get("error", {}).get("code") == "idempotency_previous_failed"


def test_roadmap_kpi_update_and_fetch_roundtrip(monkeypatch):
    client = _build_client()
    store = {}

    def _fake_get():
        return store.get("kpis", {"availability_min": 0.999})

    def _fake_save(payload):
        merged = {**_fake_get(), **payload}
        store["kpis"] = merged
        return merged

    monkeypatch.setattr(system_api, "get_roadmap_kpis", _fake_get)
    monkeypatch.setattr(system_api, "save_roadmap_kpis", _fake_save)

    post_resp = client.post("/api/system/roadmap/kpis", json={"p99_latency_ms_max": 2200})
    assert post_resp.status_code == 200
    assert post_resp.json().get("kpis", {}).get("p99_latency_ms_max") == 2200

    get_resp = client.get("/api/system/roadmap/kpis")
    assert get_resp.status_code == 200
    assert get_resp.json().get("kpis", {}).get("availability_min") == pytest.approx(0.999)


def test_roadmap_phase_status_endpoint_returns_gate_summary(monkeypatch):
    client = _build_client()
    monkeypatch.setattr(system_api, "build_roadmap_snapshot", lambda: {"online_error_rate": 0.001, "capabilities": {}})
    monkeypatch.setattr(system_api, "get_roadmap_kpis", lambda: {"availability_min": 0.999})
    monkeypatch.setattr(system_api, "get_phase_gates", lambda: {"phase0_foundation": {"required_capabilities": [], "required_kpis": {}}})
    monkeypatch.setattr(
        system_api,
        "evaluate_north_star",
        lambda snapshot, kpis: type("Eval", (), {"score": 1.0, "passed": True, "reasons": ["ok"]})(),
    )
    monkeypatch.setattr(
        system_api,
        "evaluate_phase_gates",
        lambda snapshot, gates: {"phase0_foundation": {"passed": True, "missing_capabilities": [], "kpi_results": {}}},
    )

    resp = client.get("/api/system/roadmap/phases/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("north_star", {}).get("passed") is True
    assert body.get("phase_gate", {}).get("passed_count") == 1


def test_roadmap_monthly_review_create_and_list(monkeypatch):
    client = _build_client()
    monkeypatch.setattr(
        system_api,
        "create_monthly_review",
        lambda: {"go_no_go": "go", "north_star": {"passed": True}, "phase_gate": {"passed": True}},
    )
    monkeypatch.setattr(system_api, "list_monthly_reviews", lambda limit=12: [{"go_no_go": "go"}][:limit])

    create_resp = client.post("/api/system/roadmap/monthly-review")
    assert create_resp.status_code == 200
    assert create_resp.json().get("review", {}).get("go_no_go") == "go"

    list_resp = client.get("/api/system/roadmap/monthly-review", params={"limit": 5})
    assert list_resp.status_code == 200
    assert list_resp.json().get("count") == 1
