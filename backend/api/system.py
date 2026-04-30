from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import StreamingResponse
import asyncio
import psutil  # type: ignore[import-untyped]
import time
import os
import json
import hashlib
import secrets
import aiofiles  # type: ignore[import-untyped]
from pathlib import Path
from log import logger, log_structured

import subprocess
from typing import Annotated, Any, Literal, Optional, Dict, AsyncIterator, cast, List
from pydantic import BaseModel, Field, ConfigDict

from api.errors import raise_api_error
from config.settings import settings
from core.system.settings_store import get_system_settings_store
from core.system.feature_flags import get_feature_flags, set_feature_flags
from core.system.queue_summary import build_unified_queue_summary
from core.system.storage_strategy import storage_readiness
from core.system.smart_routing_validation import validate_smart_routing_policies_json
from core.inference.gateway import get_inference_gateway
from core.cache import get_redis_cache_client
from core.security.deps import require_authenticated_platform_admin, require_platform_admin
from middleware.api_key_scope import get_revoked_api_keys, revoke_api_key, unrevoke_api_key
from core.system.runtime_settings import (
    get_continuous_batch_enabled,
    get_continuous_batch_max_size,
    get_inference_priority_panel_high_slo_critical_rate,
    get_inference_priority_panel_high_slo_warning_rate,
    get_inference_priority_panel_preemption_cooldown_busy_threshold,
    get_mcp_http_emit_server_push_events,
)
from core.system.roadmap import (
    build_blocking_capabilities,
    build_go_no_go_summary,
    build_phase_readiness_summary,
    build_roadmap_snapshot,
    create_monthly_review,
    get_phase_gates,
    get_roadmap_kpis,
    list_monthly_reviews_page,
    save_manual_quality_metrics,
    save_phase_gates,
    save_roadmap_kpis,
    evaluate_north_star,
    evaluate_phase_gates,
)
from core.plugins import get_plugin_manager
from core.plugins.market import PluginMarketValidationError, get_plugin_market_service
from core.plugins.compatibility import build_plugin_compatibility_matrix
from core.models.registry import get_model_registry
from core.agent_runtime.definition import get_agent_registry
from core.knowledge.knowledge_base_store import KnowledgeBaseStore
from core.data.base import SessionLocal
from core.idempotency.service import (
    IDEMPOTENCY_STATUS_FAILED,
    IDEMPOTENCY_STATUS_SUCCEEDED,
    IdempotencyService,
)
from core.events import (
    clear_event_bus_dlq,
    get_event_bus_dlq,
    get_event_bus_runtime_status,
    replay_event_bus_dlq,
)

router = APIRouter(
    prefix="/api/system",
    tags=["system"],
    dependencies=[Depends(require_authenticated_platform_admin)],
)
KERNEL_ADAPTER_NOT_INITIALIZED = "Kernel adapter not initialized"
_INFERENCE_CACHE_CLEAR_CHALLENGES: dict[str, tuple[str, float, Optional[str]]] = {}
_INFERENCE_CACHE_CLEAR_CHALLENGE_RATE: dict[str, list[float]] = {}
_INFERENCE_CACHE_CHALLENGE_METRICS: dict[str, int] = {
    "issued_total": 0,
    "validate_success_total": 0,
    "validate_failed_total": 0,
    "validate_failed_missing_total": 0,
    "validate_failed_actor_mismatch_total": 0,
    "validate_failed_code_mismatch_total": 0,
    "rate_limited_total": 0,
}

ALLOWED_SYSTEM_CONFIG_KEYS = {
    "offlineMode",
    "theme",
    "modelLoader",
    "contextWindow",
    "gpuLayers",
    "dataDirectory",
    "language",
    "yoloModelPath",
    "yoloDevice",
    "yoloDefaultBackend",
    "imageGenerationDefaultModelId",
    "asrModelId",
    "asrDevice",
    "autoUnloadLocalModelOnSwitch",
    "runtimeAutoReleaseEnabled",
    "runtimeMaxCachedLocalRuntimes",
    "runtimeMaxCachedLocalLlmRuntimes",
    "runtimeMaxCachedLocalVlmRuntimes",
    "runtimeMaxCachedLocalImageGenerationRuntimes",
    "runtimeReleaseIdleTtlSeconds",
    "runtimeReleaseMinIntervalSeconds",
    "inferenceSmartRoutingEnabled",
    "inferenceSmartRoutingPoliciesJson",
    "inferenceQueueSloEnabled",
    "inferenceQueueSloHighMs",
    "inferenceQueueSloMediumMs",
    "inferenceQueueSloLowMs",
    "inferenceQueuePreemptionEnabled",
    "inferenceQueuePreemptionMaxPerHighRequest",
    "inferenceQueuePreemptionMaxPerTask",
    "inferenceQueuePreemptionCooldownMs",
    "inferencePriorityPanelHighSloCriticalRate",
    "inferencePriorityPanelHighSloWarningRate",
    "inferencePriorityPanelPreemptionCooldownBusyThreshold",
    "continuousBatchEnabled",
    "continuousBatchWaitMs",
    "continuousBatchMaxSize",
    "skillDiscoveryTagMatchWeight",
    "skillDiscoveryMinSemanticSimilarity",
    "skillDiscoveryMinHybridScore",
    "agentPlanMaxParallelSteps",
    "agentStepDefaultTimeoutSeconds",
    "agentStepDefaultMaxRetries",
    "agentStepDefaultRetryIntervalSeconds",
    "workflowContractRequiredInputAddedBreaking",
    "workflowContractOutputAddedRisky",
    "workflowContractFieldExemptions",
    "workflowReflectorMaxRetries",
    "workflowReflectorRetryIntervalSeconds",
    "workflowReflectorFallbackAgentId",
    "workflowGovernanceHealthyThreshold",
    "workflowGovernanceWarningThreshold",
    "chaosFailRateWarn",
    "chaosP95WarnMs",
    "chaosNetErrWarn",
    "mcpHttpEmitServerPushEvents",
    "roadmapCapabilitiesJson",
}

SYSTEM_CONFIG_SCHEMA_HINTS: Dict[str, Dict[str, Any]] = {
    "workflowContractRequiredInputAddedBreaking": {
        "type": "boolean",
        "default": True,
        "recommended": True,
        "description": "新增 required 入参是否按 breaking 处理（建议生产开启）。",
    },
    "workflowContractOutputAddedRisky": {
        "type": "boolean",
        "default": True,
        "recommended": True,
        "description": "新增输出字段是否按 risky 处理（建议开启，便于风险提示）。",
    },
    "workflowContractFieldExemptions": {
        "type": "string",
        "default": "",
        "recommended": "",
        "description": "字段豁免列表，逗号分隔，格式 input.xxx 或 output.xxx。",
        "example": "input.age,output.debug",
    },
    "workflowReflectorMaxRetries": {
        "type": "integer",
        "default": 0,
        "recommended": 1,
        "description": "Reflector 全局默认重试次数（节点可覆盖）。",
    },
    "workflowReflectorRetryIntervalSeconds": {
        "type": "number",
        "default": 1.0,
        "recommended": 1.0,
        "description": "Reflector 全局默认重试间隔秒数（节点可覆盖）。",
    },
    "workflowReflectorFallbackAgentId": {
        "type": "string",
        "default": "",
        "recommended": "",
        "description": "Reflector 全局默认备用 Agent ID（节点可覆盖）。",
    },
    "workflowGovernanceHealthyThreshold": {
        "type": "number",
        "default": 0.1,
        "recommended": 0.1,
        "description": "治理成熟度 Healthy 阈值（覆盖比例）。",
    },
    "workflowGovernanceWarningThreshold": {
        "type": "number",
        "default": 0.3,
        "recommended": 0.3,
        "description": "治理成熟度 Warning 阈值（覆盖比例）。超过则为 Risky。",
    },
    "mcpHttpEmitServerPushEvents": {
        "type": "boolean",
        "default": True,
        "recommended": True,
        "description": "MCP Streamable HTTP：是否在 GET SSE 上收到服务端 JSON-RPC 时发布到事件总线（mcp.streamable.server_rpc，仅摘要）。",
    },
    "roadmapCapabilitiesJson": {
        "type": "string",
        "default": "{}",
        "recommended": "{}",
        "description": "路线图阶段能力开关（JSON 字符串），如 {\"hybrid_retrieval\": true}。",
    },
}

SYSTEM_CONFIG_EXAMPLE_PAYLOAD: Dict[str, Any] = {
    "workflowContractRequiredInputAddedBreaking": True,
    "workflowContractOutputAddedRisky": True,
    "workflowContractFieldExemptions": "input.age,output.debug",
    "workflowReflectorMaxRetries": 1,
    "workflowReflectorRetryIntervalSeconds": 1.0,
    "workflowReflectorFallbackAgentId": "agent.worker.backup",
    "workflowGovernanceHealthyThreshold": 0.1,
    "workflowGovernanceWarningThreshold": 0.3,
}


class SystemConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offlineMode: Optional[bool] = None
    theme: Optional[Literal["light", "dark"]] = None
    modelLoader: Optional[Literal["llama.cpp", "ollama"]] = None
    contextWindow: Optional[int] = Field(default=None, ge=256, le=262144)
    gpuLayers: Optional[int] = Field(default=None, ge=0, le=256)
    dataDirectory: Optional[str] = Field(default=None, min_length=1, max_length=4096)
    language: Optional[Literal["zh", "en"]] = None

    yoloModelPath: Optional[str] = Field(default=None, max_length=4096)
    yoloDevice: Optional[Literal["auto", "cpu", "cuda", "mps"]] = None
    yoloDefaultBackend: Optional[Literal["yolov8", "yolov11", "yolov26", "onnx"]] = None
    imageGenerationDefaultModelId: Optional[str] = Field(default=None, max_length=512)

    asrModelId: Optional[str] = Field(default=None, min_length=1, max_length=512)
    asrDevice: Optional[Literal["auto", "cpu", "cuda", "mps"]] = None

    autoUnloadLocalModelOnSwitch: Optional[bool] = None
    runtimeAutoReleaseEnabled: Optional[bool] = None
    runtimeMaxCachedLocalRuntimes: Optional[int] = Field(default=None, ge=1, le=16)
    runtimeMaxCachedLocalLlmRuntimes: Optional[int] = Field(default=None, ge=1, le=16)
    runtimeMaxCachedLocalVlmRuntimes: Optional[int] = Field(default=None, ge=1, le=16)
    runtimeMaxCachedLocalImageGenerationRuntimes: Optional[int] = Field(default=None, ge=1, le=16)
    runtimeReleaseIdleTtlSeconds: Optional[int] = Field(default=None, ge=30, le=86400)
    runtimeReleaseMinIntervalSeconds: Optional[int] = Field(default=None, ge=1, le=3600)
    inferenceSmartRoutingEnabled: Optional[bool] = None
    inferenceSmartRoutingPoliciesJson: Optional[str] = Field(default=None, max_length=65535)
    inferenceQueueSloEnabled: Optional[bool] = None
    inferenceQueueSloHighMs: Optional[int] = Field(default=None, ge=200, le=120000)
    inferenceQueueSloMediumMs: Optional[int] = Field(default=None, ge=200, le=120000)
    inferenceQueueSloLowMs: Optional[int] = Field(default=None, ge=200, le=120000)
    inferenceQueuePreemptionEnabled: Optional[bool] = None
    inferenceQueuePreemptionMaxPerHighRequest: Optional[int] = Field(default=None, ge=1, le=8)
    inferenceQueuePreemptionMaxPerTask: Optional[int] = Field(default=None, ge=1, le=20)
    inferenceQueuePreemptionCooldownMs: Optional[int] = Field(default=None, ge=0, le=60000)
    inferencePriorityPanelHighSloCriticalRate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    inferencePriorityPanelHighSloWarningRate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    inferencePriorityPanelPreemptionCooldownBusyThreshold: Optional[int] = Field(default=None, ge=0, le=100000)
    continuousBatchEnabled: Optional[bool] = None
    continuousBatchWaitMs: Optional[int] = Field(default=None, ge=0, le=500)
    continuousBatchMaxSize: Optional[int] = Field(default=None, ge=1, le=64)
    skillDiscoveryTagMatchWeight: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    skillDiscoveryMinSemanticSimilarity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    skillDiscoveryMinHybridScore: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    agentPlanMaxParallelSteps: Optional[int] = Field(default=None, ge=1, le=32)
    agentStepDefaultTimeoutSeconds: Optional[float] = Field(default=None, ge=0.0, le=3600.0)
    agentStepDefaultMaxRetries: Optional[int] = Field(default=None, ge=0, le=20)
    agentStepDefaultRetryIntervalSeconds: Optional[float] = Field(default=None, ge=0.0, le=60.0)
    workflowContractRequiredInputAddedBreaking: Optional[bool] = None
    workflowContractOutputAddedRisky: Optional[bool] = None
    workflowContractFieldExemptions: Optional[str] = Field(default=None, max_length=4096)
    workflowReflectorMaxRetries: Optional[int] = Field(default=None, ge=0, le=20)
    workflowReflectorRetryIntervalSeconds: Optional[float] = Field(default=None, ge=0.0, le=60.0)
    workflowReflectorFallbackAgentId: Optional[str] = Field(default=None, max_length=512)
    workflowGovernanceHealthyThreshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    workflowGovernanceWarningThreshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    chaosFailRateWarn: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    chaosP95WarnMs: Optional[int] = Field(default=None, ge=1, le=600000)
    chaosNetErrWarn: Optional[int] = Field(default=None, ge=0, le=10000)
    mcpHttpEmitServerPushEvents: Optional[bool] = None
    roadmapCapabilitiesJson: Optional[str] = Field(default=None, max_length=65535)


class RoadmapKpiUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    availability_min: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    p99_latency_ms_max: Optional[float] = Field(default=None, ge=0.0, le=300000.0)
    rag_top5_recall_min: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    answer_usefulness_min: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    unit_cost_reduction_min: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    critical_security_incidents_max: Optional[int] = Field(default=None, ge=0, le=1000)
    observability_coverage_min: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    online_error_rate_max: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class RoadmapQualityMetricsUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rag_top5_recall: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    answer_usefulness: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    unit_cost_reduction: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    observability_coverage: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    critical_security_incidents: Optional[int] = Field(default=None, ge=0, le=1000)
    throughput_gain: Optional[float] = Field(default=None, ge=0.0, le=1000.0)
    multi_hop_accuracy_gain: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    hallucination_reduction: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    auto_scaling_trigger_success_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    rollback_time_seconds: Optional[int] = Field(default=None, ge=0, le=86400)


class RoadmapGateUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase_gates: Dict[str, Dict[str, Any]]


class RoadmapMonthlyReviewListAppliedFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int
    offset: int
    top_blocker_capability: Optional[str] = None
    go_no_go: Optional[Literal["go", "no_go"]] = None
    lowest_readiness_phase: Optional[str] = None
    readiness_below_threshold: Optional[bool] = None


class RoadmapMonthlyReviewListMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applied_filters: RoadmapMonthlyReviewListAppliedFilters
    total_before_limit: int
    has_more: bool
    next_offset: Optional[int] = None
    prev_offset: Optional[int] = None
    returned_order: Literal["newest_first"] = "newest_first"
    page_window: Dict[str, int]


class RoadmapMonthlyReviewListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    items: List[Dict[str, Any]]
    meta: RoadmapMonthlyReviewListMeta


class RoadmapNorthStarStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float
    passed: bool
    reasons: List[str]


class RoadmapPhaseGateStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed_count: int
    total_count: int
    score: float
    phases: Dict[str, Dict[str, Any]]
    blocking_capabilities: List[Dict[str, Any]]
    readiness_summary: Dict[str, Any]
    top_blocker_capability: Optional[str] = None


class RoadmapPhaseStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: Dict[str, Any]
    north_star: RoadmapNorthStarStatus
    go_no_go: Literal["go", "no_go"]
    go_no_go_reasons: List[Dict[str, Any]]
    top_blocker_capability: Optional[str] = None
    phase_gate: RoadmapPhaseGateStatus


class ApiKeyRevokeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(..., min_length=1, max_length=512)


class ApiKeyRevocationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revoked_api_keys: list[str]


class InferenceCacheClearBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cache_kind: Literal["generate", "embedding"] = "generate"
    user_id: Optional[str] = Field(default=None, max_length=256)
    model_type: Optional[str] = Field(default=None, max_length=64)
    model_alias: Optional[str] = Field(default=None, max_length=256)
    resolved_model: Optional[str] = Field(default=None, max_length=256)
    force_all: bool = False
    confirm_text: Optional[str] = Field(default=None, max_length=32)
    challenge_id: Optional[str] = Field(default=None, max_length=64)


def _validate_system_config_payload(config_data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(config_data, dict):
        raise_api_error(
            status_code=400,
            code="system_config_invalid_type",
            message="config payload must be a JSON object",
        )

    unsupported = sorted(set(config_data.keys()) - ALLOWED_SYSTEM_CONFIG_KEYS)
    if unsupported:
        raise_api_error(
            status_code=400,
            code="system_config_unsupported_keys",
            message="unsupported system config keys",
            details={
                "unsupported_keys": unsupported,
                "allowed_keys": sorted(ALLOWED_SYSTEM_CONFIG_KEYS),
            },
        )

    try:
        validated = SystemConfigUpdate.model_validate(config_data)
    except Exception as e:
        if hasattr(e, "errors"):
            raise_api_error(
                status_code=400,
                code="system_config_validation_failed",
                message="invalid system config payload",
                details={"errors": e.errors()},
            )
        raise_api_error(status_code=400, code="system_config_invalid", message=str(e))

    normalized = cast(Dict[str, Any], validated.model_dump(exclude_none=True))
    _validate_governance_threshold_consistency(normalized)
    return normalized


def _validate_governance_threshold_consistency(config_data: Dict[str, Any]) -> None:
    healthy = config_data.get("workflowGovernanceHealthyThreshold")
    warning = config_data.get("workflowGovernanceWarningThreshold")
    if healthy is None or warning is None:
        return
    try:
        healthy_v = float(healthy)
        warning_v = float(warning)
    except (TypeError, ValueError):
        return
    if warning_v < healthy_v:
        raise_api_error(
            status_code=400,
            code="system_config_invalid_governance_thresholds",
            message="workflowGovernanceWarningThreshold must be greater than or equal to workflowGovernanceHealthyThreshold",
            details={
                "workflowGovernanceHealthyThreshold": healthy_v,
                "workflowGovernanceWarningThreshold": warning_v,
            },
        )

def _challenge_redis_key(challenge_id: str) -> str:
    return f"{settings.inference_cache_prefix}:challenge:{challenge_id}"


async def _issue_cache_clear_challenge(actor: Optional[str]) -> tuple[str, str]:
    challenge_id = secrets.token_hex(8)
    challenge_code = f"CLEAR-{secrets.token_hex(3).upper()}"
    ttl_seconds = max(30, int(getattr(settings, "inference_cache_clear_challenge_ttl_seconds", 120)))
    expires_at = time.time() + ttl_seconds
    _INFERENCE_CACHE_CLEAR_CHALLENGES[challenge_id] = (challenge_code, expires_at, actor)
    redis_cache = get_redis_cache_client()
    await redis_cache.set_json(
        _challenge_redis_key(challenge_id),
        {"code": challenge_code, "actor": actor or ""},
        ttl_seconds,
    )
    # Cleanup expired entries opportunistically.
    now = time.time()
    expired_ids = [cid for cid, (_, exp, _) in _INFERENCE_CACHE_CLEAR_CHALLENGES.items() if exp <= now]
    for cid in expired_ids:
        _INFERENCE_CACHE_CLEAR_CHALLENGES.pop(cid, None)
    return challenge_id, challenge_code


def _rate_limit_config() -> tuple[int, int]:
    window_seconds = max(10, int(getattr(settings, "inference_cache_clear_challenge_rate_window_seconds", 60)))
    max_per_window = max(1, int(getattr(settings, "inference_cache_clear_challenge_rate_max_per_window", 5)))
    return window_seconds, max_per_window


def _memory_rate_limit_fallback(actor: Optional[str], window_seconds: int, max_per_window: int) -> tuple[bool, int]:
    key = (actor or "anonymous").strip() or "anonymous"
    now = time.time()
    window_start = now - window_seconds
    hits = _INFERENCE_CACHE_CLEAR_CHALLENGE_RATE.get(key, [])
    hits = [t for t in hits if t >= window_start]
    if len(hits) >= max_per_window:
        _INFERENCE_CACHE_CLEAR_CHALLENGE_RATE[key] = hits
        retry_after = max(1, int(window_seconds - (now - hits[0])))
        _INFERENCE_CACHE_CHALLENGE_METRICS["rate_limited_total"] += 1
        return False, retry_after
    hits.append(now)
    _INFERENCE_CACHE_CLEAR_CHALLENGE_RATE[key] = hits
    return True, 0


async def _consume_cache_clear_challenge_rate(actor: Optional[str]) -> tuple[bool, int]:
    window_seconds, max_per_window = _rate_limit_config()
    actor_key = (actor or "anonymous").strip() or "anonymous"
    redis_key = f"{settings.inference_cache_prefix}:challenge_rate:{actor_key}"
    redis_cache = get_redis_cache_client()
    count = await redis_cache.incr_with_expire(redis_key, window_seconds)
    if count is not None:
        if count > max_per_window:
            ttl = await redis_cache.ttl(redis_key)
            retry_after = max(1, int(ttl if isinstance(ttl, int) and ttl > 0 else window_seconds))
            _INFERENCE_CACHE_CHALLENGE_METRICS["rate_limited_total"] += 1
            return False, retry_after
        return True, 0
    return _memory_rate_limit_fallback(actor, window_seconds, max_per_window)


async def _validate_cache_clear_challenge(
    challenge_id: Optional[str],
    confirm_text: Optional[str],
    actor: Optional[str],
) -> bool:
    cid = (challenge_id or "").strip()
    code = (confirm_text or "").strip()
    if not cid or not code:
        _INFERENCE_CACHE_CHALLENGE_METRICS["validate_failed_total"] += 1
        _INFERENCE_CACHE_CHALLENGE_METRICS["validate_failed_missing_total"] += 1
        return False

    redis_ok = await _validate_cache_clear_challenge_from_redis(cid, code, actor)
    if redis_ok is not None:
        if redis_ok:
            # Redis 与进程内表双写时须同步删除，避免二次校验仍命中内存中的挑战
            _INFERENCE_CACHE_CLEAR_CHALLENGES.pop(cid, None)
            _INFERENCE_CACHE_CHALLENGE_METRICS["validate_success_total"] += 1
        else:
            _INFERENCE_CACHE_CHALLENGE_METRICS["validate_failed_total"] += 1
        return redis_ok

    stored = _INFERENCE_CACHE_CLEAR_CHALLENGES.get(cid)
    if not stored:
        _INFERENCE_CACHE_CHALLENGE_METRICS["validate_failed_total"] += 1
        _INFERENCE_CACHE_CHALLENGE_METRICS["validate_failed_missing_total"] += 1
        return False
    expected, expires_at, stored_actor = stored
    if expires_at <= time.time():
        _INFERENCE_CACHE_CLEAR_CHALLENGES.pop(cid, None)
        _INFERENCE_CACHE_CHALLENGE_METRICS["validate_failed_total"] += 1
        _INFERENCE_CACHE_CHALLENGE_METRICS["validate_failed_missing_total"] += 1
        return False
    if (stored_actor or "") != (actor or ""):
        _INFERENCE_CACHE_CHALLENGE_METRICS["validate_failed_total"] += 1
        _INFERENCE_CACHE_CHALLENGE_METRICS["validate_failed_actor_mismatch_total"] += 1
        return False
    ok = code.upper() == expected.upper()
    if ok:
        _INFERENCE_CACHE_CLEAR_CHALLENGES.pop(cid, None)
        _INFERENCE_CACHE_CHALLENGE_METRICS["validate_success_total"] += 1
    else:
        _INFERENCE_CACHE_CHALLENGE_METRICS["validate_failed_total"] += 1
        _INFERENCE_CACHE_CHALLENGE_METRICS["validate_failed_code_mismatch_total"] += 1
    return ok


async def _validate_cache_clear_challenge_from_redis(
    challenge_id: str,
    confirm_text: str,
    actor: Optional[str],
) -> Optional[bool]:
    redis_cache = get_redis_cache_client()
    redis_payload = await redis_cache.get_json(_challenge_redis_key(challenge_id))
    if not isinstance(redis_payload, dict):
        return None
    expected = str(redis_payload.get("code") or "").strip()
    stored_actor = str(redis_payload.get("actor") or "")
    if expected and confirm_text.upper() == expected.upper() and (stored_actor or "") == (actor or ""):
        await redis_cache.delete(_challenge_redis_key(challenge_id))
        return True
    if (stored_actor or "") != (actor or ""):
        _INFERENCE_CACHE_CHALLENGE_METRICS["validate_failed_actor_mismatch_total"] += 1
    else:
        _INFERENCE_CACHE_CHALLENGE_METRICS["validate_failed_code_mismatch_total"] += 1
    return False

@router.get("/config")
async def get_config() -> Dict[str, Any]:
    """获取系统配置"""
    store = get_system_settings_store()
    db_settings = store.get_all_settings()
    
    # 优先从数据库读取用户设置的目录，否则使用配置文件默认值
    local_model_dir = db_settings.get("dataDirectory") or settings.local_model_directory
    
    return {
        "ollama_base_url": settings.ollama_base_url,
        "localai_base_url": settings.localai_base_url,
        "textgen_webui_base_url": settings.textgen_webui_base_url,
        "app_name": settings.app_name,
        "version": settings.version,
        "local_model_directory": local_model_dir,
        "settings": db_settings,
        # MCP Streamable HTTP：合并 SystemSetting 与 .env 后的生效值（供控制台与其它客户端展示）
        "mcp_http_emit_server_push_events_effective": get_mcp_http_emit_server_push_events(),
    }

@router.post("/config")
async def update_config(
    config_data: Dict[str, Any],
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    """更新系统配置"""
    config_data = _validate_system_config_payload(config_data)
    if "inferenceSmartRoutingPoliciesJson" in config_data:
        validate_smart_routing_policies_json(str(config_data.get("inferenceSmartRoutingPoliciesJson") or ""))
    store = get_system_settings_store()
    for key, value in config_data.items():
        store.set_setting(key, value)
    return {"success": True}


@router.get("/config/schema")
async def get_config_schema(
    keys: Annotated[Optional[str], Query(description="逗号分隔，仅返回指定配置键 schema")] = None,
    keys_list: Annotated[Optional[List[str]], Query(alias="keys", description="可重复 keys 参数")] = None,
    include_examples: Annotated[bool, Query(description="是否包含示例 payload")] = True,
    compact: Annotated[bool, Query(description="紧凑模式，仅保留关键 schema 字段")] = False,
) -> Dict[str, Any]:
    """
    返回系统配置字段定义与示例，供前端配置页动态渲染使用。
    """
    requested_keys: set[str] = set()
    for raw in [keys or "", *(keys_list or [])]:
        for k in str(raw or "").split(","):
            kk = k.strip()
            if kk:
                requested_keys.add(kk)
    if requested_keys:
        schema_hints = {
            key: value
            for key, value in SYSTEM_CONFIG_SCHEMA_HINTS.items()
            if key in requested_keys
        }
        allowed_keys = sorted(set(ALLOWED_SYSTEM_CONFIG_KEYS) & requested_keys)
    else:
        schema_hints = SYSTEM_CONFIG_SCHEMA_HINTS
        allowed_keys = sorted(ALLOWED_SYSTEM_CONFIG_KEYS)
    if compact:
        schema_hints = _compact_schema_hints(schema_hints)
    response: Dict[str, Any] = {
        "allowed_keys": allowed_keys,
        "schema_hints": schema_hints,
        "query_examples": {
            "all": "/api/system/config/schema",
            "compact_no_examples": "/api/system/config/schema?compact=true&include_examples=false",
            "filtered_keys_csv": (
                "/api/system/config/schema?"
                "keys=workflowContractRequiredInputAddedBreaking,workflowContractFieldExemptions"
            ),
            "filtered_keys_repeated": (
                "/api/system/config/schema?"
                "keys=workflowContractRequiredInputAddedBreaking&keys=workflowContractFieldExemptions"
            ),
            "combined": (
                "/api/system/config/schema?"
                "keys=workflowContractOutputAddedRisky&compact=true&include_examples=false"
            ),
        },
    }
    if include_examples:
        response["examples"] = {
            "workflow_contract_policy": SYSTEM_CONFIG_EXAMPLE_PAYLOAD,
        }
    return response


def _compact_schema_hints(schema_hints: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    keep_fields = {"type", "default", "recommended"}
    compacted: Dict[str, Dict[str, Any]] = {}
    for key, hint in (schema_hints or {}).items():
        if not isinstance(hint, dict):
            continue
        compacted[key] = {k: v for k, v in hint.items() if k in keep_fields}
    return compacted


class PluginRegisterBody(BaseModel):
    manifest_path: str = Field(..., min_length=1, max_length=4096)
    set_default: bool = True


class PluginUnregisterBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    version: Optional[str] = Field(default=None, max_length=128)


class PluginReloadBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    version: Optional[str] = Field(default=None, max_length=128)


class PluginSetDefaultBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    version: str = Field(..., min_length=1, max_length=128)


class PluginMarketPublishBody(BaseModel):
    manifest_path: str = Field(..., min_length=1, max_length=4096)
    package_path: Optional[str] = Field(default=None, max_length=4096)
    author: Optional[str] = Field(default=None, max_length=256)
    signature: Optional[str] = Field(default=None, max_length=4096)
    source: Literal["third_party", "builtin", "enterprise"] = "third_party"


class PluginMarketReviewBody(BaseModel):
    package_id: str = Field(..., min_length=3, max_length=256)
    approve: bool = True
    visibility: Literal["public", "private"] = "public"


class PluginMarketInstallBody(BaseModel):
    package_id: str = Field(..., min_length=3, max_length=256)


class PluginMarketToggleBody(BaseModel):
    package_id: str = Field(..., min_length=3, max_length=256)
    enabled: bool = True


class EventBusDlqClearBody(BaseModel):
    confirm: bool = Field(default=False, description="必须为 true 才会执行清理")


class EventBusDlqReplayBody(BaseModel):
    event_type: Optional[str] = Field(default=None, max_length=128)
    since_ts: Optional[int] = Field(default=None, ge=0)
    limit: int = Field(default=20, ge=1, le=200)
    dry_run: bool = Field(default=False, description="仅预览将重放的条目，不实际投递")
    confirm: bool = Field(default=False, description="必须为 true 才会执行重放")


def _extract_idempotency_key(request: Request) -> Optional[str]:
    return (
        request.headers.get("Idempotency-Key")
        or request.headers.get("X-Idempotency-Key")
        or request.headers.get("X-Request-Id")
    )


def _stable_request_hash(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _run_replay_with_rate_limit(body: "EventBusDlqReplayBody") -> Dict[str, Any]:
    try:
        return await replay_event_bus_dlq(
            event_type=body.event_type,
            since_ts=body.since_ts,
            limit=body.limit,
            dry_run=body.dry_run,
        )
    except RuntimeError as e:
        raise_api_error(
            status_code=429,
            code="event_bus_dlq_replay_rate_limited",
            message=str(e),
        )
        raise AssertionError("unreachable")


def _raise_idempotency_in_progress() -> None:
    raise_api_error(
        status_code=409,
        code="idempotency_in_progress",
        message="Idempotent replay request is still processing; retry later",
        details={"scope": "event_bus_dlq_replay"},
    )


async def _run_replay_with_optional_idempotency(body: "EventBusDlqReplayBody", request: Request) -> Dict[str, Any]:
    idem_key = _extract_idempotency_key(request)
    if not idem_key:
        return await _run_replay_with_rate_limit(body)

    owner_id = str(getattr(request.state, "user_id", None) or "platform_admin")
    idem_db = SessionLocal()
    idem_service = IdempotencyService(idem_db)
    req_hash = _stable_request_hash(
        {
            "event_type": body.event_type,
            "since_ts": body.since_ts,
            "limit": body.limit,
            "dry_run": body.dry_run,
            "confirm": body.confirm,
        }
    )
    claim = idem_service.claim(
        scope="event_bus_dlq_replay",
        owner_id=owner_id,
        key=idem_key,
        request_hash=req_hash,
        ttl_seconds=3600,
    )
    if claim.conflict:
        idem_db.close()
        raise_api_error(
            status_code=409,
            code="idempotency_conflict",
            message="Idempotency-Key already used with different request payload",
            details={"scope": "event_bus_dlq_replay"},
        )
    if not claim.is_new:
        cached = _resolve_cached_replay_response(claim.record.status, claim.record.error_message)
        idem_db.close()
        if cached is not None:
            return cached
        _raise_idempotency_in_progress()

    try:
        result = await _run_replay_with_rate_limit(body)
        claim.record.status = IDEMPOTENCY_STATUS_SUCCEEDED
        claim.record.response_ref = "inline_json"
        claim.record.error_message = json.dumps(result, ensure_ascii=False)[:2000]
        idem_db.commit()
    except Exception as e:
        claim.record.status = IDEMPOTENCY_STATUS_FAILED
        claim.record.error_message = str(e)[:2000]
        idem_db.commit()
        idem_db.close()
        raise
    idem_db.close()
    return result


def _resolve_cached_replay_response(status: str, error_message: Optional[str]) -> Optional[Dict[str, Any]]:
    if status == IDEMPOTENCY_STATUS_SUCCEEDED and error_message:
        try:
            return json.loads(error_message)
        except Exception:
            return None
    if status == IDEMPOTENCY_STATUS_FAILED and error_message:
        raise_api_error(
            status_code=409,
            code="idempotency_previous_failed",
            message="Previous idempotent replay request failed",
            details={"scope": "event_bus_dlq_replay", "reason": error_message},
        )
    return None


def _plugin_init_context() -> tuple[Any, Any]:
    model_registry = get_model_registry()
    memory = None
    try:
        from api.chat import memory_store  # lazy import to avoid bootstrap cycle

        memory = memory_store
    except Exception:
        memory = None
    return model_registry, memory


@router.get("/plugins")
async def list_plugins(*, _role: Annotated[Any, Depends(require_platform_admin)]) -> Dict[str, Any]:
    manager = get_plugin_manager()
    plugins = manager.list_plugins()
    return {"count": len(plugins), "plugins": plugins}


@router.post("/plugins/register")
async def register_plugin(
    body: PluginRegisterBody,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    manager = get_plugin_manager()
    model_registry, memory = _plugin_init_context()
    ok = await manager.register_from_manifest(
        body.manifest_path,
        logger=logger,
        memory=memory,
        model_registry=model_registry,
        set_default=body.set_default,
    )
    if not ok:
        raise_api_error(
            status_code=400,
            code="plugin_register_failed",
            message="Plugin register failed",
            details={"manifest_path": body.manifest_path},
        )
    return {"success": True}


@router.post("/plugins/unregister")
async def unregister_plugin(
    body: PluginUnregisterBody,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    manager = get_plugin_manager()
    ok = await manager.unregister(body.name, body.version)
    if not ok:
        raise_api_error(
            status_code=404,
            code="plugin_not_found",
            message="Plugin not found",
            details={"name": body.name, "version": body.version},
        )
    return {"success": True}


@router.post("/plugins/reload")
async def reload_plugin(
    body: PluginReloadBody,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    manager = get_plugin_manager()
    model_registry, memory = _plugin_init_context()
    ok = await manager.reload(
        body.name,
        body.version,
        logger=logger,
        memory=memory,
        model_registry=model_registry,
    )
    if not ok:
        raise_api_error(
            status_code=404,
            code="plugin_reload_failed",
            message="Plugin reload failed",
            details={"name": body.name, "version": body.version},
        )
    return {"success": True}


@router.post("/plugins/default")
async def set_default_plugin_version(
    body: PluginSetDefaultBody,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    manager = get_plugin_manager()
    manager.set_default_version(body.name, body.version)
    return {"success": True}


@router.get("/plugins/market")
async def list_plugin_market_packages(
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
    review_status: Annotated[Optional[str], Query(max_length=32)] = None,
) -> Dict[str, Any]:
    service = get_plugin_market_service()
    items = service.list_packages(review_status=review_status)
    return {"count": len(items), "items": items}


@router.post("/plugins/market/publish")
async def publish_plugin_market_package(
    body: PluginMarketPublishBody,
    request: Request,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    service = get_plugin_market_service()
    try:
        result = service.publish(
            manifest_path=body.manifest_path,
            package_path=body.package_path,
            author=body.author or getattr(request.state, "user_id", None),
            signature=body.signature,
            source=body.source,
        )
    except PluginMarketValidationError as e:
        raise_api_error(status_code=400, code="plugin_market_publish_invalid", message=str(e))
    return {"success": True, **result}


@router.post("/plugins/market/review")
async def review_plugin_market_package(
    body: PluginMarketReviewBody,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    service = get_plugin_market_service()
    ok = service.review(package_id=body.package_id, approve=body.approve, visibility=body.visibility)
    if not ok:
        raise_api_error(
            status_code=404,
            code="plugin_market_package_not_found",
            message="Plugin package not found",
            details={"package_id": body.package_id},
        )
    return {"success": True, "package_id": body.package_id, "approved": body.approve}


@router.post("/plugins/market/install")
async def install_plugin_market_package(
    body: PluginMarketInstallBody,
    request: Request,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    service = get_plugin_market_service()
    model_registry, memory = _plugin_init_context()
    try:
        result = await service.install(
            body.package_id,
            logger=logger,
            memory=memory,
            model_registry=model_registry,
            installed_by=getattr(request.state, "user_id", None),
        )
    except PluginMarketValidationError as e:
        raise_api_error(status_code=400, code="plugin_market_install_failed", message=str(e))
    return {"success": True, **result}


@router.get("/plugins/market/installations")
async def list_plugin_market_installations(*, _role: Annotated[Any, Depends(require_platform_admin)]) -> Dict[str, Any]:
    service = get_plugin_market_service()
    items = service.list_installations()
    return {"count": len(items), "items": items}


@router.post("/plugins/market/toggle")
async def toggle_plugin_market_installation(
    body: PluginMarketToggleBody,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    service = get_plugin_market_service()
    model_registry, memory = _plugin_init_context()
    ok = await service.set_enabled(
        body.package_id,
        body.enabled,
        logger=logger,
        memory=memory,
        model_registry=model_registry,
    )
    if not ok:
        raise_api_error(
            status_code=404,
            code="plugin_market_installation_not_found",
            message="Plugin installation not found",
            details={"package_id": body.package_id},
        )
    return {"success": True, "package_id": body.package_id, "enabled": body.enabled}


@router.get("/plugins/compatibility/matrix")
async def get_plugin_compatibility_matrix(*, _role: Annotated[Any, Depends(require_platform_admin)]) -> Dict[str, Any]:
    return build_plugin_compatibility_matrix()


@router.get("/event-bus/status")
async def event_bus_status(*, _role: Annotated[Any, Depends(require_platform_admin)]) -> Dict[str, Any]:
    return await get_event_bus_runtime_status()


@router.get("/event-bus/dlq")
async def event_bus_dlq(
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    event_type: Annotated[Optional[str], Query(max_length=128)] = None,
    since_ts: Annotated[Optional[int], Query(ge=0)] = None,
) -> Dict[str, Any]:
    items = await get_event_bus_dlq(limit=limit, event_type=event_type, since_ts=since_ts)
    return {"count": len(items), "items": items}


@router.post("/event-bus/dlq/clear")
async def event_bus_dlq_clear(
    body: EventBusDlqClearBody,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    if not body.confirm:
        raise_api_error(
            status_code=400,
            code="event_bus_dlq_clear_confirmation_required",
            message="confirm=true is required to clear event bus DLQ.",
        )
    cleared = await clear_event_bus_dlq()
    return {"success": True, "cleared": cleared}


@router.post("/event-bus/dlq/replay")
async def event_bus_dlq_replay(
    body: EventBusDlqReplayBody,
    request: Request,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    if not body.confirm:
        raise_api_error(
            status_code=400,
            code="event_bus_dlq_replay_confirmation_required",
            message="confirm=true is required to replay event bus DLQ.",
        )
    result = await _run_replay_with_optional_idempotency(body, request)
    return {"success": True, **result}

@router.post("/engine/reload")
async def reload_engine(*, _role: Annotated[Any, Depends(require_platform_admin)]) -> Dict[str, Any]:
    """重载推理引擎"""
    logger.info("[System] Reloading inference engine...")
    # 这里可以添加实际的重载逻辑，比如重启 Ollama 服务或重置 llama.cpp 实例
    await asyncio.sleep(1.5)
    return {"success": True}


@router.get("/security/api-keys/revoked")
async def list_revoked_api_keys(
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> ApiKeyRevocationListResponse:
    return ApiKeyRevocationListResponse(revoked_api_keys=get_revoked_api_keys())


@router.post("/security/api-keys/revoke")
async def revoke_api_key_endpoint(
    body: ApiKeyRevokeBody,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> ApiKeyRevocationListResponse:
    return ApiKeyRevocationListResponse(revoked_api_keys=revoke_api_key(body.api_key))


@router.post("/security/api-keys/unrevoke")
async def unrevoke_api_key_endpoint(
    body: ApiKeyRevokeBody,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> ApiKeyRevocationListResponse:
    return ApiKeyRevocationListResponse(revoked_api_keys=unrevoke_api_key(body.api_key))


@router.get("/inference/cache/stats")
async def get_inference_cache_stats(
    request: Request,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    gateway = get_inference_gateway()
    stats = gateway.get_cache_stats()
    stats = {
        **stats,
        "challenge_metrics": dict(_INFERENCE_CACHE_CHALLENGE_METRICS),
    }
    actor = getattr(request.state, "user_id", None)
    log_structured(
        "System",
        "inference_cache_stats_read",
        actor=actor,
        cache_hits=stats.get("cache_hits"),
        cache_misses=stats.get("cache_misses"),
        cache_hit_rate=stats.get("cache_hit_rate"),
    )
    return stats


@router.post("/inference/cache/clear/challenge")
async def create_inference_cache_clear_challenge(
    request: Request,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    actor = getattr(request.state, "user_id", None)
    allowed, retry_after = await _consume_cache_clear_challenge_rate(actor)
    if not allowed:
        raise_api_error(
            status_code=429,
            code="inference_cache_clear_challenge_rate_limited",
            message="Too many challenge requests. Please retry later.",
            details={"retry_after_seconds": retry_after},
        )
    challenge_id, challenge_code = await _issue_cache_clear_challenge(actor)
    _INFERENCE_CACHE_CHALLENGE_METRICS["issued_total"] += 1
    log_structured("System", "inference_cache_clear_challenge_issued", actor=actor, challenge_id=challenge_id)
    ttl_seconds = max(30, int(getattr(settings, "inference_cache_clear_challenge_ttl_seconds", 120)))
    return {
        "challenge_id": challenge_id,
        "challenge_code": challenge_code,
        "expires_in_seconds": ttl_seconds,
    }


@router.post("/inference/cache/clear")
async def clear_inference_cache(
    body: InferenceCacheClearBody,
    request: Request,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    actor = getattr(request.state, "user_id", None)
    has_scope = bool(
        (body.user_id and body.user_id.strip())
        or (body.model_type and body.model_type.strip())
        or (body.model_alias and body.model_alias.strip())
        or (body.resolved_model and body.resolved_model.strip())
    )
    if not has_scope and not body.force_all:
        raise_api_error(
            status_code=400,
            code="inference_cache_clear_scope_required",
            message="At least one filter is required, or set force_all=true to clear all cache.",
        )
    if body.force_all:
        if not await _validate_cache_clear_challenge(body.challenge_id, body.confirm_text, actor):
            raise_api_error(
                status_code=400,
                code="inference_cache_clear_confirmation_required",
                message="force_all=true requires a valid challenge_id and matching confirm_text.",
            )
    gateway = get_inference_gateway()
    result = await gateway.clear_cache(
        cache_kind=body.cache_kind,
        user_id=(body.user_id or None),
        model_type=(body.model_type or None),
        model_alias=(body.model_alias or None),
        resolved_model=(body.resolved_model or None),
    )
    log_structured(
        "System",
        "inference_cache_cleared",
        actor=actor,
        cache_kind=body.cache_kind,
        user_id=body.user_id,
        model_type=body.model_type,
        model_alias=body.model_alias,
        resolved_model=result.get("resolved_model"),
        total_deleted=result.get("total_deleted"),
    )
    return {"success": True, **result}

@router.get("/browse-directory")
async def browse_directory() -> Dict[str, Optional[str]]:
    """打开本地目录选择器 (目前仅支持 MacOS)"""
    import platform
    import subprocess
    
    system = platform.system()
    try:
        if system == "Darwin":
            # MacOS osascript to pick a folder and return POSIX path
            cmd = 'osascript -e "POSIX path of (choose folder with prompt \\"Select Local Model Directory:\\")"'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                return {"path": stdout.decode().strip()}
        elif system == "Windows":
            # Windows powershell snippet for folder picker
            cmd = 'powershell.exe -NoProfile -Command "& { $app = New-Object -ComObject Shell.Application; $folder = $app.BrowseForFolder(0, \'Select Local Model Directory\', 0); if ($folder) { $folder.Self.Path } }"'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                return {"path": stdout.decode().strip()}
    except Exception as e:
        logger.error(f"[System] Browse directory failed: {e}")
        
    return {"path": None}

# 获取启动时间
BOOT_TIME = time.time()

def get_node_version() -> str:
    """获取 Node.js 版本"""
    try:
        result = subprocess.run(["node", "-v"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "N/A"

def get_gpu_metrics() -> Dict[str, Any]:
    """获取真实的 GPU 指标"""
    gpu_metrics = {
        "gpu_usage": 0,
        "vram_used": 0,
        "vram_total": 0,
        "cuda_version": "N/A"
    }
    
    # 1. 尝试 NVIDIA GPU (pynvml)
    try:
        import pynvml  # type: ignore[import-not-found]
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        if device_count > 0:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0) # 默认取第一个 GPU
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            cuda_ver = pynvml.nvmlSystemGetCudaDriverVersion()
            
            gpu_metrics["gpu_usage"] = util.gpu
            gpu_metrics["vram_used"] = round(info.used / (1024**3), 1)
            gpu_metrics["vram_total"] = round(info.total / (1024**3), 1)
            gpu_metrics["cuda_version"] = f"{cuda_ver // 1000}.{(cuda_ver % 1000) // 10}"
            pynvml.nvmlShutdown()
            return gpu_metrics
    except Exception:
        pass

    # 2. 尝试 MacOS Apple Silicon (MPS / Unified Memory)
    if os.uname().sysname == 'Darwin':
        try:
            # 对于 Mac，VRAM 即统一内存
            mem = psutil.virtual_memory()
            gpu_metrics["vram_total"] = round(mem.total / (1024**3), 1)
            # 估算 GPU 占用的内存 (Mac 没有直接 API 拿 GPU 瞬时占用，通常取当前活跃内存的一个比例)
            gpu_metrics["vram_used"] = round(mem.used / (1024**3), 1)
            gpu_metrics["cuda_version"] = "MPS (Metal)"
            
            # 获取 GPU 使用率 (通过 ioreg 尝试，可能较慢)
            cmd = "ioreg -l | grep \"PerformanceStatistics\" | grep \"Device Utilization\" | head -n 1"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=1)
            if res.stdout:
                # 解析示例: "Device Utilization %"=15
                import re
                match = re.search(r"\"Device Utilization %\"=(\d+)", res.stdout)
                if match:
                    gpu_metrics["gpu_usage"] = int(match.group(1))
            return gpu_metrics
        except Exception:
            pass

    return gpu_metrics

@router.get("/runtime-metrics")
async def get_runtime_metrics_api() -> Dict[str, Any]:
    """V2.9 运行时稳定层指标：按模型的请求数、延迟、队列、tokens"""
    from core.runtime import get_runtime_metrics, get_inference_queue_manager

    metrics = cast(Dict[str, Any], get_runtime_metrics().get_metrics())
    priority_summary = cast(Dict[str, Any], metrics.get("by_priority_summary") or {})
    high_priority = cast(Dict[str, Any], priority_summary.get("high") or {})
    queue_manager = get_inference_queue_manager()
    queue_preemption_summary = {
        "preemptions_total": 0,
        "preemption_skipped_limit_total": 0,
        "preemption_skipped_cooldown_total": 0,
        "by_model": {},
    }
    for model_id, queue in queue_manager.list_queues().items():
        model_stats = {
            "preemptions_total": int(getattr(queue, "preemptions_total", 0)),
            "preemption_skipped_limit_total": int(getattr(queue, "preemption_skipped_limit_total", 0)),
            "preemption_skipped_cooldown_total": int(getattr(queue, "preemption_skipped_cooldown_total", 0)),
        }
        queue_preemption_summary["by_model"][model_id] = model_stats
        queue_preemption_summary["preemptions_total"] += model_stats["preemptions_total"]
        queue_preemption_summary["preemption_skipped_limit_total"] += model_stats["preemption_skipped_limit_total"]
        queue_preemption_summary["preemption_skipped_cooldown_total"] += model_stats["preemption_skipped_cooldown_total"]

    metrics["priority_slo_panel"] = {
        "high_priority": {
            "requests": int(high_priority.get("requests") or 0),
            "p95_latency_ms": float(high_priority.get("p95_latency_ms") or 0.0),
            "slo_target_ms": int(high_priority.get("slo_target_ms") or 0),
            "slo_met_rate": float(high_priority.get("slo_met_rate") or 0.0),
        },
        "queue_preemption": queue_preemption_summary,
        "thresholds": {
            "high_slo_critical_rate": float(get_inference_priority_panel_high_slo_critical_rate()),
            "high_slo_warning_rate": float(get_inference_priority_panel_high_slo_warning_rate()),
            "preemption_cooldown_busy_threshold": int(
                get_inference_priority_panel_preemption_cooldown_busy_threshold()
            ),
        },
    }
    return metrics


@router.get("/observability-summary")
async def observability_summary() -> Dict[str, Any]:
    """聚合观测摘要（用于生产巡检看板）。"""
    from core.runtime import get_runtime_metrics

    metrics = get_runtime_metrics().get_metrics()
    summary = metrics.get("summary", {})
    total_requests = int(summary.get("total_requests", 0) or 0)
    total_failed = int(summary.get("total_requests_failed", 0) or 0)
    failure_rate = (total_failed / total_requests) if total_requests else 0.0
    return {
        "requests": total_requests,
        "failed_requests": total_failed,
        "failure_rate": round(failure_rate, 4),
        "models_count": int(summary.get("models_count", 0) or 0),
        "total_latency_ms": float(summary.get("total_latency_ms", 0.0) or 0.0),
    }


@router.get("/storage-readiness")
async def storage_readiness_api() -> Dict[str, Any]:
    return cast(Dict[str, Any], storage_readiness(getattr(settings, "db_path", "")))


@router.get("/queue-summary")
async def queue_summary_api() -> Dict[str, Any]:
    """统一任务负载摘要（workflow + image + runtime）。"""
    workflow_running = 0
    image_pending = 0
    image_running = 0
    runtime_models = 0
    try:
        from core.data.base import db_session
        from core.data.models.workflow import WorkflowExecutionORM
        from core.data.models.image_generation import ImageGenerationJobORM
        from sqlalchemy import func

        with db_session() as db:
            workflow_running = int(
                db.query(func.count())
                .select_from(WorkflowExecutionORM)
                .filter(WorkflowExecutionORM.state == "running")
                .scalar()
                or 0
            )
            image_pending = int(
                db.query(func.count())
                .select_from(ImageGenerationJobORM)
                .filter(ImageGenerationJobORM.status == "queued")
                .scalar()
                or 0
            )
            image_running = int(
                db.query(func.count())
                .select_from(ImageGenerationJobORM)
                .filter(ImageGenerationJobORM.status == "running")
                .scalar()
                or 0
            )
    except Exception:
        pass
    try:
        from core.runtime.manager import get_model_instance_manager

        runtime_models = len(get_model_instance_manager().list_instances())
    except Exception:
        runtime_models = 0

    return cast(
        Dict[str, Any],
        build_unified_queue_summary(workflow_running, image_pending, image_running, runtime_models),
    )


@router.get("/feature-flags")
async def get_feature_flags_api(request: Request) -> Dict[str, Any]:
    tenant_id = getattr(request.state, "tenant_id", None)
    return {"tenant_id": tenant_id, "flags": get_feature_flags(tenant_id)}


@router.post("/feature-flags")
async def update_feature_flags_api(
    payload: Dict[str, Any],
    request: Request,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    flags = payload.get("flags", payload)
    if not isinstance(flags, dict):
        raise_api_error(
            status_code=400,
            code="system_feature_flags_invalid",
            message="flags must be object",
        )
    tenant_id = getattr(request.state, "tenant_id", None)
    saved = set_feature_flags(flags, tenant_id=tenant_id)
    return {"success": True, "tenant_id": tenant_id, "flags": saved}


_RAG_PLUGIN_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "core" / "plugins" / "builtin" / "rag" / "plugin.json"


def _read_manual_roadmap_capabilities() -> Dict[str, bool]:
    try:
        store = get_system_settings_store()
        raw = store.get_setting("roadmapCapabilitiesJson", "{}")
    except Exception:
        return {}
    if isinstance(raw, dict):
        return {str(k): bool(v) for k, v in raw.items()}
    if not isinstance(raw, str):
        return {}
    text = raw.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return {str(k): bool(v) for k, v in parsed.items()}
    except Exception:
        return {}
    return {}


def _detect_dynamic_batching_capability() -> bool:
    try:
        return bool(get_continuous_batch_enabled()) and int(get_continuous_batch_max_size()) > 1
    except Exception:
        return False


def _build_dynamic_batching_detail(enabled: bool) -> Dict[str, Any]:
    try:
        batch_enabled = bool(get_continuous_batch_enabled())
        batch_max_size = int(get_continuous_batch_max_size())
    except Exception:
        batch_enabled = False
        batch_max_size = 0
    return {
        "source": "runtime_settings",
        "enabled": enabled,
        "signals": {
            "continuous_batch_enabled": batch_enabled,
            "continuous_batch_max_size": batch_max_size,
        },
    }


def _detect_hybrid_retrieval_capability() -> bool:
    try:
        if not _RAG_PLUGIN_MANIFEST_PATH.exists():
            return False
        raw = _RAG_PLUGIN_MANIFEST_PATH.read_text(encoding="utf-8")
        manifest = json.loads(raw)
        retrieval_schema = (((manifest.get("input_schema") or {}).get("properties") or {}).get("retrieval_mode") or {})
        retrieval_enum = retrieval_schema.get("enum")
        if isinstance(retrieval_enum, list) and "hybrid" in retrieval_enum:
            return True
        return str(retrieval_schema.get("default") or "").strip().lower() == "hybrid"
    except Exception:
        return False


def _load_rag_plugin_manifest() -> Dict[str, Any]:
    try:
        if not _RAG_PLUGIN_MANIFEST_PATH.exists():
            return {}
        raw = _RAG_PLUGIN_MANIFEST_PATH.read_text(encoding="utf-8")
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _detect_multi_hop_retrieval_capability() -> bool:
    # Phase 2 的“多跳”先以多阶段检索链路参数存在作为能力信号
    manifest = _load_rag_plugin_manifest()
    rag_props = (
        (((manifest.get("input_schema") or {}).get("properties") or {}).get("rag") or {}).get("properties") or {}
    )
    return all(key in rag_props for key in ("keyword_top_k", "vector_top_k", "rerank_top_k"))


def _detect_kg_augmented_rag_capability() -> bool:
    # 通过知识库层是否暴露图谱关系检索能力判断
    return callable(getattr(KnowledgeBaseStore, "search_graph_relations", None))


def _detect_active_learning_reviewed_update_capability() -> bool:
    # 先以“支持手工质量指标回填”作为主动学习闭环的基础能力
    return callable(save_manual_quality_metrics)


def _detect_anomaly_detection_capability() -> bool:
    # 先以治理阈值配置 + 可观测摘要入口存在作为异常检测能力信号
    return (
        "chaosFailRateWarn" in ALLOWED_SYSTEM_CONFIG_KEYS
        and "chaosP95WarnMs" in ALLOWED_SYSTEM_CONFIG_KEYS
        and "chaosNetErrWarn" in ALLOWED_SYSTEM_CONFIG_KEYS
    )


def _build_anomaly_detection_detail(enabled: bool) -> Dict[str, Any]:
    anomaly_signals = {}
    try:
        snapshot = build_roadmap_snapshot()
        raw = snapshot.get("anomaly_signals")
        if isinstance(raw, dict):
            anomaly_signals = raw
    except Exception:
        anomaly_signals = {}
    breached_metrics = anomaly_signals.get("breached_metrics") if isinstance(anomaly_signals, dict) else []
    return {
        "source": "runtime_thresholds",
        "enabled": enabled,
        "signals": {
            "chaos_threshold_keys_present": all(
                key in ALLOWED_SYSTEM_CONFIG_KEYS
                for key in ("chaosFailRateWarn", "chaosP95WarnMs", "chaosNetErrWarn")
            ),
            "anomaly_detected": bool(anomaly_signals.get("anomaly_detected")) if isinstance(anomaly_signals, dict) else False,
            "breached_metrics": breached_metrics if isinstance(breached_metrics, list) else [],
        },
    }


def _detect_cluster_scaling_capability() -> bool:
    return (
        "runtimeMaxCachedLocalRuntimes" in ALLOWED_SYSTEM_CONFIG_KEYS
        and callable(build_unified_queue_summary)
    )


def _detect_model_version_governance_capability() -> bool:
    return callable(get_model_registry) and callable(build_plugin_compatibility_matrix)


def _detect_sso_integration_capability() -> bool:
    return callable(require_authenticated_platform_admin) and (Path(__file__).resolve().parent.parent / "middleware" / "rbac_enforcement.py").exists()


def _detect_multimodal_pilot_capability() -> bool:
    return (
        "asrModelId" in ALLOWED_SYSTEM_CONFIG_KEYS
        and "imageGenerationDefaultModelId" in ALLOWED_SYSTEM_CONFIG_KEYS
        and (Path(__file__).resolve().parent / "vlm.py").exists()
    )


def _build_hybrid_retrieval_detail(enabled: bool) -> Dict[str, Any]:
    detail: Dict[str, Any] = {
        "source": "rag_plugin_manifest",
        "enabled": enabled,
        "signals": {
            "manifest_exists": bool(_RAG_PLUGIN_MANIFEST_PATH.exists()),
            "retrieval_mode_default": "",
            "retrieval_mode_enum": [],
        },
    }
    try:
        if not _RAG_PLUGIN_MANIFEST_PATH.exists():
            return detail
        raw = _RAG_PLUGIN_MANIFEST_PATH.read_text(encoding="utf-8")
        manifest = json.loads(raw)
        retrieval_schema = (((manifest.get("input_schema") or {}).get("properties") or {}).get("retrieval_mode") or {})
        retrieval_enum = retrieval_schema.get("enum")
        detail["signals"]["retrieval_mode_default"] = str(retrieval_schema.get("default") or "")
        detail["signals"]["retrieval_mode_enum"] = retrieval_enum if isinstance(retrieval_enum, list) else []
    except Exception:
        return detail
    return detail


def _list_agents_for_capability_detection() -> List[Any]:
    try:
        return get_agent_registry().list_agents()
    except Exception:
        return []


def _iter_plan_based_agents_with_skills(agents: List[Any]) -> List[Any]:
    matched: List[Any] = []
    for agent in agents:
        execution_mode = str(getattr(agent, "execution_mode", "") or "").strip().lower()
        enabled_skills = getattr(agent, "enabled_skills", None) or []
        if execution_mode == "plan_based" and bool(enabled_skills):
            matched.append(agent)
    return matched


def _detect_function_calling_orchestration_capability(agents: List[Any]) -> bool:
    return bool(_iter_plan_based_agents_with_skills(agents))


def _detect_agent_role_collaboration_capability(agents: List[Any]) -> bool:
    return len(_iter_plan_based_agents_with_skills(agents)) >= 2


def _detect_roadmap_capabilities() -> Dict[str, bool]:
    agents = _list_agents_for_capability_detection()
    multi_hop_enabled = _detect_multi_hop_retrieval_capability()
    return {
        "dynamic_batching": _detect_dynamic_batching_capability(),
        "hybrid_retrieval": _detect_hybrid_retrieval_capability(),
        "multi_hop_retrieval": multi_hop_enabled,
        "multi_hop_retrieval_system": multi_hop_enabled,
        "kg_augmented_rag": _detect_kg_augmented_rag_capability(),
        "active_learning_reviewed_update": _detect_active_learning_reviewed_update_capability(),
        "anomaly_detection": _detect_anomaly_detection_capability(),
        "cluster_scaling": _detect_cluster_scaling_capability(),
        "model_version_governance": _detect_model_version_governance_capability(),
        "sso_integration": _detect_sso_integration_capability(),
        "multimodal_pilot": _detect_multimodal_pilot_capability(),
        "function_calling_orchestration": _detect_function_calling_orchestration_capability(agents),
        "agent_role_collaboration": _detect_agent_role_collaboration_capability(agents),
    }


def _detect_roadmap_capability_details() -> Dict[str, Dict[str, Any]]:
    agents = _list_agents_for_capability_detection()
    plan_based_agents = _iter_plan_based_agents_with_skills(agents)
    function_calling_enabled = bool(plan_based_agents)
    collaboration_enabled = len(plan_based_agents) >= 2
    multi_hop_enabled = _detect_multi_hop_retrieval_capability()
    return {
        "dynamic_batching": _build_dynamic_batching_detail(_detect_dynamic_batching_capability()),
        "hybrid_retrieval": _build_hybrid_retrieval_detail(_detect_hybrid_retrieval_capability()),
        "multi_hop_retrieval": {
            "source": "rag_plugin_manifest",
            "enabled": multi_hop_enabled,
            "signals": {
                "manifest_exists": bool(_RAG_PLUGIN_MANIFEST_PATH.exists()),
                "required_chain_params": ["keyword_top_k", "vector_top_k", "rerank_top_k"],
            },
        },
        "multi_hop_retrieval_system": {
            "source": "rag_plugin_manifest",
            "enabled": multi_hop_enabled,
            "signals": {
                "manifest_exists": bool(_RAG_PLUGIN_MANIFEST_PATH.exists()),
                "required_chain_params": ["keyword_top_k", "vector_top_k", "rerank_top_k"],
            },
        },
        "kg_augmented_rag": {
            "source": "knowledge_base_store",
            "enabled": _detect_kg_augmented_rag_capability(),
            "signals": {
                "search_graph_relations_available": callable(
                    getattr(KnowledgeBaseStore, "search_graph_relations", None)
                ),
            },
        },
        "active_learning_reviewed_update": {
            "source": "roadmap_quality_metrics",
            "enabled": _detect_active_learning_reviewed_update_capability(),
            "signals": {
                "manual_quality_metrics_save_available": callable(save_manual_quality_metrics),
            },
        },
        "anomaly_detection": {
            **_build_anomaly_detection_detail(_detect_anomaly_detection_capability()),
        },
        "cluster_scaling": {
            "source": "runtime_control_plane",
            "enabled": _detect_cluster_scaling_capability(),
            "signals": {
                "runtime_cache_controls_present": "runtimeMaxCachedLocalRuntimes" in ALLOWED_SYSTEM_CONFIG_KEYS,
                "queue_summary_available": callable(build_unified_queue_summary),
            },
        },
        "model_version_governance": {
            "source": "model_registry_and_plugin_matrix",
            "enabled": _detect_model_version_governance_capability(),
            "signals": {
                "model_registry_available": callable(get_model_registry),
                "plugin_compatibility_matrix_available": callable(build_plugin_compatibility_matrix),
            },
        },
        "sso_integration": {
            "source": "security_stack",
            "enabled": _detect_sso_integration_capability(),
            "signals": {
                "auth_guard_available": callable(require_authenticated_platform_admin),
                "rbac_enforcement_module_present": (
                    Path(__file__).resolve().parent.parent / "middleware" / "rbac_enforcement.py"
                ).exists(),
            },
        },
        "multimodal_pilot": {
            "source": "multimodal_endpoints_and_settings",
            "enabled": _detect_multimodal_pilot_capability(),
            "signals": {
                "asr_setting_present": "asrModelId" in ALLOWED_SYSTEM_CONFIG_KEYS,
                "image_generation_setting_present": "imageGenerationDefaultModelId" in ALLOWED_SYSTEM_CONFIG_KEYS,
                "vlm_api_present": (Path(__file__).resolve().parent / "vlm.py").exists(),
            },
        },
        "function_calling_orchestration": {
            "source": "agent_registry",
            "enabled": function_calling_enabled,
            "signals": {
                "plan_based_agents_with_skills": [str(getattr(agent, "agent_id", "")) for agent in plan_based_agents],
                "count": len(plan_based_agents),
            },
        },
        "agent_role_collaboration": {
            "source": "agent_registry",
            "enabled": collaboration_enabled,
            "signals": {
                "plan_based_agents_with_skills": [str(getattr(agent, "agent_id", "")) for agent in plan_based_agents],
                "count": len(plan_based_agents),
                "required_min_agents": 2,
            },
        },
    }


def _read_roadmap_capabilities() -> Dict[str, bool]:
    detected = _detect_roadmap_capabilities()
    manual = _read_manual_roadmap_capabilities()
    return {**detected, **manual}


@router.get("/roadmap/kpis")
async def get_roadmap_kpis_api(*, _role: Annotated[Any, Depends(require_platform_admin)]) -> Dict[str, Any]:
    return {"kpis": get_roadmap_kpis()}


@router.post("/roadmap/kpis")
async def update_roadmap_kpis_api(
    body: RoadmapKpiUpdateBody,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    merged = save_roadmap_kpis(payload)
    return {"success": True, "kpis": merged}


@router.post("/roadmap/quality-metrics")
async def update_roadmap_quality_metrics_api(
    body: RoadmapQualityMetricsUpdateBody,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    merged = save_manual_quality_metrics(payload)
    return {"success": True, "quality_metrics": merged}


@router.get("/roadmap/phases/status")
async def get_roadmap_phase_status_api(*, _role: Annotated[Any, Depends(require_platform_admin)]) -> RoadmapPhaseStatusResponse:
    snapshot = build_roadmap_snapshot()
    snapshot["capabilities"] = _read_roadmap_capabilities()
    snapshot["capability_details"] = _detect_roadmap_capability_details()
    return _build_phase_status_payload(snapshot=snapshot)


def _build_phase_status_payload(snapshot: Dict[str, Any]) -> RoadmapPhaseStatusResponse:
    gates = get_phase_gates()
    phase_status = evaluate_phase_gates(snapshot, gates)
    north_star = evaluate_north_star(snapshot, get_roadmap_kpis())
    passed_count = sum(1 for item in phase_status.values() if item.get("passed"))
    total_count = len(phase_status)
    gate_score = (passed_count / total_count) if total_count else 0.0
    blocking_capabilities = build_blocking_capabilities(phase_status)
    readiness_summary = build_phase_readiness_summary(phase_status)
    go_no_go_summary = build_go_no_go_summary(
        north_star=north_star,
        gate_score=gate_score,
        blocking_capabilities=blocking_capabilities,
        anomaly_signals=snapshot.get("anomaly_signals") if isinstance(snapshot.get("anomaly_signals"), dict) else None,
        readiness_summary=readiness_summary,
    )
    go_no_go = str(go_no_go_summary.get("go_no_go") or "no_go")
    go_no_go_reasons = list(go_no_go_summary.get("go_no_go_reasons") or [])
    top_blocker_capability = go_no_go_summary.get("top_blocker_capability")
    payload = {
        "snapshot": snapshot,
        "north_star": {
            "score": round(north_star.score, 4),
            "passed": north_star.passed,
            "reasons": north_star.reasons,
        },
        "go_no_go": go_no_go,
        "go_no_go_reasons": go_no_go_reasons,
        "top_blocker_capability": top_blocker_capability,
        "phase_gate": {
            "passed_count": passed_count,
            "total_count": total_count,
            "score": round(gate_score, 4),
            "phases": phase_status,
            "blocking_capabilities": blocking_capabilities,
            "readiness_summary": readiness_summary,
            "top_blocker_capability": top_blocker_capability,
        },
    }
    return RoadmapPhaseStatusResponse.model_validate(payload)


@router.post("/roadmap/phase-gates")
async def update_roadmap_phase_gates_api(
    body: RoadmapGateUpdateBody,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    merged = save_phase_gates(body.phase_gates)
    return {"success": True, "phase_gates": merged}


@router.post("/roadmap/monthly-review")
async def create_roadmap_monthly_review_api(
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    capabilities = _read_roadmap_capabilities()
    capability_details = _detect_roadmap_capability_details()
    review = create_monthly_review(capabilities=capabilities, capability_details=capability_details)
    return {"success": True, "review": review}


def _build_monthly_review_list_payload(
    *,
    limit: int,
    offset: int,
    top_blocker_capability: Optional[str],
    go_no_go: Optional[Literal["go", "no_go"]],
    lowest_readiness_phase: Optional[str],
    readiness_below_threshold: Optional[bool],
) -> RoadmapMonthlyReviewListResponse:
    items, total_before_limit = list_monthly_reviews_page(
        limit=limit,
        offset=offset,
        top_blocker_capability=top_blocker_capability,
        go_no_go=go_no_go,
        lowest_readiness_phase=lowest_readiness_phase,
        readiness_below_threshold=readiness_below_threshold,
    )
    has_more = (offset + len(items)) < total_before_limit
    next_offset = (offset + len(items)) if has_more else None
    prev_offset = max(0, offset - limit) if offset > 0 else None
    page_start = offset
    page_end_exclusive = offset + len(items)
    payload = {
        "count": len(items),
        "items": items,
        "meta": {
            "applied_filters": {
                "limit": limit,
                "offset": offset,
                "top_blocker_capability": top_blocker_capability,
                "go_no_go": go_no_go,
                "lowest_readiness_phase": lowest_readiness_phase,
                "readiness_below_threshold": readiness_below_threshold,
            },
            "total_before_limit": total_before_limit,
            "has_more": has_more,
            "next_offset": next_offset,
            "prev_offset": prev_offset,
            "page_window": {
                "start": page_start,
                "end_exclusive": page_end_exclusive,
            },
            "returned_order": "newest_first",
        },
    }
    return RoadmapMonthlyReviewListResponse.model_validate(payload)


@router.get("/roadmap/monthly-review")
async def list_roadmap_monthly_review_api(
    limit: Annotated[int, Query(ge=1, le=36)] = 12,
    offset: Annotated[int, Query(ge=0, le=1000)] = 0,
    top_blocker_capability: Annotated[Optional[str], Query(max_length=128)] = None,
    go_no_go: Annotated[Optional[Literal["go", "no_go"]], Query()] = None,
    lowest_readiness_phase: Annotated[Optional[str], Query(max_length=128)] = None,
    readiness_below_threshold: Annotated[Optional[bool], Query()] = None,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> RoadmapMonthlyReviewListResponse:
    return _build_monthly_review_list_payload(
        limit=limit,
        offset=offset,
        top_blocker_capability=top_blocker_capability,
        go_no_go=go_no_go,
        lowest_readiness_phase=lowest_readiness_phase,
        readiness_below_threshold=readiness_below_threshold,
    )


@router.get("/metrics")
async def get_metrics() -> Dict[str, Any]:
    """获取硬件指标"""
    from core.inference.stats.tracker import get_inference_stats
    
    cpu_usage = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()
    
    gpu_info = get_gpu_metrics()
    uptime_seconds = int(time.time() - BOOT_TIME)
    
    # Get inference speed from stats tracker
    inference_stats = get_inference_stats().get_stats()
    inference_speed = inference_stats.get("inference_speed")  # tokens/s or None
    
    return {
        "cpu_load": cpu_usage,
        "ram_used": round(memory.used / (1024**3), 1),
        "ram_total": round(memory.total / (1024**3), 1),
        "gpu_usage": gpu_info["gpu_usage"],
        "vram_used": gpu_info["vram_used"],
        "vram_total": gpu_info["vram_total"],
        "inference_speed": inference_speed,  # tokens/s or null
        "uptime": format_uptime(uptime_seconds),
        "node_version": get_node_version(),
        "cuda_version": gpu_info["cuda_version"],
        "active_workers": psutil.cpu_count(logical=False) or 4
    }

def format_uptime(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"


def _is_log_line_skippable(line: str) -> bool:
    return not line or line.startswith("Traceback") or line.startswith("File \"")


def _parse_log_entries(lines: list[str]) -> list[Dict[str, Any]]:
    entries: list[Dict[str, Any]] = []
    for raw_line in lines:
        line = raw_line.strip()
        if _is_log_line_skippable(line):
            continue
        entry = parse_log_line(line)
        if entry:
            entries.append(entry)
    return entries


async def _read_recent_log_entries(
    log_file_abs: Path, tail_count: int = 50
) -> list[Dict[str, Any]]:
    async with aiofiles.open(log_file_abs, mode='r', encoding='utf-8') as f:
        lines = await f.readlines()
    return _parse_log_entries(lines[-tail_count:])


async def _read_incremental_log_entries(
    log_file_abs: Path, last_size: int
) -> tuple[list[Dict[str, Any]], int]:
    current_size = log_file_abs.stat().st_size
    if current_size <= last_size:
        return [], last_size

    async with aiofiles.open(log_file_abs, mode='r', encoding='utf-8') as f:
        await f.seek(last_size)
        new_lines = await f.readlines()
    return _parse_log_entries(new_lines), current_size


async def _tail_log_entries(
    request: Request, log_file_abs: Path, last_size: int
) -> AsyncIterator[Dict[str, Any]]:
    while True:
        if await request.is_disconnected():
            break
        try:
            entries, next_size = await _read_incremental_log_entries(log_file_abs, last_size)
            for entry in entries:
                yield entry
            last_size = next_size
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
            await asyncio.sleep(1)


@router.get("/logs/stream")
async def stream_logs(request: Request) -> StreamingResponse:
    """实时流式推送日志"""
    # 使用与 logger.py 相同的路径计算方式（基于 __file__ 的相对路径）
    # backend/api/system.py -> backend/api -> backend -> 项目根目录
    # 先 resolve __file__ 确保是绝对路径，然后计算相对路径
    backend_api_file = Path(__file__).resolve()  # 先转换为绝对路径
    backend_api_dir = backend_api_file.parent  # backend/api
    root_dir = backend_api_dir.parent.parent  # 项目根目录 (backend/api -> backend -> 项目根目录)
    log_file = root_dir / "logs" / "app.log"  # 已经是绝对路径
    
    async def log_generator() -> AsyncIterator[str]:
        # 确保日志目录存在（log_file 已经是绝对路径）
        log_file_abs = log_file.resolve()  # 再次确保是绝对路径
        log_file_abs.parent.mkdir(parents=True, exist_ok=True)
        
        if not log_file_abs.exists():
            # 如果日志文件不存在，创建一个空文件并发送提示
            log_file_abs.touch()
            yield f"data: {json.dumps({'timestamp': '', 'level': 'INFO', 'tag': 'System', 'message': 'Log file created. Waiting for logs...'})}\n\n"
            await asyncio.sleep(0.1)

        # 先读取最后 50 行
        initial_entries = await _read_recent_log_entries(log_file_abs, tail_count=50)
        for entry in initial_entries:
            yield f"data: {json.dumps(entry)}\n\n"

        # 持续监控新日志
        # 使用轮询方式监控文件变化，因为 aiofiles.readline() 在文件末尾不会阻塞
        last_size = log_file_abs.stat().st_size if log_file_abs.exists() else 0
        async for entry in _tail_log_entries(request, log_file_abs, last_size):
            yield f"data: {json.dumps(entry)}\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")

def parse_log_line(line: str) -> Optional[Dict[str, Any]]:
    """
    解析日志行
    格式: [%(asctime)s] %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] - %(message)s
    示例: [2026-01-13 12:12:30] INFO [ai_platform] [chat.py:111] - Some message
    """
    try:
        if not line.strip() or " - " not in line:
            return None
            
        parts = line.split(" - ", 1)
        header = parts[0].strip()
        message = parts[1].strip()
        
        # 解析 header: [2026-01-13 12:12:30] INFO [ai_platform] [chat.py:111]
        if not header.startswith("[") or "]" not in header:
            return None
            
        # 提取时间戳 [2026-01-13 12:12:30]
        time_end = header.find("]")
        if time_end == -1:
            return None
        time_str = header[1:time_end]  # "2026-01-13 12:12:30"
        
        # 提取剩余部分: " INFO [ai_platform] [chat.py:111]"
        remaining = header[time_end + 1:].strip()
        if not remaining:
            return None
        
        # 提取级别 (第一个单词)
        parts_remaining = remaining.split(" ", 1)
        level = parts_remaining[0] if parts_remaining else "INFO"
        
        # 提取 tag (第一个 [xxx] 中的内容)
        tag = "System"
        if len(parts_remaining) > 1:
            tag_part = parts_remaining[1]
            tag_start = tag_part.find("[")
            if tag_start != -1:
                tag_end = tag_part.find("]", tag_start + 1)
                if tag_end != -1:
                    tag = tag_part[tag_start + 1:tag_end]

        return {
            "timestamp": time_str,  # 完整的时间戳 "2026-01-13 12:12:30"
            "level": "ERRR" if level == "ERROR" else level,
            "tag": tag,
            "message": message
        }
    except Exception as e:
        logger.debug(f"Failed to parse log line: {e}, line: {line[:100]}")
        return None


# ========== Execution Kernel 管理 API ==========

@router.get("/kernel/stats")
async def get_kernel_stats() -> Dict[str, Any]:
    """
    获取 Execution Kernel 聚合统计指标
    
    指标包括：
    - total_runs: 总执行次数
    - kernel_runs: Kernel 执行次数
    - plan_based_runs: PlanBasedExecutor 执行次数
    - kernel_success_rate: Kernel 成功率 (%)
    - kernel_fallback_rate: Kernel 回退率 (%)
    - step_fail_rate: 步骤失败率 (%)
    - replan_trigger_rate: RePlan 触发率
    - avg_duration_ms: 平均耗时
    - p50_duration_ms: P50 耗时
    - p95_duration_ms: P95 耗时
    """
    from core.agent_runtime.v2.observability import get_kernel_stats
    return cast(Dict[str, Any], get_kernel_stats().get_stats())


@router.get("/kernel/status")
async def get_kernel_status() -> Dict[str, Any]:
    """
    获取 Execution Kernel 当前状态
    
    返回：
    - enabled: 全局是否启用
    - can_toggle: 是否可以运行时切换
    """
    from core.agent_runtime.v2.runtime import USE_EXECUTION_KERNEL
    return {
        "enabled": USE_EXECUTION_KERNEL,
        "can_toggle": True,
        "description": "Execution Kernel is a DAG-based execution engine. Set USE_EXECUTION_KERNEL in runtime.py or use agent-level override."
    }


@router.post("/kernel/toggle")
async def toggle_kernel(
    data: Dict[str, Any],
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    """
    运行时切换 Execution Kernel 开关
    
    请求体：
    - enabled: true/false
    
    注意：此操作仅影响当前运行实例，重启后恢复为代码中定义的默认值。
    """
    from core.agent_runtime.v2.runtime import USE_EXECUTION_KERNEL
    import core.agent_runtime.v2.runtime as runtime_module
    
    enabled = data.get("enabled", None)
    if enabled is None:
        return {"success": False, "error": "Missing 'enabled' field"}
    
    # 运行时修改模块级变量
    runtime_module.USE_EXECUTION_KERNEL = bool(enabled)
    
    log_structured("System", "kernel_toggled", enabled=bool(enabled), previous=USE_EXECUTION_KERNEL)
    logger.info(f"[System] Execution Kernel toggled to: {enabled}")
    
    return {
        "success": True,
        "enabled": bool(enabled),
        "note": "Runtime toggle. Will reset to default on restart."
    }


@router.post("/kernel/stats/reset")
async def reset_kernel_stats(*, _role: Annotated[Any, Depends(require_platform_admin)]) -> Dict[str, Any]:
    """重置 Kernel 统计指标"""
    from core.agent_runtime.v2.observability import get_kernel_stats
    stats = get_kernel_stats()
    stats._reset()
    log_structured("System", "kernel_stats_reset")
    return {"success": True, "message": "Kernel stats reset"}


# ========== V2.7: Optimization Layer API ==========

@router.get("/kernel/optimization")
async def get_optimization_status() -> Dict[str, Any]:
    """
    V2.7: 获取 Optimization Layer 状态
    
    返回：
    - enabled: 是否启用优化
    - scheduler_policy: 调度策略信息（名称、版本）
    - snapshot: 快照信息（版本、节点数、Skill 数）
    - config: 完整配置
    """
    from core.agent_runtime.v2.runtime import get_kernel_adapter
    
    adapter = get_kernel_adapter()
    if adapter is None:
        return {
            "enabled": False,
            "error": KERNEL_ADAPTER_NOT_INITIALIZED,
        }
    if not adapter._initialized:
        await adapter.initialize()
    return cast(Dict[str, Any], adapter.get_optimization_status())


@router.post("/kernel/optimization/rebuild-snapshot")
async def rebuild_optimization_snapshot(
    data: Optional[Dict[str, Any]] = None,
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    """
    V2.7: 重新构建 OptimizationSnapshot
    
    请求体（可选）：
    - instance_ids: 指定收集的实例 ID 列表
    - limit_instances: 最大实例数量限制（默认 100）
    
    返回：
    - version: 新快照版本
    - node_count: 节点统计数
    - skill_count: Skill 统计数
    """
    from core.agent_runtime.v2.runtime import get_kernel_adapter
    
    adapter = get_kernel_adapter()
    if adapter is None:
        return {"success": False, "error": KERNEL_ADAPTER_NOT_INITIALIZED}
    if not adapter._initialized:
        await adapter.initialize()
    
    data = data or {}
    instance_ids = data.get("instance_ids")
    limit_instances = data.get("limit_instances", 100)
    
    try:
        snapshot = await adapter.rebuild_optimization_snapshot(
            instance_ids=instance_ids,
            limit_instances=limit_instances,
        )
        
        log_structured("System", "optimization_snapshot_rebuilt", 
                      version=snapshot.version,
                      node_count=len(snapshot.node_weights))
        
        return {
            "success": True,
            "version": snapshot.version,
            "node_count": len(snapshot.node_weights),
            "skill_count": len(snapshot.skill_weights),
        }
    except Exception as e:
        logger.error(f"[System] Failed to rebuild optimization snapshot: {e}")
        return {"success": False, "error": str(e)}


@router.post("/kernel/optimization/config")
async def set_optimization_config(
    data: Dict[str, Any],
    *,
    _role: Annotated[Any, Depends(require_platform_admin)],
) -> Dict[str, Any]:
    """
    V2.7: 更新 Optimization 配置
    
    请求体：
    - enabled: 是否启用优化
    - scheduler_policy: 策略名称（"default" 或 "learned"）
    - policy_params: 策略参数（仅 learned 策略有效）
      - node_weight_factor: 节点权重乘数
      - latency_penalty_factor: 延迟惩罚乘数
      - skill_weight_factor: Skill 权重乘数
      - consider_skill: 是否考虑 Skill 权重
    """
    from core.agent_runtime.v2.runtime import get_kernel_adapter
    from execution_kernel.optimization import OptimizationConfig
    
    adapter = get_kernel_adapter()
    if adapter is None:
        return {"success": False, "error": KERNEL_ADAPTER_NOT_INITIALIZED}
    if not adapter._initialized:
        await adapter.initialize()
    
    try:
        config = OptimizationConfig(
            enabled=data.get("enabled", False),
            scheduler_policy=data.get("scheduler_policy", "default"),
            policy_params=data.get("policy_params", {}),
            auto_build_snapshot=data.get("auto_build_snapshot", True),
            collect_statistics=data.get("collect_statistics", True),
        )
        
        adapter.set_optimization_config(config)
        
        # 每次更新配置都重新初始化策略，确保关闭优化时切回 DefaultPolicy
        await adapter._initialize_optimization()
        
        log_structured("System", "optimization_config_updated",
                      enabled=config.enabled,
                      policy=config.scheduler_policy)
        
        return {
            "success": True,
            "config": config.to_dict(),
        }
    except Exception as e:
        logger.error(f"[System] Failed to update optimization config: {e}")
        return {"success": False, "error": str(e)}


@router.get("/kernel/optimization/impact-report")
async def get_optimization_impact_report() -> Dict[str, Any]:
    """
    V2.7: 获取优化效果报告
    
    对比当前快照与空快照（或指定版本）的差异，计算优化效果：
    - 成功率提升百分比
    - 延迟降低百分比
    - 节点/Skill 数量变化
    """
    from core.agent_runtime.v2.runtime import get_kernel_adapter
    from execution_kernel.optimization.snapshot import OptimizationSnapshot
    from execution_kernel.analytics.metrics import compute_optimization_impact
    
    adapter = get_kernel_adapter()
    if adapter is None:
        return {"error": KERNEL_ADAPTER_NOT_INITIALIZED}
    
    if not adapter._initialized:
        await adapter.initialize()
    
    current_snapshot = adapter._optimization_snapshot
    if current_snapshot is None:
        return {"error": "No optimization snapshot available"}
    
    # 使用空快照作为基准对比
    baseline_snapshot = OptimizationSnapshot.empty()
    baseline_empty = True

    # 计算优化效果
    impact = compute_optimization_impact(baseline_snapshot, current_snapshot)

    log_structured("System", "optimization_impact_report",
                  improvement_pct=impact["improvement_pct"],
                  latency_reduction=impact["latency_reduction_pct"])

    return {
        "impact": impact,
        "baseline_empty": baseline_empty,
        "note": "空快照表示无历史数据基准，当前数值为相对「无优化」的差异；success_rate_before=0 仅表示基准无数据。",
        "current_policy": adapter._scheduler_policy.get_name() if adapter._scheduler_policy else None,
        "optimization_enabled": adapter._optimization_config.enabled if adapter._optimization_config else False,
    }
