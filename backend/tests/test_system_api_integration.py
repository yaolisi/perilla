from __future__ import annotations

import asyncio
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

from api import system as system_api

from tests.helpers import make_fastapi_app_router_only


def _override_get_db_with_fake(client: TestClient, fake_db: object) -> None:
    """让 event-bus replay 等路由使用与集成测试一致的 fake Session（替代已移除的 SessionLocal monkeypatch）。"""

    def _gen(_request: Request):
        yield fake_db  # type: ignore[misc]

    client.app.dependency_overrides[system_api.get_db] = _gen


def _build_client() -> TestClient:
    app = make_fastapi_app_router_only(system_api)

    @app.middleware("http")
    async def _inject_test_user(request, call_next):  # type: ignore[no-untyped-def]
        request.state.user_id = request.headers.get("X-User-Id")
        return await call_next(request)

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
    assert "workflowSchedulerMaxConcurrency" in hints
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


def test_update_config_accepts_torch_stream_settings(monkeypatch):
    client = _build_client()
    captured: dict[str, object] = {}

    class _FakeStore:
        def set_setting(self, key, value):
            captured[key] = value

    monkeypatch.setattr(system_api, "get_system_settings_store", lambda: _FakeStore())
    resp = client.post(
        "/api/system/config",
        json={
            "torchStreamThreadJoinTimeoutSec": 120,
            "torchStreamChunkQueueMax": 32,
            "chatStreamWallClockMaxSeconds": 1800,
            "chatStreamResumeCancelUpstreamOnDisconnect": True,
        },
    )
    assert resp.status_code == 200
    assert resp.json().get("success") is True
    assert captured.get("torchStreamThreadJoinTimeoutSec") == 120
    assert captured.get("torchStreamChunkQueueMax") == 32
    assert captured.get("chatStreamWallClockMaxSeconds") == 1800
    assert captured.get("chatStreamResumeCancelUpstreamOnDisconnect") is True


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
        _store: dict[tuple[str, str, str, str], _FakeRecord] = {}

        def __init__(self, db):
            self.db = db

        def claim(self, *, scope, owner_id, key, request_hash, ttl_seconds=3600, tenant_id=None):
            _ = ttl_seconds
            k = ((tenant_id or "default"), scope, owner_id, key)
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

    _override_get_db_with_fake(client, _FakeDB())
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
        _store: dict[tuple[str, str, str, str], _FakeRecord] = {}

        def __init__(self, db):
            self.db = db

        def claim(self, *, scope, owner_id, key, request_hash, ttl_seconds=3600, tenant_id=None):
            _ = ttl_seconds
            k = ((tenant_id or "default"), scope, owner_id, key)
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

    _override_get_db_with_fake(client, _FakeDB())
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
        _store: dict[tuple[str, str, str, str], _FakeRecord] = {}

        def __init__(self, db):
            self.db = db

        def claim(self, *, scope, owner_id, key, request_hash, ttl_seconds=3600, tenant_id=None):
            _ = ttl_seconds
            k = ((tenant_id or "default"), scope, owner_id, key)
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

    _override_get_db_with_fake(client, _FakeDB())
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

        def claim(self, *, scope, owner_id, key, request_hash, ttl_seconds=3600, tenant_id=None):
            _ = (scope, owner_id, request_hash, ttl_seconds, tenant_id)
            observed["key"] = key
            return _FakeClaim(_FakeRecord(request_hash=request_hash), is_new=True, conflict=False)

    async def _fake_replay(**kwargs):
        _ = kwargs
        await asyncio.sleep(0)
        return {"dry_run": False, "candidate": 1, "replayed": 1, "failed": 0, "grouped": {}}

    _override_get_db_with_fake(client, _FakeDB())
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

    _override_get_db_with_fake(client, _FakeDB())
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

    _override_get_db_with_fake(client, _FakeDB())
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


def test_roadmap_phase_gates_post_returns_success_and_merged(monkeypatch):
    client = _build_client()
    store: dict = {}

    def _fake_get():
        return store.get(
            "gates",
            {"phase0_foundation": {"required_capabilities": [], "required_kpis": {}}},
        )

    def _fake_save(payload):
        merged = {**_fake_get(), **payload}
        store["gates"] = merged
        return merged

    monkeypatch.setattr(system_api, "save_phase_gates", _fake_save)

    post_resp = client.post(
        "/api/system/roadmap/phase-gates",
        json={
            "phase_gates": {
                "phase1_core": {"required_capabilities": ["throughput"], "required_kpis": {"throughput_gain": 2.0}},
            },
        },
    )
    assert post_resp.status_code == 200
    body = post_resp.json()
    assert body.get("success") is True
    gates = body.get("phase_gates") or {}
    assert "phase0_foundation" in gates
    assert gates.get("phase1_core", {}).get("required_capabilities") == ["throughput"]


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
        lambda snapshot, gates: {
            "phase0_foundation": {
                "passed": True,
                "missing_capabilities": [],
                "kpi_results": {},
                "readiness": {"score": 1.0},
            }
        },
    )

    resp = client.get("/api/system/roadmap/phases/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("north_star", {}).get("passed") is True
    assert body.get("phase_gate", {}).get("passed_count") == 1
    assert body.get("go_no_go") in {"go", "no_go"}
    assert isinstance(body.get("go_no_go_reasons"), list)
    assert isinstance(body.get("phase_gate", {}).get("readiness_summary"), dict)
    assert "top_blocker_capability" in body


def test_roadmap_phase_status_blocking_capabilities_sorted(monkeypatch):
    client = _build_client()
    monkeypatch.setattr(system_api, "build_roadmap_snapshot", lambda: {"online_error_rate": 0.001})
    monkeypatch.setattr(system_api, "get_roadmap_kpis", lambda: {"availability_min": 0.999})
    monkeypatch.setattr(
        system_api,
        "get_phase_gates",
        lambda: {
            "phase1_core": {"required_capabilities": [], "required_kpis": {}},
            "phase2_advanced": {"required_capabilities": [], "required_kpis": {}},
        },
    )
    monkeypatch.setattr(
        system_api,
        "evaluate_north_star",
        lambda snapshot, kpis: type("Eval", (), {"score": 1.0, "passed": True, "reasons": ["ok"]})(),
    )
    monkeypatch.setattr(
        system_api,
        "evaluate_phase_gates",
        lambda snapshot, gates: {
            "phase1_core": {
                "passed": False,
                "missing_capabilities": ["hybrid_retrieval", "dynamic_batching"],
                "missing_capability_details": {
                    "hybrid_retrieval": {"enabled": False, "source": "rag_plugin_manifest", "signals": {}},
                    "dynamic_batching": {"enabled": False, "source": "runtime_settings", "signals": {}},
                },
                "kpi_results": {},
            },
            "phase2_advanced": {
                "passed": False,
                "missing_capabilities": ["hybrid_retrieval"],
                "missing_capability_details": {
                    "hybrid_retrieval": {"enabled": False, "source": "rag_plugin_manifest", "signals": {}},
                },
                "kpi_results": {},
            },
        },
    )

    resp = client.get("/api/system/roadmap/phases/status")
    assert resp.status_code == 200
    blocking = resp.json().get("phase_gate", {}).get("blocking_capabilities", [])
    assert isinstance(blocking, list)
    assert blocking[0]["capability"] == "hybrid_retrieval"
    assert blocking[0]["phase_count"] == 2
    assert set(blocking[0]["blocked_phases"]) == {"phase1_core", "phase2_advanced"}


def test_roadmap_capabilities_merge_auto_and_manual(monkeypatch):
    monkeypatch.setattr(
        system_api,
        "_detect_roadmap_capabilities",
        lambda: {"dynamic_batching": True, "hybrid_retrieval": False},
    )
    monkeypatch.setattr(
        system_api,
        "_read_manual_roadmap_capabilities",
        lambda: {"hybrid_retrieval": True, "function_calling_orchestration": True},
    )
    merged = system_api._read_roadmap_capabilities()
    assert merged["dynamic_batching"] is True
    # 手工开关优先级更高，覆盖自动探测结果
    assert merged["hybrid_retrieval"] is True
    assert merged["function_calling_orchestration"] is True


def test_roadmap_phase_status_includes_auto_detected_capabilities(monkeypatch):
    client = _build_client()
    monkeypatch.setattr(system_api, "build_roadmap_snapshot", lambda: {"online_error_rate": 0.001})
    monkeypatch.setattr(
        system_api,
        "_read_roadmap_capabilities",
        lambda: {
            "dynamic_batching": True,
            "hybrid_retrieval": True,
            "function_calling_orchestration": False,
            "agent_role_collaboration": False,
        },
    )
    monkeypatch.setattr(
        system_api,
        "_detect_roadmap_capability_details",
        lambda: {
            "dynamic_batching": {"source": "runtime_settings", "enabled": True, "signals": {"continuous_batch_enabled": True}},
            "hybrid_retrieval": {"source": "rag_plugin_manifest", "enabled": True, "signals": {"manifest_exists": True}},
        },
    )
    resp = client.get("/api/system/roadmap/phases/status")
    assert resp.status_code == 200
    snapshot = resp.json().get("snapshot", {})
    capabilities = snapshot.get("capabilities", {})
    assert capabilities.get("dynamic_batching") is True
    assert capabilities.get("hybrid_retrieval") is True
    capability_details = snapshot.get("capability_details", {})
    assert capability_details.get("dynamic_batching", {}).get("source") == "runtime_settings"
    assert capability_details.get("hybrid_retrieval", {}).get("signals", {}).get("manifest_exists") is True


def test_detect_roadmap_capabilities_includes_phase2_and_phase3_keys(monkeypatch):
    monkeypatch.setattr(system_api, "_list_agents_for_capability_detection", lambda: [])
    monkeypatch.setattr(system_api, "_detect_dynamic_batching_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_hybrid_retrieval_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_multi_hop_retrieval_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_kg_augmented_rag_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_active_learning_reviewed_update_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_anomaly_detection_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_cluster_scaling_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_model_version_governance_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_sso_integration_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_multimodal_pilot_capability", lambda: True)

    caps = system_api._detect_roadmap_capabilities()
    assert caps["multi_hop_retrieval"] is True
    assert caps["multi_hop_retrieval_system"] is True
    assert caps["kg_augmented_rag"] is True
    assert caps["active_learning_reviewed_update"] is True
    assert caps["anomaly_detection"] is True
    assert caps["cluster_scaling"] is True
    assert caps["model_version_governance"] is True
    assert caps["sso_integration"] is True
    assert caps["multimodal_pilot"] is True


def test_detect_roadmap_capability_details_includes_phase2_and_phase3_keys(monkeypatch):
    monkeypatch.setattr(system_api, "_list_agents_for_capability_detection", lambda: [])
    monkeypatch.setattr(system_api, "_detect_dynamic_batching_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_hybrid_retrieval_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_multi_hop_retrieval_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_kg_augmented_rag_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_active_learning_reviewed_update_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_anomaly_detection_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_cluster_scaling_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_model_version_governance_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_sso_integration_capability", lambda: True)
    monkeypatch.setattr(system_api, "_detect_multimodal_pilot_capability", lambda: True)
    monkeypatch.setattr(
        system_api,
        "build_roadmap_snapshot",
        lambda: {"anomaly_signals": {"anomaly_detected": True, "breached_metrics": ["online_error_rate"]}},
    )

    details = system_api._detect_roadmap_capability_details()
    assert details["multi_hop_retrieval"]["enabled"] is True
    assert details["multi_hop_retrieval_system"]["enabled"] is True
    assert details["kg_augmented_rag"]["signals"]["search_graph_relations_available"] is True
    assert details["active_learning_reviewed_update"]["signals"]["manual_quality_metrics_save_available"] is True
    assert details["anomaly_detection"]["signals"]["chaos_threshold_keys_present"] is True
    assert details["anomaly_detection"]["signals"]["anomaly_detected"] is True
    assert details["anomaly_detection"]["signals"]["breached_metrics"] == ["online_error_rate"]
    assert details["cluster_scaling"]["enabled"] is True
    assert details["model_version_governance"]["enabled"] is True
    assert details["sso_integration"]["enabled"] is True
    assert details["multimodal_pilot"]["enabled"] is True


def test_roadmap_monthly_review_create_and_list(monkeypatch):
    client = _build_client()
    captured = {}

    def _fake_create_monthly_review(*args, **kwargs):
        captured["kwargs"] = kwargs
        return {
            "go_no_go": "go",
            "go_no_go_reasons": [{"type": "summary", "message": "north_star_and_phase_gates_passed"}],
            "top_blocker_capability": None,
            "north_star": {"passed": True},
            "phase_gate": {"passed": True, "blocking_capabilities": []},
        }

    monkeypatch.setattr(
        system_api,
        "create_monthly_review",
        _fake_create_monthly_review,
    )
    monkeypatch.setattr(
        system_api,
        "list_monthly_reviews_page",
        lambda limit=12, offset=0, top_blocker_capability=None, go_no_go=None, lowest_readiness_phase=None, readiness_below_threshold=None, max_lowest_readiness_score=None: (
            [{"go_no_go": "go"}][offset : offset + limit],
            1,
        ),
    )
    monkeypatch.setattr(system_api, "_read_roadmap_capabilities", lambda: {"dynamic_batching": True})
    monkeypatch.setattr(
        system_api,
        "_detect_roadmap_capability_details",
        lambda: {"dynamic_batching": {"enabled": True, "source": "runtime_settings", "signals": {}}},
    )

    create_resp = client.post("/api/system/roadmap/monthly-review")
    assert create_resp.status_code == 200
    assert create_resp.json().get("review", {}).get("go_no_go") == "go"
    assert isinstance(create_resp.json().get("review", {}).get("go_no_go_reasons"), list)
    assert "top_blocker_capability" in create_resp.json().get("review", {})
    assert "blocking_capabilities" in create_resp.json().get("review", {}).get("phase_gate", {})
    assert captured.get("kwargs", {}).get("capabilities", {}).get("dynamic_batching") is True
    assert captured.get("kwargs", {}).get("capability_details", {}).get("dynamic_batching", {}).get("enabled") is True

    list_resp = client.get("/api/system/roadmap/monthly-review", params={"limit": 5})
    assert list_resp.status_code == 200
    assert list_resp.json().get("count") == 1


def test_roadmap_end_to_end_with_real_store_and_snapshot():
    client = _build_client()
    from core.data.base import Base, get_engine
    from core.data.models.system import SystemSetting  # noqa: F401
    from core.data.models.audit import AuditLogORM  # noqa: F401

    Base.metadata.create_all(get_engine())

    store = system_api.get_system_settings_store()
    keys = [
        "roadmap_kpis",
        "roadmap_kpis_meta",
        "roadmap_quality_metrics",
        "roadmap_quality_metrics_explicit_keys",
        "roadmap_monthly_reviews",
        "roadmapCapabilitiesJson",
    ]
    backup = {key: store.get_setting(key, None) for key in keys}

    try:
        # 1) 冻结 KPI（真实 store）
        kpi_resp = client.post(
            "/api/system/roadmap/kpis",
            json={
                "availability_min": 0.99,
                "p99_latency_ms_max": 5000,
                "observability_coverage_min": 0.5,
            },
        )
        assert kpi_resp.status_code == 200
        assert kpi_resp.json().get("kpis", {}).get("p99_latency_ms_max") == 5000

        # 2) 写入质量指标（真实 store）
        quality_resp = client.post(
            "/api/system/roadmap/quality-metrics",
            json={
                "rag_top5_recall": 0.9,
                "answer_usefulness": 0.91,
                "unit_cost_reduction": 0.35,
                "observability_coverage": 1.0,
                "critical_security_incidents": 0,
                "throughput_gain": 3.0,
                "multi_hop_accuracy_gain": 0.2,
                "hallucination_reduction": 0.25,
                "auto_scaling_trigger_success_rate": 0.995,
                "rollback_time_seconds": 120,
            },
        )
        assert quality_resp.status_code == 200

        # 3) 注入 capability 开关（走系统配置接口，真实持久化路径）
        cfg_resp = client.post(
            "/api/system/config",
            json={
                "roadmapCapabilitiesJson": '{"fine_grained_permissions":true,"audit_traceability":true,'
                '"observability_dashboard":true,"rag_eval_baseline":true,"dynamic_batching":true,'
                '"hybrid_retrieval":true,"function_calling_orchestration":true,'
                '"agent_role_collaboration":true,"multi_hop_retrieval":true,"kg_augmented_rag":true,'
                '"active_learning_reviewed_update":true,"anomaly_detection":true,"cluster_scaling":true,'
                '"model_version_governance":true,"sso_integration":true,"multimodal_pilot":true}',
            },
        )
        assert cfg_resp.status_code == 200

        # 4) 读取阶段状态（真实 snapshot + 真实评估）
        phase_resp = client.get("/api/system/roadmap/phases/status")
        assert phase_resp.status_code == 200
        phase_body = phase_resp.json()
        assert "snapshot" in phase_body
        assert "north_star" in phase_body
        assert "phase_gate" in phase_body
        assert isinstance(phase_body.get("phase_gate", {}).get("total_count"), int)

        # 5) 触发一次月度复盘，并确保可被查询到
        create_resp = client.post("/api/system/roadmap/monthly-review")
        assert create_resp.status_code == 200
        review = create_resp.json().get("review", {})
        assert review.get("go_no_go") in {"go", "no_go"}
        assert "top_blocker_capability" in review
        assert "north_star" in review
        assert "phase_gate" in review

        list_resp = client.get("/api/system/roadmap/monthly-review", params={"limit": 10})
        assert list_resp.status_code == 200
        items = list_resp.json().get("items", [])
        assert len(items) >= 1
        assert items[0].get("go_no_go") in {"go", "no_go"}
    finally:
        for key, value in backup.items():
            store.set_setting(key, value)


def test_roadmap_end_to_end_no_go_when_capabilities_and_kpis_missing():
    client = _build_client()
    from core.data.base import Base, get_engine
    from core.data.models.system import SystemSetting  # noqa: F401
    from core.data.models.audit import AuditLogORM  # noqa: F401

    Base.metadata.create_all(get_engine())

    store = system_api.get_system_settings_store()
    keys = [
        "roadmap_kpis",
        "roadmap_kpis_meta",
        "roadmap_quality_metrics",
        "roadmap_quality_metrics_explicit_keys",
        "roadmap_monthly_reviews",
        "roadmapCapabilitiesJson",
    ]
    backup = {key: store.get_setting(key, None) for key in keys}

    try:
        # 设置严格 KPI 目标，确保当前低质量指标无法满足
        kpi_resp = client.post(
            "/api/system/roadmap/kpis",
            json={
                "availability_min": 0.999,
                "p99_latency_ms_max": 1000,
                "rag_top5_recall_min": 0.95,
                "answer_usefulness_min": 0.95,
                "unit_cost_reduction_min": 0.5,
                "observability_coverage_min": 1.0,
            },
        )
        assert kpi_resp.status_code == 200

        # 写入明显不达标的质量指标
        quality_resp = client.post(
            "/api/system/roadmap/quality-metrics",
            json={
                "rag_top5_recall": 0.5,
                "answer_usefulness": 0.5,
                "unit_cost_reduction": 0.0,
                "observability_coverage": 0.2,
                "critical_security_incidents": 2,
                "throughput_gain": 1.0,
                "multi_hop_accuracy_gain": 0.0,
                "hallucination_reduction": 0.0,
                "auto_scaling_trigger_success_rate": 0.0,
                "rollback_time_seconds": 1200,
            },
        )
        assert quality_resp.status_code == 200

        # 仅打开极少 capability，制造 phase gate 缺口
        cfg_resp = client.post(
            "/api/system/config",
            json={"roadmapCapabilitiesJson": '{"fine_grained_permissions":true}'},
        )
        assert cfg_resp.status_code == 200

        create_resp = client.post("/api/system/roadmap/monthly-review")
        assert create_resp.status_code == 200
        review = create_resp.json().get("review", {})
        assert review.get("go_no_go") == "no_go"
        assert review.get("north_star", {}).get("passed") is False
        assert review.get("phase_gate", {}).get("passed") is False
    finally:
        for key, value in backup.items():
            store.set_setting(key, value)


def test_roadmap_phase_status_response_contract():
    client = _build_client()

    resp = client.get("/api/system/roadmap/phases/status")
    assert resp.status_code == 200
    body = resp.json()

    # 顶层 contract
    assert set(body.keys()) >= {"snapshot", "north_star", "phase_gate", "go_no_go", "go_no_go_reasons", "top_blocker_capability"}
    assert isinstance(body["snapshot"], dict)
    assert isinstance(body["north_star"], dict)
    assert isinstance(body["phase_gate"], dict)
    assert body["go_no_go"] in {"go", "no_go"}
    assert isinstance(body["go_no_go_reasons"], list)
    assert body["top_blocker_capability"] is None or isinstance(body["top_blocker_capability"], str)
    for reason in body["go_no_go_reasons"]:
        assert isinstance(reason, dict)
        assert str(reason.get("type") or "") in {
            "summary",
            "capability_blocker",
            "anomaly_risk",
            "readiness_risk",
            "north_star",
        }

    # north_star contract
    north = body["north_star"]
    assert set(north.keys()) >= {"score", "passed", "reasons"}
    assert isinstance(north["score"], (int, float))
    assert isinstance(north["passed"], bool)
    assert isinstance(north["reasons"], list)

    # phase_gate contract
    gate = body["phase_gate"]
    assert set(gate.keys()) >= {
        "passed_count",
        "total_count",
        "score",
        "phases",
        "blocking_capabilities",
        "readiness_summary",
        "top_blocker_capability",
    }
    assert isinstance(gate["passed_count"], int)
    assert isinstance(gate["total_count"], int)
    assert isinstance(gate["score"], (int, float))
    assert isinstance(gate["phases"], dict)
    assert isinstance(gate["blocking_capabilities"], list)
    assert isinstance(gate["readiness_summary"], dict)
    assert gate["top_blocker_capability"] is None or isinstance(gate["top_blocker_capability"], str)

    # 每个 phase 的 contract
    for _, phase_info in gate["phases"].items():
        assert isinstance(phase_info, dict)
        assert set(phase_info.keys()) >= {"passed", "missing_capabilities", "missing_capability_details", "kpi_results"}
        assert isinstance(phase_info["passed"], bool)
        assert isinstance(phase_info["missing_capabilities"], list)
        assert isinstance(phase_info["missing_capability_details"], dict)
        assert isinstance(phase_info["kpi_results"], dict)
        assert isinstance(phase_info.get("readiness"), dict)
        assert set(phase_info.get("readiness", {}).keys()) >= {
            "score",
            "capability_readiness",
            "kpi_readiness",
            "capability_ready_count",
            "capability_total_count",
            "kpi_ready_count",
            "kpi_total_count",
        }


def test_roadmap_api_degrades_gracefully_when_settings_store_unavailable(monkeypatch):
    client = _build_client()

    class _BrokenStore:
        def get_setting(self, key, default=None):
            raise RuntimeError(f"store unavailable for key={key}")

        def set_setting(self, key, value):
            raise RuntimeError(f"store unavailable for key={key}")

    monkeypatch.setattr(system_api, "get_system_settings_store", lambda: _BrokenStore())

    # phases/status 应该仍可返回结构化结果（依赖默认值与运行时快照），不应 500
    status_resp = client.get("/api/system/roadmap/phases/status")
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert set(body.keys()) >= {"snapshot", "north_star", "phase_gate"}
    assert isinstance(body.get("north_star", {}).get("passed"), bool)

    # monthly-review 至少应保持 API 可用：成功返回 review，或返回结构化错误（不能崩溃）
    review_resp = client.post("/api/system/roadmap/monthly-review")
    assert review_resp.status_code in {200, 500, 503}
    payload = review_resp.json()
    if review_resp.status_code == 200:
        assert isinstance(payload.get("review"), dict)
        for reason in payload.get("review", {}).get("go_no_go_reasons", []) or []:
            assert isinstance(reason, dict)
            assert str(reason.get("type") or "") in {
                "summary",
                "capability_blocker",
                "anomaly_risk",
                "readiness_risk",
                "north_star",
            }
    else:
        assert isinstance(payload.get("error", {}), dict)


def test_roadmap_kpis_and_quality_metrics_response_contract():
    client = _build_client()

    kpis_resp = client.get("/api/system/roadmap/kpis")
    assert kpis_resp.status_code == 200
    kpis_body = kpis_resp.json()
    assert set(kpis_body.keys()) >= {"kpis"}
    assert isinstance(kpis_body["kpis"], dict)
    assert "availability_min" in kpis_body["kpis"]
    assert "p99_latency_ms_max" in kpis_body["kpis"]

    update_resp = client.post(
        "/api/system/roadmap/quality-metrics",
        json={"rag_top5_recall": 0.88, "answer_usefulness": 0.9},
    )
    assert update_resp.status_code == 200
    update_body = update_resp.json()
    assert set(update_body.keys()) >= {"success", "quality_metrics"}
    assert update_body["success"] is True
    assert isinstance(update_body["quality_metrics"], dict)
    assert isinstance(update_body["quality_metrics"].get("rag_top5_recall"), (int, float))

    get_qm = client.get("/api/system/roadmap/quality-metrics")
    assert get_qm.status_code == 200
    qm_body = get_qm.json()
    assert set(qm_body.keys()) >= {
        "quality_metrics",
        "explicit_metric_keys",
        "explicit_metric_keys_tracked",
        "phase3_kpi_inference_probe",
    }
    assert isinstance(qm_body["quality_metrics"], dict)
    assert qm_body["quality_metrics"].get("rag_top5_recall") == pytest.approx(0.88)
    assert isinstance(qm_body.get("explicit_metric_keys"), list)
    assert "rag_top5_recall" in (qm_body.get("explicit_metric_keys") or [])
    assert "answer_usefulness" in (qm_body.get("explicit_metric_keys") or [])
    assert qm_body.get("explicit_metric_keys_tracked") is True
    assert isinstance(qm_body.get("phase3_kpi_inference_probe"), dict)


def test_roadmap_monthly_review_list_limit_and_order():
    client = _build_client()
    from core.data.base import Base, get_engine
    from core.data.models.system import SystemSetting  # noqa: F401
    from core.data.models.audit import AuditLogORM  # noqa: F401

    Base.metadata.create_all(get_engine())
    store = system_api.get_system_settings_store()
    backup = store.get_setting("roadmap_monthly_reviews", None)
    try:
        # 连续写入两次，验证列表按最近优先返回
        r1 = client.post("/api/system/roadmap/monthly-review")
        r2 = client.post("/api/system/roadmap/monthly-review")
        assert r1.status_code == 200
        assert r2.status_code == 200

        list_resp = client.get("/api/system/roadmap/monthly-review", params={"limit": 1})
        assert list_resp.status_code == 200
        body = list_resp.json()
        assert body.get("count") == 1
        assert body.get("meta", {}).get("applied_filters", {}).get("limit") == 1
        assert body.get("meta", {}).get("applied_filters", {}).get("offset") == 0
        assert body.get("meta", {}).get("has_more") in {True, False}
        assert (
            body.get("meta", {}).get("next_offset") is None
            or isinstance(body.get("meta", {}).get("next_offset"), int)
        )
        assert (
            body.get("meta", {}).get("prev_offset") is None
            or isinstance(body.get("meta", {}).get("prev_offset"), int)
        )
        assert isinstance(body.get("meta", {}).get("page_window"), dict)
        assert body.get("meta", {}).get("returned_order") == "newest_first"
        items = body.get("items", [])
        assert isinstance(items, list)
        assert len(items) == 1
        assert isinstance(items[0], dict)
        assert "created_at" in items[0]
    finally:
        store.set_setting("roadmap_monthly_reviews", backup)


def test_roadmap_monthly_review_list_supports_top_blocker_filter(monkeypatch):
    client = _build_client()
    monkeypatch.setattr(
        system_api,
        "list_monthly_reviews_page",
        lambda limit=12, offset=0, top_blocker_capability=None, go_no_go=None, lowest_readiness_phase=None, readiness_below_threshold=None, max_lowest_readiness_score=None: (
            (
                [{"top_blocker_capability": "hybrid_retrieval"}, {"top_blocker_capability": "hybrid_retrieval"}]
                if top_blocker_capability == "hybrid_retrieval"
                else []
            )[offset : offset + limit],
            2 if top_blocker_capability == "hybrid_retrieval" else 0,
        ),
    )
    resp = client.get(
        "/api/system/roadmap/monthly-review",
        params={"top_blocker_capability": "hybrid_retrieval", "limit": 1},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["top_blocker_capability"] == "hybrid_retrieval"
    assert body["meta"]["applied_filters"]["top_blocker_capability"] == "hybrid_retrieval"
    assert body["meta"]["applied_filters"]["offset"] == 0
    assert body["meta"]["total_before_limit"] == 2
    assert body["meta"]["has_more"] is True
    assert body["meta"]["next_offset"] == 1
    assert body["meta"]["prev_offset"] is None
    assert body["meta"]["page_window"]["start"] == 0
    assert body["meta"]["page_window"]["end_exclusive"] == 1
    assert body["meta"]["returned_order"] == "newest_first"


def test_roadmap_monthly_review_list_supports_go_no_go_filter(monkeypatch):
    client = _build_client()
    monkeypatch.setattr(
        system_api,
        "list_monthly_reviews_page",
        lambda limit=12, offset=0, top_blocker_capability=None, go_no_go=None, lowest_readiness_phase=None, readiness_below_threshold=None, max_lowest_readiness_score=None: (
            (
                [
                    {"go_no_go": "no_go", "top_blocker_capability": "dynamic_batching"},
                    {"go_no_go": "no_go", "top_blocker_capability": "hybrid_retrieval"},
                ]
                if go_no_go == "no_go"
                else []
            )[offset : offset + limit],
            2 if go_no_go == "no_go" else 0,
        ),
    )
    resp = client.get("/api/system/roadmap/monthly-review", params={"go_no_go": "no_go", "limit": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["go_no_go"] == "no_go"
    assert body["meta"]["applied_filters"]["go_no_go"] == "no_go"
    assert body["meta"]["applied_filters"]["offset"] == 0
    assert body["meta"]["total_before_limit"] == 2
    assert body["meta"]["has_more"] is True
    assert body["meta"]["next_offset"] == 1
    assert body["meta"]["prev_offset"] is None
    assert body["meta"]["page_window"]["start"] == 0
    assert body["meta"]["page_window"]["end_exclusive"] == 1
    assert body["meta"]["returned_order"] == "newest_first"


def test_roadmap_monthly_review_list_supports_offset_param(monkeypatch):
    client = _build_client()
    monkeypatch.setattr(
        system_api,
        "list_monthly_reviews_page",
        lambda limit=12, offset=0, top_blocker_capability=None, go_no_go=None, lowest_readiness_phase=None, readiness_below_threshold=None, max_lowest_readiness_score=None: (
            [
                {"created_at": "2026-01-03T00:00:00Z"},
                {"created_at": "2026-01-02T00:00:00Z"},
                {"created_at": "2026-01-01T00:00:00Z"},
            ][offset : offset + limit],
            3,
        ),
    )
    resp = client.get("/api/system/roadmap/monthly-review", params={"limit": 1, "offset": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["created_at"] == "2026-01-02T00:00:00Z"
    assert body["meta"]["applied_filters"]["offset"] == 1
    assert body["meta"]["has_more"] is True
    assert body["meta"]["next_offset"] == 2
    assert body["meta"]["prev_offset"] == 0
    assert body["meta"]["page_window"]["start"] == 1
    assert body["meta"]["page_window"]["end_exclusive"] == 2
    assert body["meta"]["returned_order"] == "newest_first"


def test_roadmap_monthly_review_list_supports_combined_filters(monkeypatch):
    client = _build_client()
    monkeypatch.setattr(
        system_api,
        "list_monthly_reviews_page",
        lambda limit=12, offset=0, top_blocker_capability=None, go_no_go=None, lowest_readiness_phase=None, readiness_below_threshold=None, max_lowest_readiness_score=None: (
            (
                [{"go_no_go": "no_go", "top_blocker_capability": "hybrid_retrieval"}]
                if (top_blocker_capability == "hybrid_retrieval" and go_no_go == "no_go")
                else []
            )[offset : offset + limit],
            1 if (top_blocker_capability == "hybrid_retrieval" and go_no_go == "no_go") else 0,
        ),
    )
    resp = client.get(
        "/api/system/roadmap/monthly-review",
        params={"top_blocker_capability": "hybrid_retrieval", "go_no_go": "no_go", "limit": 5, "offset": 0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["go_no_go"] == "no_go"
    assert body["items"][0]["top_blocker_capability"] == "hybrid_retrieval"
    assert body["meta"]["applied_filters"]["top_blocker_capability"] == "hybrid_retrieval"
    assert body["meta"]["applied_filters"]["go_no_go"] == "no_go"
    assert body["meta"]["total_before_limit"] == 1
    assert body["meta"]["has_more"] is False
    assert body["meta"]["next_offset"] is None


def test_roadmap_monthly_review_list_empty_result_meta_contract(monkeypatch):
    client = _build_client()
    monkeypatch.setattr(
        system_api,
        "list_monthly_reviews_page",
        lambda limit=12, offset=0, top_blocker_capability=None, go_no_go=None, lowest_readiness_phase=None, readiness_below_threshold=None, max_lowest_readiness_score=None: ([], 0),
    )
    resp = client.get("/api/system/roadmap/monthly-review", params={"limit": 10, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["items"] == []
    assert body["meta"]["total_before_limit"] == 0
    assert body["meta"]["has_more"] is False
    assert body["meta"]["next_offset"] is None
    assert body["meta"]["prev_offset"] is None
    assert body["meta"]["page_window"]["start"] == 0
    assert body["meta"]["page_window"]["end_exclusive"] == 0


def test_roadmap_monthly_review_list_supports_readiness_filters(monkeypatch):
    client = _build_client()
    monkeypatch.setattr(
        system_api,
        "list_monthly_reviews_page",
        lambda limit=12, offset=0, top_blocker_capability=None, go_no_go=None, lowest_readiness_phase=None, readiness_below_threshold=None, max_lowest_readiness_score=None: (
            (
                [{"go_no_go": "no_go", "phase_gate": {"readiness_summary": {"lowest_phase": "phase2_advanced"}}}]
                if (lowest_readiness_phase == "phase2_advanced" and readiness_below_threshold is True)
                else []
            )[offset : offset + limit],
            1 if (lowest_readiness_phase == "phase2_advanced" and readiness_below_threshold is True) else 0,
        ),
    )
    resp = client.get(
        "/api/system/roadmap/monthly-review",
        params={"lowest_readiness_phase": "phase2_advanced", "readiness_below_threshold": "true", "limit": 5, "offset": 0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["meta"]["applied_filters"]["lowest_readiness_phase"] == "phase2_advanced"
    assert body["meta"]["applied_filters"]["readiness_below_threshold"] is True
    assert body["meta"]["total_before_limit"] == 1


def test_roadmap_monthly_review_list_supports_max_lowest_readiness_score(monkeypatch):
    client = _build_client()
    monkeypatch.setattr(
        system_api,
        "list_monthly_reviews_page",
        lambda limit=12, offset=0, top_blocker_capability=None, go_no_go=None, lowest_readiness_phase=None, readiness_below_threshold=None, max_lowest_readiness_score=None: (
            (
                [{"phase_gate": {"readiness_summary": {"lowest_score": 0.64}}}]
                if (
                    max_lowest_readiness_score is not None
                    and abs(float(max_lowest_readiness_score) - 0.65) < 1e-9
                )
                else []
            )[offset : offset + limit],
            1
            if (
                max_lowest_readiness_score is not None
                and abs(float(max_lowest_readiness_score) - 0.65) < 1e-9
            )
            else 0,
        ),
    )
    resp = client.get(
        "/api/system/roadmap/monthly-review",
        params={"max_lowest_readiness_score": "0.65", "limit": 5, "offset": 0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert abs(float(body["meta"]["applied_filters"]["max_lowest_readiness_score"]) - 0.65) < 1e-9
    assert body["meta"]["total_before_limit"] == 1
