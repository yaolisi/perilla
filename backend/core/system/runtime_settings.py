"""
运行时相关配置：优先从 SystemSettingsStore（前端可配）读取，否则回退到 config.settings。
key 与前端约定为 camelCase。
"""
from typing import Optional

from config.settings import settings
from core.system.settings_store import get_system_settings_store


def _get_bool(key: str, fallback: bool) -> bool:
    v = get_system_settings_store().get_setting(key)
    if v is None:
        return fallback
    return bool(v)


def _get_int(key: str, fallback: int, min_val: int, max_val: int) -> int:
    v = get_system_settings_store().get_setting(key)
    if v is None:
        return fallback
    try:
        n = int(v)
        return max(min_val, min(max_val, n))
    except (TypeError, ValueError):
        return fallback


def _get_float(key: str, fallback: float, min_val: float, max_val: float) -> float:
    v = get_system_settings_store().get_setting(key)
    if v is None:
        return fallback
    try:
        n = float(v)
        return max(min_val, min(max_val, n))
    except (TypeError, ValueError):
        return fallback


def get_auto_unload_local_model_on_switch() -> bool:
    return _get_bool("autoUnloadLocalModelOnSwitch", getattr(settings, "auto_unload_local_model_on_switch", False))


def get_runtime_auto_release_enabled() -> bool:
    return _get_bool("runtimeAutoReleaseEnabled", getattr(settings, "runtime_auto_release_enabled", True))


def get_runtime_max_cached_local_runtimes(model_type: str | None = None) -> int:
    fallback = getattr(settings, "runtime_max_cached_local_runtimes", 1)
    if not model_type:
        return _get_int("runtimeMaxCachedLocalRuntimes", fallback, 1, 16)

    normalized = str(model_type).lower()
    if normalized in {"vision", "multimodal"}:
        normalized = "vlm"

    specific_keys = {
        "llm": (
            "runtimeMaxCachedLocalLlmRuntimes",
            getattr(settings, "runtime_max_cached_local_llm_runtimes", fallback),
        ),
        "vlm": (
            "runtimeMaxCachedLocalVlmRuntimes",
            getattr(settings, "runtime_max_cached_local_vlm_runtimes", fallback),
        ),
        "image_generation": (
            "runtimeMaxCachedLocalImageGenerationRuntimes",
            getattr(settings, "runtime_max_cached_local_image_generation_runtimes", fallback),
        ),
    }
    key_and_fallback = specific_keys.get(normalized)
    if not key_and_fallback:
        return _get_int("runtimeMaxCachedLocalRuntimes", fallback, 1, 16)
    key, typed_fallback = key_and_fallback
    return _get_int(key, typed_fallback, 1, 16)


def get_runtime_release_idle_ttl_seconds() -> int:
    fallback = getattr(settings, "runtime_release_idle_ttl_seconds", 300)
    return _get_int("runtimeReleaseIdleTtlSeconds", fallback, 30, 86400)


def get_runtime_release_min_interval_seconds() -> int:
    fallback = getattr(settings, "runtime_release_min_interval_seconds", 5)
    return _get_int("runtimeReleaseMinIntervalSeconds", fallback, 1, 3600)


def get_inference_smart_routing_enabled() -> bool:
    return _get_bool("inferenceSmartRoutingEnabled", getattr(settings, "inference_smart_routing_enabled", True))


def get_inference_smart_routing_policies_json() -> str:
    value = get_system_settings_store().get_setting("inferenceSmartRoutingPoliciesJson")
    if value is None:
        value = getattr(settings, "inference_smart_routing_policies_json", "")
    return str(value or "")


def get_inference_queue_slo_enabled() -> bool:
    return _get_bool("inferenceQueueSloEnabled", getattr(settings, "inference_queue_slo_enabled", True))


def get_inference_queue_slo_high_ms() -> int:
    return _get_int("inferenceQueueSloHighMs", getattr(settings, "inference_queue_slo_high_ms", 3000), 200, 120000)


def get_inference_queue_slo_medium_ms() -> int:
    return _get_int("inferenceQueueSloMediumMs", getattr(settings, "inference_queue_slo_medium_ms", 6000), 200, 120000)


def get_inference_queue_slo_low_ms() -> int:
    return _get_int("inferenceQueueSloLowMs", getattr(settings, "inference_queue_slo_low_ms", 10000), 200, 120000)


def get_inference_queue_preemption_enabled() -> bool:
    return _get_bool(
        "inferenceQueuePreemptionEnabled",
        getattr(settings, "inference_queue_preemption_enabled", True),
    )


def get_inference_queue_preemption_max_per_high_request() -> int:
    return _get_int(
        "inferenceQueuePreemptionMaxPerHighRequest",
        getattr(settings, "inference_queue_preemption_max_per_high_request", 1),
        1,
        8,
    )


def get_inference_queue_preemption_max_per_task() -> int:
    return _get_int(
        "inferenceQueuePreemptionMaxPerTask",
        getattr(settings, "inference_queue_preemption_max_per_task", 2),
        1,
        20,
    )


def get_inference_queue_preemption_cooldown_ms() -> int:
    return _get_int(
        "inferenceQueuePreemptionCooldownMs",
        getattr(settings, "inference_queue_preemption_cooldown_ms", 300),
        0,
        60000,
    )


def get_inference_priority_panel_high_slo_critical_rate() -> float:
    return _get_float(
        "inferencePriorityPanelHighSloCriticalRate",
        float(getattr(settings, "inference_priority_panel_high_slo_critical_rate", 0.95)),
        0.0,
        1.0,
    )


def get_inference_priority_panel_high_slo_warning_rate() -> float:
    return _get_float(
        "inferencePriorityPanelHighSloWarningRate",
        float(getattr(settings, "inference_priority_panel_high_slo_warning_rate", 0.99)),
        0.0,
        1.0,
    )


def get_inference_priority_panel_preemption_cooldown_busy_threshold() -> int:
    return _get_int(
        "inferencePriorityPanelPreemptionCooldownBusyThreshold",
        int(getattr(settings, "inference_priority_panel_preemption_cooldown_busy_threshold", 10)),
        0,
        100000,
    )


def get_continuous_batch_enabled() -> bool:
    return _get_bool("continuousBatchEnabled", getattr(settings, "continuous_batch_enabled", True))


def get_continuous_batch_wait_ms() -> int:
    return _get_int(
        "continuousBatchWaitMs",
        int(getattr(settings, "continuous_batch_wait_ms", 12)),
        0,
        500,
    )


def get_continuous_batch_max_size() -> int:
    return _get_int(
        "continuousBatchMaxSize",
        int(getattr(settings, "continuous_batch_max_size", 8)),
        1,
        64,
    )


def get_mcp_http_emit_server_push_events() -> bool:
    """MCP Streamable HTTP：GET SSE 服务端推送是否写入事件总线；系统设置可覆盖 .env。"""
    return _get_bool(
        "mcpHttpEmitServerPushEvents",
        bool(getattr(settings, "mcp_http_emit_server_push_events", True)),
    )


def get_skill_discovery_tag_match_weight() -> float:
    """技能语义检索：标签匹配项在混合分中的权重（0–1），语义为 1 减该值。"""
    return _get_float(
        "skillDiscoveryTagMatchWeight",
        float(getattr(settings, "skill_discovery_tag_match_weight", 0.3)),
        0.0,
        1.0,
    )


def get_skill_discovery_min_semantic_similarity() -> float:
    """仅保留余弦相似度 ≥ 此值的候选项；0 表示不启用。"""
    return _get_float(
        "skillDiscoveryMinSemanticSimilarity",
        float(getattr(settings, "skill_discovery_min_semantic_similarity", 0.0)),
        0.0,
        1.0,
    )


def get_skill_discovery_min_hybrid_score() -> float:
    """混合分最低门槛；0 表示不启用。"""
    return _get_float(
        "skillDiscoveryMinHybridScore",
        float(getattr(settings, "skill_discovery_min_hybrid_score", 0.0)),
        0.0,
        1.0,
    )


def get_agent_plan_max_parallel_steps() -> int:
    """Plan 同批并行步（parallel_group / parallel_calls）全局并发上限；系统设置可覆盖 .env。"""
    fb = int(getattr(settings, "agent_plan_max_parallel_steps", 4) or 4)
    v = get_system_settings_store().get_setting("agentPlanMaxParallelSteps")
    if v is None or v == "":
        return max(1, min(32, fb))
    try:
        n = int(v)
        return max(1, min(32, n))
    except (TypeError, ValueError):
        return max(1, min(32, fb))


def get_agent_step_default_timeout_seconds() -> Optional[float]:
    """单步默认超时时长（秒）；未配置时回退到 config.settings；0/空 表示不覆盖 .env（不限制）。"""
    v = get_system_settings_store().get_setting("agentStepDefaultTimeoutSeconds")
    if v is not None and v != "" and v is not False:
        try:
            f = float(v)
            if f > 0:
                return f
            # 0 显式选择：按 .env 默认
        except (TypeError, ValueError):
            pass
    g = getattr(settings, "agent_step_default_timeout_seconds", None)
    if g is not None:
        try:
            f = float(g)
            return f if f > 0 else None
        except (TypeError, ValueError):
            pass
    return None


def get_agent_step_default_max_retries() -> int:
    fb = int(getattr(settings, "agent_step_default_max_retries", 0) or 0)
    v = get_system_settings_store().get_setting("agentStepDefaultMaxRetries")
    if v is None or v == "":
        return max(0, min(20, fb))
    try:
        n = int(v)
        return max(0, min(20, n))
    except (TypeError, ValueError):
        return max(0, min(20, fb))


def get_agent_step_default_retry_interval_seconds() -> float:
    fb = float(getattr(settings, "agent_step_default_retry_interval_seconds", 1.0) or 1.0)
    v = get_system_settings_store().get_setting("agentStepDefaultRetryIntervalSeconds")
    if v is None or v == "":
        return max(0.0, min(60.0, fb))
    try:
        f = float(v)
        return max(0.0, min(60.0, f))
    except (TypeError, ValueError):
        return max(0.0, min(60.0, fb))
