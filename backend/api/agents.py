import json
import asyncio
import math
import re
import hashlib
from string import Formatter
import uuid
from pathlib import Path
from typing import Annotated, List, Literal, Optional, Dict, Any, AsyncIterator, cast

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.orm import Session
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.agent_runtime.agent_generator import generate_agent_draft_from_nl, GenerateAgentFromNlResult
from core.agent_runtime.definition import (
    AgentDefinition,
    AgentModelParamsJsonMap,
    agent_model_params_as_dict,
    get_agent_registry,
)
from core.agent_runtime.session import (
    AgentSession,
    AgentSessionStateJsonMap,
    agent_session_state_as_dict,
    get_agent_session_store,
)
from core.agent_runtime.collaboration import (
    build_api_root_collaboration,
    merge_collaboration_into_state,
    parse_invoked_from_form,
)
from core.agent_runtime.trace import AgentTraceEvent, get_agent_trace_store
from core.agent_runtime.executor import get_agent_executor
from core.agent_runtime.loop import AgentLoop
from core.agent_runtime.rag import get_kb_store
from core.agent_runtime.v2.runtime import AgentRuntime, get_agent_runtime
from core.types import Message
from log import logger
from core.models.registry import get_model_registry
from core.skills.registry import SkillRegistry
from core.tools.sandbox import resolve_in_workspace, WorkspacePathError
from core.security.deps import require_authenticated_platform_admin
from core.security.skill_policy import get_blocked_skills
from core.idempotency.service import IdempotencyService
from core.data.base import get_db
from config.settings import settings
from api.error_i18n import localize_error_message, resolve_accept_language_for_sse
from api.errors import APIErrorHttpEnvelope, raise_api_error  # type: ignore[import-untyped]
from core.utils.user_context import get_user_id, ResourceNotFoundError, UserAccessDeniedError
from core.utils.tenant_request import get_effective_tenant_id
from core.agent_runtime.session import DEFAULT_AGENT_SESSION_TENANT_ID

router = APIRouter(
    prefix="/api/agents",
    tags=["agents"],
    dependencies=[Depends(require_authenticated_platform_admin)],
)
session_router = APIRouter(
    prefix="/api",
    tags=["agent-sessions"],
    dependencies=[Depends(require_authenticated_platform_admin)],
)

# Replan prompt template guardrails
MAX_REPLAN_PROMPT_TEMPLATE_LEN = 8000
ALLOWED_REPLAN_TEMPLATE_PLACEHOLDERS = {
    "failed_step_id",
    "failed_step_executor",
    "failed_step_error",
    "failed_step_inputs_json",
    "failed_step_outputs_json",
    "replan_count",
    "replan_limit",
    # backward-compatible placeholders
    "test_command",
    "exit_code",
    "stdout",
    "stderr",
    "fix_iteration",
    "max_fix_iterations",
}

MAX_AGENT_UPLOAD_FILES = 10
MAX_AGENT_UPLOAD_FILE_BYTES = 20 * 1024 * 1024  # 20MB
MAX_AGENT_UPLOAD_TOTAL_BYTES = 100 * 1024 * 1024  # 100MB
UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1MB
UPLOAD_CONCURRENCY = max(1, int(getattr(settings, "agent_upload_max_concurrency", 4) or 4))
_upload_semaphore = asyncio.Semaphore(UPLOAD_CONCURRENCY)
VISION_DETECT_OBJECTS_SKILL_ID = "builtin_vision.detect_objects"
AGENT_NOT_FOUND_MESSAGE = "Agent not found"
SESSION_NOT_FOUND_MESSAGE = "Session not found"
REQUEST_CANCELLED_OR_TIMED_OUT_MESSAGE = "Request cancelled or timed out"
SSE_STATUS_DELTA_SCHEMA_VERSION = 1
SSE_STREAM_RESOURCE_NOT_FOUND_ERROR_CODE = "sse_stream_resource_not_found"
SSE_STREAM_RUNTIME_ERROR_CODE = "sse_stream_runtime_error"


def _get_user_id(request: Request) -> str:
    uid = (request.headers.get("X-User-Id") or "").strip()
    return uid or "default"


def _extract_idempotency_key(request: Request) -> Optional[str]:
    key = (
        request.headers.get("Idempotency-Key")
        or request.headers.get("X-Idempotency-Key")
        or request.headers.get("X-Request-Id")
    )
    if not key:
        return None
    key = key.strip()
    return key[:256] if key else None


def _stable_request_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

class CreateAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Agent name (required)")
    description: str = Field(default="", max_length=500, description="Agent description")
    model_id: str = Field(..., description="Model ID to use for this agent")
    system_prompt: str = Field(default="", description="System prompt for the agent")
    enabled_skills: List[str] = Field(default_factory=list, description="List of Skill IDs (v1.5); Agent only sees these skills")
    tool_ids: List[str] = Field(default_factory=list, description="Deprecated: mapped to builtin_<id> skills when enabled_skills empty")
    rag_ids: List[str] = Field(default_factory=list, description="List of knowledge base IDs for RAG")
    max_steps: int = Field(default=20, ge=1, le=50, description="Maximum steps for agent execution")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Temperature for LLM generation")
    slug: Optional[str] = Field(default=None, max_length=50, description="URL-friendly identifier")
    execution_mode: Optional[str] = Field(default="legacy", description="Execution mode: 'legacy' or 'plan_based'")
    use_execution_kernel: Optional[bool] = Field(default=None, description="Agent-level override for Execution Kernel (None = follow global)")
    # V2.2: RePlan
    max_replan_count: Optional[int] = Field(default=None, ge=0, le=10, description="Max replan attempts (plan_based)")
    on_failure_strategy: Optional[str] = Field(default=None, description="On failure: stop / continue / replan")
    replan_prompt: Optional[str] = Field(default=None, description="Custom replan instruction when strategy is replan")
    response_mode: Optional[str] = Field(default=None, description="Agent response mode: default or direct_tool_result")
    # Model parameters (e.g., intent_rules, skill_param_extractors, use_skill_discovery, etc.)
    model_params: Optional[AgentModelParamsJsonMap] = Field(
        default=None,
        description=(
            "Model parameters: intent_rules, skill_param_extractors, use_skill_discovery (bool), "
            "skill_discovery (object: tag_match_weight, min_semantic_similarity, min_hybrid_score for runtime discovery), "
            "plan_execution (object: max_parallel_in_group, default_timeout_seconds, default_max_retries, "
            "default_retry_interval_seconds, default_on_timeout_strategy for PlanBasedExecutor), "
            "tool_failure_reflection (object: enabled bool, mode suggest_only), etc."
        ),
    )
    # V3: Plan → Graph → Kernel（与 model_params.execution_strategy 二选一亦可，显式字段优先由服务端合并逻辑处理）
    execution_strategy: Optional[str] = Field(
        default=None,
        description="plan_based 下执行策略：serial（串行 PlanBasedExecutor）或 parallel_kernel（Agent Graph + Execution Kernel）；null 表示按 use_execution_kernel / 全局开关推导",
    )
    max_parallel_nodes: Optional[int] = Field(
        default=None,
        ge=1,
        le=64,
        description="parallel_kernel 时 Scheduler 并发上限；null 表示使用内核默认",
    )


class GenerateAgentFromNlRequest(BaseModel):
    """自然语言生成 Agent 草稿（不落库；确认后走 POST /api/agents）。"""

    description: str = Field(..., min_length=4, max_length=8000)
    model_id: Optional[str] = Field(default=None, description="可选；缺省使用首个可用模型")
    top_skills: int = Field(default=12, ge=1, le=32, description="语义发现返回的技能数量上限")


class EnabledSkillMetaItem(BaseModel):
    id: str
    name: str
    is_mcp: bool


class AgentWithSkillsMetaResponse(AgentDefinition):
    enabled_skills_meta: List[EnabledSkillMetaItem] = Field(default_factory=list)


class AgentsListEnvelope(BaseModel):
    object: Literal["list"] = "list"
    data: List[AgentWithSkillsMetaResponse]


class AgentDeleteOkResponse(BaseModel):
    status: Literal["ok"] = "ok"


class AgentSessionsListEnvelope(BaseModel):
    object: Literal["list"] = "list"
    data: List[AgentSession]


class AgentTraceEventsListEnvelope(BaseModel):
    object: Literal["list"] = "list"
    data: List[AgentTraceEvent]


class AgentSessionDeletedResponse(BaseModel):
    deleted: bool = True
    session_id: str


def _validate_execution_strategy_field(value: Optional[str]) -> None:
    if value is None or value == "":
        return
    v = str(value).strip().lower()
    if v not in {"serial", "parallel_kernel"}:
        raise_api_error(
            status_code=400,
            code="agent_invalid_execution_strategy",
            message="execution_strategy must be one of: serial, parallel_kernel, or null",
        )


def _coerce_max_parallel_nodes(val: Any, field_label: str) -> int:
    """将 JSON 中的 max_parallel_nodes 规范为 1..64 的 int。"""
    if isinstance(val, bool):
        raise_api_error(
            status_code=400,
            code="agent_invalid_integer_field",
            message=f"{field_label} must be an integer",
            details={"field": field_label},
        )
    if isinstance(val, int):
        n = val
    elif isinstance(val, float) and val.is_integer():
        n = int(val)
    else:
        try:
            n = int(val)
        except (TypeError, ValueError):
            raise_api_error(
                status_code=400,
                code="agent_invalid_integer_field",
                message=f"{field_label} must be an integer",
                details={"field": field_label},
            )
    if n < 1 or n > 64:
        raise_api_error(
            status_code=400,
            code="agent_parallel_nodes_out_of_range",
            message=f"{field_label} must be between 1 and 64",
            details={"field": field_label},
        )
    return n


def _normalized_execution_strategy(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().lower()
    return s if s else None


def _validate_kernel_opts_consistency(
    top_execution_strategy: Optional[str],
    top_max_parallel: Optional[int],
    model_params: Dict[str, Any],
) -> None:
    """
    与运行时一致：顶字段优先于 model_params；若两处同时给出且不一致则 400。
    并对 model_params 内的 execution_strategy / max_parallel_nodes 做格式校验。
    """
    mp = model_params or {}
    if "execution_strategy" in mp and mp.get("execution_strategy") not in (None, ""):
        _validate_execution_strategy_field(str(mp.get("execution_strategy")))
    if mp.get("max_parallel_nodes") is not None:
        _coerce_max_parallel_nodes(mp.get("max_parallel_nodes"), "model_params.max_parallel_nodes")

    top_es = _normalized_execution_strategy(top_execution_strategy)
    mp_es = _normalized_execution_strategy(mp.get("execution_strategy"))
    if top_es and mp_es and top_es != mp_es:
        raise_api_error(
            status_code=400,
            code="agent_kernel_opts_execution_strategy_conflict",
            message="execution_strategy conflicts: top-level and model_params disagree; align or remove one.",
        )

    if top_max_parallel is not None and mp.get("max_parallel_nodes") is not None:
        mp_n = _coerce_max_parallel_nodes(mp.get("max_parallel_nodes"), "model_params.max_parallel_nodes")
        if top_max_parallel != mp_n:
            raise_api_error(
                status_code=400,
                code="agent_kernel_opts_max_parallel_conflict",
                message="max_parallel_nodes conflicts: top-level and model_params disagree; align or remove one.",
            )


def _validate_model_params_tool_failure_reflection(model_params: Optional[Dict[str, Any]]) -> None:
    """校验 model_params.tool_failure_reflection 形状（与 agent_runtime 反思模块一致）。"""
    if not model_params:
        return
    raw = model_params.get("tool_failure_reflection")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise_api_error(
            status_code=400,
            code="agent_invalid_tool_failure_reflection",
            message="model_params.tool_failure_reflection must be a JSON object",
            details={"field": "model_params.tool_failure_reflection"},
        )
    for key in raw:
        if key not in ("enabled", "mode"):
            raise_api_error(
                status_code=400,
                code="agent_invalid_tool_failure_reflection",
                message="model_params.tool_failure_reflection only allows keys: enabled, mode",
                details={"invalid_key": key},
            )
    if "enabled" in raw and raw["enabled"] is not None and not isinstance(raw["enabled"], bool):
        raise_api_error(
            status_code=400,
            code="agent_invalid_tool_failure_reflection",
            message="model_params.tool_failure_reflection.enabled must be a boolean",
        )
    mode = raw.get("mode")
    if mode is not None and str(mode).strip() and str(mode).strip().lower() != "suggest_only":
        raise_api_error(
            status_code=400,
            code="agent_invalid_tool_failure_reflection",
            message="model_params.tool_failure_reflection.mode must be suggest_only or omitted",
        )


def _validate_model_params_rag(model_params: Optional[Dict[str, Any]]) -> None:
    """
    校验 model_params 中与 AgentLoop / RAGRetrieval 一致的 RAG 键（仅当键存在且非 null）。
    与前端 agentRagModelParams 的 clamp 范围对齐。
    """
    if not model_params:
        return

    def _bad(field: str, message: str, **details: Any) -> None:
        raise_api_error(
            status_code=400,
            code="agent_invalid_model_params_rag",
            message=message,
            details={"field": field, **details},
        )

    mp = model_params

    if mp.get("rag_top_k") is not None:
        v = mp["rag_top_k"]
        try:
            if isinstance(v, bool):
                raise ValueError
            n = int(v)
        except (TypeError, ValueError):
            _bad("model_params.rag_top_k", "model_params.rag_top_k must be an integer between 1 and 50")
        if n < 1 or n > 50:
            _bad("model_params.rag_top_k", "model_params.rag_top_k must be between 1 and 50", value=n)

    if mp.get("rag_score_threshold") is not None:
        try:
            x = float(mp["rag_score_threshold"])
        except (TypeError, ValueError):
            _bad("model_params.rag_score_threshold", "model_params.rag_score_threshold must be a number")
        if math.isnan(x) or x <= 0 or x > 100:
            _bad(
                "model_params.rag_score_threshold",
                "model_params.rag_score_threshold must be between 0 and 100 (exclusive 0)",
                value=x,
            )

    if mp.get("rag_retrieval_mode") is not None:
        m = str(mp["rag_retrieval_mode"]).strip().lower()
        if m not in ("hybrid", "vector"):
            _bad(
                "model_params.rag_retrieval_mode",
                "model_params.rag_retrieval_mode must be hybrid or vector",
            )

    if mp.get("rag_min_relevance_score") is not None:
        try:
            x = float(mp["rag_min_relevance_score"])
        except (TypeError, ValueError):
            _bad("model_params.rag_min_relevance_score", "model_params.rag_min_relevance_score must be a number")
        if math.isnan(x) or x < 0 or x > 1:
            _bad(
                "model_params.rag_min_relevance_score",
                "model_params.rag_min_relevance_score must be between 0 and 1",
                value=x,
            )

    def _boolish(field: str, val: Any) -> None:
        if val is None:
            return
        if isinstance(val, bool):
            return
        if isinstance(val, int) and val in (0, 1):
            return
        if isinstance(val, str) and val.strip().lower() in (
            "0",
            "1",
            "true",
            "false",
            "yes",
            "no",
            "on",
            "off",
        ):
            return
        _bad(field, f"{field} must be a boolean (or 0/1, or common true/false strings)")

    _boolish("model_params.rag_multi_hop_enabled", mp.get("rag_multi_hop_enabled"))
    _boolish("model_params.rag_multi_hop_relax_relevance", mp.get("rag_multi_hop_relax_relevance"))

    if mp.get("rag_multi_hop_max_rounds") is not None:
        v = mp["rag_multi_hop_max_rounds"]
        try:
            if isinstance(v, bool):
                raise ValueError
            n = int(v)
        except (TypeError, ValueError):
            _bad(
                "model_params.rag_multi_hop_max_rounds",
                "model_params.rag_multi_hop_max_rounds must be an integer between 2 and 5",
            )
        if n < 2 or n > 5:
            _bad(
                "model_params.rag_multi_hop_max_rounds",
                "model_params.rag_multi_hop_max_rounds must be between 2 and 5",
                value=n,
            )

    if mp.get("rag_multi_hop_min_chunks") is not None:
        v = mp["rag_multi_hop_min_chunks"]
        try:
            if isinstance(v, bool):
                raise ValueError
            n = int(v)
        except (TypeError, ValueError):
            _bad(
                "model_params.rag_multi_hop_min_chunks",
                "model_params.rag_multi_hop_min_chunks must be an integer between 0 and 50",
            )
        if n < 0 or n > 50:
            _bad(
                "model_params.rag_multi_hop_min_chunks",
                "model_params.rag_multi_hop_min_chunks must be between 0 and 50",
                value=n,
            )

    if mp.get("rag_multi_hop_min_best_relevance") is not None:
        try:
            x = float(mp["rag_multi_hop_min_best_relevance"])
        except (TypeError, ValueError):
            _bad(
                "model_params.rag_multi_hop_min_best_relevance",
                "model_params.rag_multi_hop_min_best_relevance must be a number",
            )
        if math.isnan(x) or x < 0 or x > 1:
            _bad(
                "model_params.rag_multi_hop_min_best_relevance",
                "model_params.rag_multi_hop_min_best_relevance must be between 0 and 1",
                value=x,
            )

    if mp.get("rag_multi_hop_feedback_chars") is not None:
        v = mp["rag_multi_hop_feedback_chars"]
        try:
            if isinstance(v, bool):
                raise ValueError
            n = int(v)
        except (TypeError, ValueError):
            _bad(
                "model_params.rag_multi_hop_feedback_chars",
                "model_params.rag_multi_hop_feedback_chars must be an integer between 80 and 2000",
            )
        if n < 80 or n > 2000:
            _bad(
                "model_params.rag_multi_hop_feedback_chars",
                "model_params.rag_multi_hop_feedback_chars must be between 80 and 2000",
                value=n,
            )


def _apply_response_mode(
    model_params: Optional[Dict[str, Any]],
    response_mode: Optional[str],
    enabled_skills: List[str],
) -> Dict[str, Any]:
    params = dict(model_params or {})
    mode = (response_mode or params.get("response_mode") or "default").strip() or "default"
    if mode not in {"default", "direct_tool_result"}:
        raise_api_error(
            status_code=400,
            code="agent_invalid_response_mode",
            message="response_mode must be one of: default, direct_tool_result",
        )

    params["response_mode"] = mode
    if mode == "direct_tool_result":
        params["skill_direct_response_ids"] = list(enabled_skills or [])
    else:
        params.pop("skill_direct_response_ids", None)
    return params

class RunAgentRequest(BaseModel):
    messages: List[Message]
    session_id: Optional[str] = None
    # 多 Agent 协作（Phase 0）：写入 session.state["collaboration"] 与 Kernel initial_context
    correlation_id: Optional[str] = None
    orchestrator_agent_id: Optional[str] = None
    invoked_from: Optional[AgentModelParamsJsonMap] = None

def _normalize_id_list(items: List[str]) -> List[str]:
    """Normalize user-provided id lists: strip, drop empty, de-duplicate (preserve order)."""
    out: List[str] = []
    seen = set()
    for raw in items or []:
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


# v1.5 compatibility: historical skill id aliases (avoid breaking old agents / old UI payloads)
_SKILL_ID_ALIASES = {
    # old -> new
    "builtin_vision.detect": VISION_DETECT_OBJECTS_SKILL_ID,
    # Some older payloads/records used non-builtin ids
    "vision.detect": VISION_DETECT_OBJECTS_SKILL_ID,
    "vision.detect_objects": VISION_DETECT_OBJECTS_SKILL_ID,
}


def _normalize_skill_ids(skill_ids: List[str]) -> List[str]:
    """Normalize + apply skill id aliases (keep order, de-duplicate)."""
    normalized = _normalize_id_list(skill_ids)
    mapped: List[str] = []
    for s in normalized:
        s2 = _SKILL_ID_ALIASES.get(s, s)

        # Accept both forms:
        # - builtin_<tool_name> (v1.5 Skill id)
        # - <tool_name> (legacy / UI payload / recovered data)
        if not s2.startswith("builtin_"):
            # If it's not a registered skill id, but builtin_<id> exists, promote it.
            if not SkillRegistry.get(s2) and SkillRegistry.get(f"builtin_{s2}"):
                s2 = f"builtin_{s2}"

        mapped.append(s2)
    return _normalize_id_list(mapped)


def _validate_replan_prompt_template(replan_prompt: str) -> Optional[str]:
    """Validate replan prompt template format and placeholder safety."""
    prompt = (replan_prompt or "").strip()
    if not prompt:
        return None
    if len(prompt) > MAX_REPLAN_PROMPT_TEMPLATE_LEN:
        return (
            f"replan_prompt is too long (max {MAX_REPLAN_PROMPT_TEMPLATE_LEN} characters)"
        )
    try:
        for _, field_name, _, _ in Formatter().parse(prompt):
            if field_name is None:
                continue
            if not re.fullmatch(r"\w+", field_name or ""):
                return (
                    f"replan_prompt placeholder '{field_name}' has unsupported format; "
                    "only {word_characters} are allowed"
                )
            if field_name not in ALLOWED_REPLAN_TEMPLATE_PLACEHOLDERS:
                return (
                    f"replan_prompt placeholder '{field_name}' is not allowed; "
                    f"allowed: {sorted(ALLOWED_REPLAN_TEMPLATE_PLACEHOLDERS)}"
                )
    except ValueError as e:
        return f"replan_prompt template format is invalid: {e}"
    return None


def _enforce_skill_safety(skill_ids: List[str]) -> None:
    blocked = get_blocked_skills(skill_ids)
    if blocked:
        raise_api_error(
            status_code=403,
            code="agent_skill_blocked_by_policy",
            message=(
                "dangerous skills are disabled by server policy: "
                + ", ".join(sorted(blocked))
            ),
            details={"blocked_skills": sorted(blocked)},
        )


def _enabled_skills_meta(skill_ids: List[str]) -> List[EnabledSkillMetaItem]:
    """与 enabled_skills 同序；供执行页等 UI 展示名称与 MCP 标记，无需再请求 /api/skills。"""
    out: List[EnabledSkillMetaItem] = []
    for sid in skill_ids:
        skill = SkillRegistry.get(sid)
        if skill:
            d = skill.to_dict()
            out.append(
                EnabledSkillMetaItem(
                    id=sid,
                    name=str(d.get("name") or sid),
                    is_mcp=bool(d.get("is_mcp")),
                )
            )
        else:
            out.append(EnabledSkillMetaItem(id=sid, name=sid, is_mcp=False))
    return out


def _agent_with_skills_meta(a: AgentDefinition) -> AgentWithSkillsMetaResponse:
    """JSON 序列化 + enabled_skills_meta（与 GET/列表一致）。"""
    meta = _enabled_skills_meta(list(a.enabled_skills or []))
    return AgentWithSkillsMetaResponse(**a.model_dump(mode="json"), enabled_skills_meta=meta)


@router.get("", response_model=AgentsListEnvelope)
async def list_agents() -> AgentsListEnvelope:
    registry = get_agent_registry()
    data = [_agent_with_skills_meta(a) for a in registry.list_agents()]
    return AgentsListEnvelope(object="list", data=data)

@router.post(
    "",
    response_model=AgentWithSkillsMetaResponse,
    responses={
        400: {
            "model": APIErrorHttpEnvelope,
            "description": "Business validation failed (e.g. invalid model_params / RAG fields).",
        },
        503: {
            "model": APIErrorHttpEnvelope,
            "description": "Knowledge base store unavailable when validating rag_ids.",
        },
    },
)
async def create_agent(req: CreateAgentRequest, request: Request) -> AgentWithSkillsMetaResponse:
    """Create a new agent with validation"""
    registry = get_agent_registry()
    
    # Validate model_id exists
    model_registry = get_model_registry()
    model = model_registry.get_model(req.model_id)
    if not model:
        # Also check if it's a valid model in any runtime
        available_models = model_registry.list_models()
        model_exists = any(m.id == req.model_id for m in available_models)
        if not model_exists:
            raise_api_error(
                status_code=400,
                code="agent_model_not_found",
                message=f"Model '{req.model_id}' not found. Please select a valid model.",
                details={"model_id": req.model_id},
            )

    # v1.5: enabled_skills 优先；若无则从 tool_ids 映射为 builtin_<tool_id>
    enabled_skills = _normalize_skill_ids(req.enabled_skills)
    if not enabled_skills and req.tool_ids:
        enabled_skills = _normalize_skill_ids([f"builtin_{t}" for t in _normalize_id_list(req.tool_ids)])
    for skill_id in enabled_skills:
        if not SkillRegistry.get(skill_id):
            raise_api_error(
                status_code=400,
                code="agent_skill_not_found",
                message=f"Skill '{skill_id}' not found. Please select a valid skill.",
                details={"skill_id": skill_id},
            )
    _enforce_skill_safety(enabled_skills)

    # Normalize and validate rag_ids (knowledge bases)
    rag_ids = _normalize_id_list(req.rag_ids)
    if rag_ids:
        kb_store = get_kb_store()
        if not kb_store:
            raise_api_error(
                status_code=503,
                code="agent_kb_store_unavailable",
                message="Knowledge base store is not available. Please try again later.",
            )
        uid = get_user_id(request)
        tid = get_effective_tenant_id(request)
        for kb_id in rag_ids:
            try:
                kb_ok = kb_store.get_knowledge_base(kb_id, user_id=uid, tenant_id=tid)
            except ResourceNotFoundError:
                kb_ok = None
            except UserAccessDeniedError:
                raise_api_error(
                    status_code=403,
                    code="agent_knowledge_base_access_denied",
                    message=f"Access denied for knowledge base '{kb_id}'.",
                    details={"knowledge_base_id": kb_id},
                )
            if not kb_ok:
                raise_api_error(
                    status_code=400,
                    code="agent_knowledge_base_not_found",
                    message=f"Knowledge base '{kb_id}' not found. Please select a valid knowledge base.",
                    details={"knowledge_base_id": kb_id},
                )

    failure_strategy = (req.on_failure_strategy or "stop").strip() or "stop"
    if failure_strategy not in {"stop", "continue", "replan"}:
        raise_api_error(
            status_code=400,
            code="agent_invalid_on_failure_strategy",
            message="on_failure_strategy must be one of: stop, continue, replan",
        )
    replan_prompt = (req.replan_prompt or "").strip()
    if failure_strategy == "replan" and not replan_prompt:
        raise_api_error(
            status_code=400,
            code="agent_replan_prompt_required",
            message="replan_prompt is required when on_failure_strategy is 'replan'",
        )
    replan_validate_error = _validate_replan_prompt_template(replan_prompt)
    if replan_validate_error:
        raise_api_error(
            status_code=400,
            code="agent_invalid_replan_prompt",
            message=replan_validate_error,
        )

    # Generate agent_id
    agent_id = f"agent_{uuid.uuid4().hex[:8]}"
    
    # Create agent definition (v1.5: store enabled_skills; keep tool_ids for backward compat)
    model_params = _apply_response_mode(
        req.model_params.model_dump(mode="json") if req.model_params is not None else None,
        req.response_mode,
        enabled_skills,
    )
    _validate_execution_strategy_field(req.execution_strategy)
    _validate_kernel_opts_consistency(req.execution_strategy, req.max_parallel_nodes, model_params)
    _validate_model_params_tool_failure_reflection(model_params)
    _validate_model_params_rag(model_params)

    agent = AgentDefinition(
        agent_id=agent_id,
        name=req.name.strip(),
        description=req.description.strip(),
        model_id=req.model_id,
        system_prompt=req.system_prompt.strip() if req.system_prompt else "",
        enabled_skills=enabled_skills,
        tool_ids=[s[8:] for s in enabled_skills if s.startswith("builtin_")],
        rag_ids=rag_ids,
        max_steps=req.max_steps,
        temperature=req.temperature,
        slug=req.slug.strip() if req.slug else None,
        execution_mode=req.execution_mode or "legacy",
        use_execution_kernel=req.use_execution_kernel,
        execution_strategy=req.execution_strategy,
        max_parallel_nodes=req.max_parallel_nodes,
        max_replan_count=req.max_replan_count if req.max_replan_count is not None else 3,
        on_failure_strategy=failure_strategy,
        replan_prompt=replan_prompt,
        model_params=AgentModelParamsJsonMap.model_validate(model_params or {}),
    )
    
    if registry.create_agent(agent):
        logger.info(f"[Agent API] Agent created successfully: {agent_id} - {req.name}")
        return _agent_with_skills_meta(agent)
    raise_api_error(status_code=500, code="agent_create_failed", message="Failed to create agent")


@router.post(
    "/generate-from-nl",
    response_model=GenerateAgentFromNlResult,
    responses={
        400: {
            "model": APIErrorHttpEnvelope,
            "description": "NL draft validation failed (e.g. description too short, unknown model).",
        },
        503: {
            "model": APIErrorHttpEnvelope,
            "description": "No models available for NL generation.",
        },
    },
)
async def generate_agent_from_nl(req: GenerateAgentFromNlRequest) -> GenerateAgentFromNlResult:
    """
    基于本地模型与 Skill 语义发现生成 Agent 草稿；不写入数据库。
    """
    try:
        mid = (req.model_id or "").strip()
        result = await generate_agent_draft_from_nl(
            req.description.strip(),
            model_id=mid if mid else None,
            top_skills=req.top_skills,
        )
        return result
    except ValueError as e:
        msg = str(e)
        if msg == "description_too_short":
            raise_api_error(
                status_code=400,
                code="agent_nl_description_too_short",
                message="description must be at least 4 characters",
            )
        if msg == "no_models_available":
            raise_api_error(
                status_code=503,
                code="agent_nl_no_models",
                message="No models available; scan or configure a model first.",
            )
        if msg.startswith("model_id not found:"):
            mid = msg.split(":", 1)[-1].strip()
            raise_api_error(
                status_code=400,
                code="agent_model_not_found",
                message=f"Model '{mid}' not found.",
                details={"model_id": mid},
            )
        raise_api_error(
            status_code=400,
            code="agent_nl_generate_invalid",
            message=msg,
        )


@router.get(
    "/{agent_id}",
    response_model=AgentWithSkillsMetaResponse,
    responses={
        404: {
            "model": APIErrorHttpEnvelope,
            "description": "Agent not found.",
        },
    },
)
async def get_agent(agent_id: str) -> AgentWithSkillsMetaResponse:
    registry = get_agent_registry()
    agent = registry.get_agent(agent_id)
    if not agent:
        raise_api_error(
            status_code=404,
            code="agent_not_found",
            message=AGENT_NOT_FOUND_MESSAGE,
            details={"agent_id": agent_id},
        )
    return _agent_with_skills_meta(agent)

@router.put(
    "/{agent_id}",
    response_model=AgentWithSkillsMetaResponse,
    responses={
        400: {
            "model": APIErrorHttpEnvelope,
            "description": "Business validation failed (e.g. invalid model_params / RAG fields).",
        },
        404: {
            "model": APIErrorHttpEnvelope,
            "description": "Agent not found.",
        },
        503: {
            "model": APIErrorHttpEnvelope,
            "description": "Knowledge base store unavailable when validating rag_ids.",
        },
    },
)
async def update_agent(agent_id: str, req: CreateAgentRequest, request: Request) -> AgentWithSkillsMetaResponse:
    registry = get_agent_registry()
    
    # 获取现有 agent，用于合并 model_params
    existing_agent = registry.get_agent(agent_id)
    if not existing_agent:
        raise_api_error(
            status_code=404,
            code="agent_not_found",
            message=AGENT_NOT_FOUND_MESSAGE,
            details={"agent_id": agent_id},
        )
    assert existing_agent is not None
    
    enabled_skills = _normalize_skill_ids(req.enabled_skills)
    if not enabled_skills and req.tool_ids:
        enabled_skills = _normalize_skill_ids([f"builtin_{t}" for t in _normalize_id_list(req.tool_ids)])
    for skill_id in enabled_skills:
        if not SkillRegistry.get(skill_id):
            raise_api_error(
                status_code=400,
                code="agent_skill_not_found",
                message=f"Skill '{skill_id}' not found.",
                details={"skill_id": skill_id},
            )
    _enforce_skill_safety(enabled_skills)

    # Normalize and validate rag_ids (knowledge bases), aligned with create_agent
    rag_ids = _normalize_id_list(req.rag_ids)
    if rag_ids:
        kb_store = get_kb_store()
        if not kb_store:
            raise_api_error(
                status_code=503,
                code="agent_kb_store_unavailable",
                message="Knowledge base store is not available. Please try again later.",
            )
        uid = get_user_id(request)
        tid = get_effective_tenant_id(request)
        for kb_id in rag_ids:
            try:
                kb_ok = kb_store.get_knowledge_base(kb_id, user_id=uid, tenant_id=tid)
            except ResourceNotFoundError:
                kb_ok = None
            except UserAccessDeniedError:
                raise_api_error(
                    status_code=403,
                    code="agent_knowledge_base_access_denied",
                    message=f"Access denied for knowledge base '{kb_id}'.",
                    details={"knowledge_base_id": kb_id},
                )
            if not kb_ok:
                raise_api_error(
                    status_code=400,
                    code="agent_knowledge_base_not_found",
                    message=f"Knowledge base '{kb_id}' not found. Please select a valid knowledge base.",
                    details={"knowledge_base_id": kb_id},
                )

    # 深度合并 model_params：保留原有字段，只更新请求中提供的字段
    if req.model_params is not None:
        existing_params = agent_model_params_as_dict(existing_agent.model_params)
        model_params = {**existing_params, **req.model_params.model_dump(mode="json")}
    else:
        model_params = agent_model_params_as_dict(existing_agent.model_params)
    model_params = _apply_response_mode(model_params, req.response_mode, enabled_skills)

    failure_strategy = (req.on_failure_strategy or "stop").strip() or "stop"
    if failure_strategy not in {"stop", "continue", "replan"}:
        raise_api_error(
            status_code=400,
            code="agent_invalid_on_failure_strategy",
            message="on_failure_strategy must be one of: stop, continue, replan",
        )
    replan_prompt = (req.replan_prompt or "").strip()
    if failure_strategy == "replan" and not replan_prompt:
        raise_api_error(
            status_code=400,
            code="agent_replan_prompt_required",
            message="replan_prompt is required when on_failure_strategy is 'replan'",
        )
    replan_validate_error = _validate_replan_prompt_template(replan_prompt)
    if replan_validate_error:
        raise_api_error(
            status_code=400,
            code="agent_invalid_replan_prompt",
            message=replan_validate_error,
        )

    exec_strategy = (
        req.execution_strategy
        if req.execution_strategy is not None
        else getattr(existing_agent, "execution_strategy", None)
    )
    max_parallel = (
        req.max_parallel_nodes
        if req.max_parallel_nodes is not None
        else getattr(existing_agent, "max_parallel_nodes", None)
    )
    _validate_execution_strategy_field(exec_strategy)
    _validate_kernel_opts_consistency(exec_strategy, max_parallel, model_params)
    _validate_model_params_tool_failure_reflection(model_params)
    _validate_model_params_rag(model_params)

    agent = AgentDefinition(
        agent_id=agent_id,
        name=req.name,
        description=req.description,
        model_id=req.model_id,
        system_prompt=req.system_prompt,
        enabled_skills=enabled_skills,
        tool_ids=[s[8:] for s in enabled_skills if s.startswith("builtin_")],
        rag_ids=rag_ids,
        max_steps=req.max_steps,
        temperature=req.temperature,
        execution_mode=req.execution_mode or "legacy",
        use_execution_kernel=req.use_execution_kernel,
        execution_strategy=exec_strategy,
        max_parallel_nodes=max_parallel,
        max_replan_count=req.max_replan_count if req.max_replan_count is not None else 3,
        on_failure_strategy=failure_strategy,
        replan_prompt=replan_prompt,
        model_params=AgentModelParamsJsonMap.model_validate(model_params or {}),
    )
    if registry.update_agent(agent):
        return _agent_with_skills_meta(agent)
    raise_api_error(status_code=500, code="agent_update_failed", message="Failed to update agent")

@router.delete(
    "/{agent_id}",
    response_model=AgentDeleteOkResponse,
    responses={
        404: {
            "model": APIErrorHttpEnvelope,
            "description": "Agent not found.",
        },
    },
)
async def delete_agent(agent_id: str) -> AgentDeleteOkResponse:
    registry = get_agent_registry()
    if registry.delete_agent(agent_id):
        return AgentDeleteOkResponse(status="ok")
    raise_api_error(
        status_code=404,
        code="agent_not_found",
        message=AGENT_NOT_FOUND_MESSAGE,
        details={"agent_id": agent_id},
    )

def _get_agent_workspaces_root() -> Path:
    """Return data/agent_workspaces directory for session file uploads."""
    root = Path(__file__).resolve().parents[1] / "data"
    root.mkdir(parents=True, exist_ok=True)
    workspaces = root / "agent_workspaces"
    workspaces.mkdir(parents=True, exist_ok=True)
    return workspaces


def _normalize_filename(name: str) -> str:
    """NFC 归一化，避免 macOS NFD 与 LLM 传的 NFC 不一致导致找不到文件。"""
    import unicodedata
    return unicodedata.normalize("NFC", name)


def _resolve_agent_runtime_workspace(agent: AgentDefinition, session_id: str) -> str:
    """
    Resolve runtime workspace for an agent session.
    - Default: per-session workspace (data/agent_workspaces/{session_id})
    - Optional override: agent.model_params.workspace_root (absolute or relative)
    """
    session_workspace = (_get_agent_workspaces_root() / session_id).resolve()
    session_workspace.mkdir(parents=True, exist_ok=True)

    model_params = agent_model_params_as_dict(getattr(agent, "model_params", None))
    custom_root = model_params.get("workspace_root")
    if not custom_root:
        return str(session_workspace)

    try:
        candidate = Path(str(custom_root)).expanduser()
        if not candidate.is_absolute():
            # Relative path is resolved against project backend dir for predictability
            candidate = (Path(__file__).resolve().parents[1] / candidate).resolve()
        if candidate.exists() and candidate.is_dir():
            logger.info(f"[Agent API] Using agent workspace_root override: {candidate}")
            return str(candidate)
        logger.warning(
            f"[Agent API] Invalid workspace_root '{custom_root}' for agent={agent.agent_id}, fallback to session workspace"
        )
    except Exception as e:
        logger.warning(
            f"[Agent API] Failed to resolve workspace_root '{custom_root}' for agent={agent.agent_id}: {e}"
        )
    return str(session_workspace)


async def _save_uploaded_files(session_id: str, files: List[UploadFile]) -> Path:
    """Save uploaded files to session workspace; return workspace absolute path."""
    workspaces_root = _get_agent_workspaces_root()
    workspace_dir = workspaces_root / session_id
    workspace_dir.mkdir(parents=True, exist_ok=True)
    total_written = 0
    for f in files or []:
        if not f.filename or f.filename.strip() == "":
            continue
        # 使用 basename + NFC 归一化，避免路径穿越及 macOS 文件名编码差异
        raw_name = Path(f.filename).name
        safe_name = _normalize_filename(raw_name)
        dest = workspace_dir / safe_name
        written = 0
        with dest.open("wb") as out:
            while True:
                chunk = await f.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                total_written += len(chunk)
                _validate_upload_size_limits(
                    safe_name=safe_name,
                    written_bytes=written,
                    total_written_bytes=total_written,
                )
                out.write(chunk)
        await f.close()
    return workspace_dir.resolve()


def _validate_upload_size_limits(
    *,
    safe_name: str,
    written_bytes: int,
    total_written_bytes: int,
) -> None:
    if written_bytes > MAX_AGENT_UPLOAD_FILE_BYTES:
        raise_api_error(
            status_code=413,
            code="agent_upload_file_too_large",
            message=f"file '{safe_name}' exceeds max size {MAX_AGENT_UPLOAD_FILE_BYTES} bytes",
            details={"filename": safe_name},
        )
    if total_written_bytes > MAX_AGENT_UPLOAD_TOTAL_BYTES:
        raise_api_error(
            status_code=413,
            code="agent_upload_total_too_large",
            message=f"total upload size exceeds max {MAX_AGENT_UPLOAD_TOTAL_BYTES} bytes",
        )


def _parse_run_with_files_messages(messages: str) -> List[Message]:
    try:
        messages_list = json.loads(messages)
    except json.JSONDecodeError as e:
        raise_api_error(
            status_code=400,
            code="agent_invalid_messages_json",
            message=f"Invalid messages JSON: {e}",
        )
    if not isinstance(messages_list, list):
        raise_api_error(
            status_code=400,
            code="agent_invalid_messages_format",
            message="messages must be a JSON array",
        )
    return [Message(**m) if isinstance(m, dict) else m for m in messages_list]


async def _acquire_upload_slot() -> None:
    try:
        await asyncio.wait_for(_upload_semaphore.acquire(), timeout=0.001)
    except asyncio.TimeoutError:
        raise_api_error(
            status_code=429,
            code="agent_upload_rate_limited",
            message="too many concurrent upload requests, please retry later",
        )


async def _process_uploaded_files(session_id: str, files: List[UploadFile]) -> tuple[str, List[str]]:
    workspace_path = await _save_uploaded_files(session_id, files)
    workspace_dir_str = str(workspace_path)
    saved_names = [
        _normalize_filename(Path(f.filename).name)
        for f in files
        if f.filename and f.filename.strip()
    ]
    logger.info(f"[Agent API] Saved {len(files)} file(s) to workspace {workspace_dir_str} names={saved_names}")
    if saved_names:
        first_path = workspace_path / saved_names[0]
        logger.info(
            f"[Agent API] verify first file exists={first_path.is_file()} "
            f"path={first_path} dir_list={list(workspace_path.iterdir())}"
        )
    return workspace_dir_str, saved_names


def _build_image_upload_hint(first_file: str, enabled_skills: List[str], execution_mode: str) -> str:
    has_vision = VISION_DETECT_OBJECTS_SKILL_ID in enabled_skills
    has_vlm = "builtin_vlm.generate" in enabled_skills
    if has_vision:
        if execution_mode == "plan_based":
            return (
                f"\n\n[Files saved to workspace. Image: \"{first_file}\". "
                f"You can reference the image by filename \"{first_file}\" when needed. "
                "Do NOT ask user for paths.]"
            )
        return (
            f"\n\n[Files saved to workspace. Image: \"{first_file}\". "
            f"Call vision.detect_objects with {{\"image\": \"{first_file}\"}} to analyze. "
            f"Respond ONLY in JSON, e.g. {{\"type\": \"skill_call\", \"skill_id\": \"{VISION_DETECT_OBJECTS_SKILL_ID}\", "
            f"\"input\": {{\"image\": \"{first_file}\"}}}}. Do NOT ask user for paths.]"
        )
    if has_vlm:
        if execution_mode == "plan_based":
            return (
                f"\n\n[Files saved to workspace. Image: \"{first_file}\". "
                f"Use the image filename \"{first_file}\" as reference when needed. "
                "Do NOT ask user for paths.]"
            )
        return (
            f"\n\n[Files saved to workspace. Image: \"{first_file}\". "
            f"You MUST call builtin_vlm.generate skill to analyze this image and get the actual text/content from the image. "
            f"Do NOT use the image filename (e.g. \"{first_file}\") as the recognized text. "
            f"Use {{\"type\": \"skill_call\", \"skill_id\": \"builtin_vlm.generate\", \"input\": "
            f"{{\"image\": \"{first_file}\", \"prompt\": \"<user's question>\"}}}}. "
            "Do NOT ask user for paths. Do NOT provide final answer without calling the skill first.]"
        )
    return (
        f"\n\n[Files saved to workspace. Image: \"{first_file}\". "
        f"Use the image path \"{first_file}\" when needed. "
        "Do NOT ask user for paths.]"
    )


def _build_file_upload_hint(saved_names: List[str], agent: AgentDefinition) -> str:
    first_file = saved_names[0]
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    is_image = any(Path(name).suffix.lower() in image_exts for name in saved_names)
    if is_image:
        enabled_skills = agent.enabled_skills or []
        execution_mode = (getattr(agent, "execution_mode", None) or "legacy").strip().lower()
        return _build_image_upload_hint(first_file, enabled_skills, execution_mode)

    if len(saved_names) > 1:
        return (
            "\n\n[Files have been saved to the current workspace: "
            + ", ".join(f'"{n}"' for n in saved_names)
            + ". When using file.read, use the **relative path** (filename only), e.g. path=\""
            + first_file
            + "\". Do NOT use absolute paths.]"
        )
    return (
        "\n\n[Files have been saved to the current workspace. "
        "When using file.read, use the **relative path** (filename only), e.g. path=\""
        + first_file
        + "\". Do NOT use absolute paths.]"
    )


def _attach_upload_hint(messages_objs: List[Message], saved_names: List[str], agent: AgentDefinition) -> None:
    if not (messages_objs and saved_names):
        return
    last = messages_objs[-1]
    hint = _build_file_upload_hint(saved_names, agent)
    if isinstance(last.content, str):
        merged_content: Any = last.content + hint
    else:
        merged_content = list(last.content)
        merged_content.append({"type": "text", "text": hint})
    messages_objs[-1] = Message(role=last.role, content=merged_content)


def _prepare_run_with_files_session(
    *,
    session_store: Any,
    session_id: str,
    agent_id: str,
    user_id: str,
    tenant_id: str,
    messages_objs: List[Message],
    saved_names: List[str],
    workspace_dir_str: str,
    collaboration: Optional[Dict[str, Any]] = None,
) -> AgentSession:
    tid = (tenant_id or DEFAULT_AGENT_SESSION_TENANT_ID).strip() or DEFAULT_AGENT_SESSION_TENANT_ID
    principal = session_store.get_session_principal(session_id)
    if principal:
        pu, pt = principal
        if pu != user_id or pt != tid:
            raise_api_error(
                status_code=409,
                code="agent_session_id_conflict",
                message=(
                    f"Session ID '{session_id}' is already bound to another user or tenant."
                ),
                details={"session_id": session_id},
            )
    session = cast(
        Optional[AgentSession],
        session_store.get_session(session_id, user_id=user_id, tenant_id=tid),
    )
    if not session:
        session = AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
            tenant_id=tid,
            messages=messages_objs,
            status="idle",
        )
    else:
        session.messages.extend(messages_objs)
        session.status = "idle"
        session.step = 0

    if saved_names:
        st = agent_session_state_as_dict(session.state)
        st["last_uploaded_images"] = saved_names
        st["last_uploaded_image"] = saved_names[0]
        session.state = AgentSessionStateJsonMap.model_validate(st)

    if collaboration:
        session.state = AgentSessionStateJsonMap.model_validate(
            merge_collaboration_into_state(agent_session_state_as_dict(session.state), collaboration)
        )

    session.workspace_dir = workspace_dir_str
    session.status = "running"
    session.error_message = None
    session_store.save_session(session)
    return cast(AgentSession, session)


def _claim_run_idempotency(
    *,
    db: Session,
    idem_key: Optional[str],
    user_id: str,
    tenant_id: str,
    agent_id: str,
    req: RunAgentRequest,
    session_store: Any,
) -> tuple[Optional[IdempotencyService], Optional[Any]]:
    if not idem_key:
        return None, None
    idem_service = IdempotencyService(db)
    req_hash = _stable_request_hash(
        {
            "agent_id": agent_id,
            "session_id": req.session_id,
            "messages": [m.model_dump(mode="json") for m in (req.messages or [])],
            "correlation_id": req.correlation_id,
            "orchestrator_agent_id": req.orchestrator_agent_id,
            "invoked_from": req.invoked_from.model_dump(mode="json") if req.invoked_from is not None else None,
        }
    )
    claim = idem_service.claim(
        scope="agent_run",
        owner_id=user_id,
        key=idem_key,
        request_hash=req_hash,
        tenant_id=tenant_id,
    )
    if claim.conflict:
        raise_api_error(
            status_code=409,
            code="idempotency_conflict",
            message="Idempotency-Key already used with different request payload",
            details={"scope": "agent_run"},
        )
    idem_record = claim.record
    if not claim.is_new:
        if claim.record.response_ref:
            existing_session = session_store.get_session(
                claim.record.response_ref,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            if existing_session:
                return idem_service, existing_session
        raise_api_error(
            status_code=409,
            code="idempotency_in_progress",
            message="Idempotent request is still processing; retry later",
            details={"scope": "agent_run"},
        )
    return idem_service, idem_record


def _prepare_run_session(
    *,
    session_store: Any,
    session_id: str,
    agent_id: str,
    user_id: str,
    tenant_id: str,
    messages: List[Message],
    agent: AgentDefinition,
    collaboration: Optional[Dict[str, Any]] = None,
) -> tuple[AgentSession, str]:
    tid = (tenant_id or DEFAULT_AGENT_SESSION_TENANT_ID).strip() or DEFAULT_AGENT_SESSION_TENANT_ID
    principal = session_store.get_session_principal(session_id)
    if principal:
        pu, pt = principal
        if pu != user_id or pt != tid:
            raise_api_error(
                status_code=409,
                code="agent_session_id_conflict",
                message=(
                    f"Session ID '{session_id}' is already bound to another user or tenant."
                ),
                details={"session_id": session_id},
            )
    session = session_store.get_session(session_id, user_id=user_id, tenant_id=tid)
    if not session:
        session = AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
            tenant_id=tid,
            messages=messages,
            status="idle",
        )
    else:
        session.messages.extend(messages)
        session.status = "idle"
        session.step = 0

    if collaboration:
        session.state = AgentSessionStateJsonMap.model_validate(
            merge_collaboration_into_state(agent_session_state_as_dict(session.state), collaboration)
        )

    workspace = _resolve_agent_runtime_workspace(agent, session_id)
    session.workspace_dir = workspace
    session.status = "running"
    session.error_message = None
    session_store.save_session(session)
    return session, workspace


async def _execute_run_runtime(
    *,
    executor: Any,
    agent: AgentDefinition,
    session: AgentSession,
    workspace: str,
    session_store: Any,
    session_id: str,
    agent_id: str,
    idem_service: Optional[IdempotencyService],
    idem_record: Optional[Any],
) -> AgentSession:
    try:
        runtime = get_agent_runtime(executor)
        result_session = await runtime.run(agent, session, workspace=workspace)
        if idem_service and idem_record:
            idem_service.mark_succeeded(record_id=idem_record.id, response_ref=result_session.session_id)
        return result_session
    except asyncio.CancelledError:
        session.status = "error"
        session.error_message = REQUEST_CANCELLED_OR_TIMED_OUT_MESSAGE
        session_store.save_session(session)
        logger.warning(f"[Agent API] run cancelled session_id={session_id} agent_id={agent_id}")
        if idem_service and idem_record:
            idem_service.mark_failed(
                record_id=idem_record.id,
                error_message=REQUEST_CANCELLED_OR_TIMED_OUT_MESSAGE,
            )
        raise
    except Exception as e:
        session.status = "error"
        session.error_message = str(e)
        session_store.save_session(session)
        logger.exception(f"[Agent API] run failed session_id={session_id} agent_id={agent_id}: {e}")
        if idem_service and idem_record:
            idem_service.mark_failed(record_id=idem_record.id, error_message=str(e))
        raise


@router.post(
    "/{agent_id}/run",
    response_model=AgentSession,
    responses={
        404: {
            "model": APIErrorHttpEnvelope,
            "description": "Agent not found.",
        },
    },
)
async def run_agent(
    agent_id: str,
    req: RunAgentRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> AgentSession:
    registry = get_agent_registry()
    session_store = get_agent_session_store()
    executor = get_agent_executor()
    user_id = get_user_id(request)
    tenant_id = get_effective_tenant_id(request)
    idem_key = _extract_idempotency_key(request)
    idem_service = None
    idem_record = None
    
    agent = registry.get_agent(agent_id)
    if not agent:
        raise_api_error(
            status_code=404,
            code="agent_not_found",
            message=AGENT_NOT_FOUND_MESSAGE,
            details={"agent_id": agent_id},
        )
    assert agent is not None

    # 获取或创建会话
    session_id = req.session_id or f"asess_{uuid.uuid4().hex[:12]}"

    idem_service, idem_claim_or_session = _claim_run_idempotency(
        db=db,
        idem_key=idem_key,
        user_id=user_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        req=req,
        session_store=session_store,
    )
    if isinstance(idem_claim_or_session, AgentSession):
        return idem_claim_or_session
    idem_record = idem_claim_or_session

    collab = build_api_root_collaboration(
        agent_id,
        correlation_id=req.correlation_id,
        orchestrator_agent_id=req.orchestrator_agent_id,
        invoked_from=req.invoked_from.model_dump(mode="json") if req.invoked_from is not None else None,
    )
    session, workspace = _prepare_run_session(
        session_store=session_store,
        session_id=session_id,
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        messages=req.messages,
        agent=agent,
        collaboration=collab,
    )
    return await _execute_run_runtime(
        executor=executor,
        agent=agent,
        session=session,
        workspace=workspace,
        session_store=session_store,
        session_id=session_id,
        agent_id=agent_id,
        idem_service=idem_service,
        idem_record=idem_record,
    )


@router.post(
    "/{agent_id}/run/with-files",
    response_model=AgentSession,
    responses={
        404: {
            "model": APIErrorHttpEnvelope,
            "description": "Agent not found.",
        },
        413: {
            "model": APIErrorHttpEnvelope,
            "description": "Too many uploaded files.",
        },
    },
)
async def run_agent_with_files(
    request: Request,
    agent_id: str,
    messages: Annotated[str, Form(..., description="JSON array of Message objects")],
    session_id: Annotated[Optional[str], Form()] = None,
    files: Annotated[List[UploadFile], File()] = [],
    correlation_id: Annotated[Optional[str], Form()] = None,
    orchestrator_agent_id: Annotated[Optional[str], Form()] = None,
    invoked_from_json: Annotated[
        Optional[str],
        Form(description="Optional JSON object for invoked_from (same as POST /run body)"),
    ] = None,
) -> AgentSession:
    """Run agent with uploaded files. Files are saved to session workspace so file.read can access them."""
    registry = get_agent_registry()
    session_store = get_agent_session_store()
    executor = get_agent_executor()
    user_id = get_user_id(request)
    tenant_id = get_effective_tenant_id(request)

    agent = registry.get_agent(agent_id)
    if not agent:
        raise_api_error(
            status_code=404,
            code="agent_not_found",
            message=AGENT_NOT_FOUND_MESSAGE,
            details={"agent_id": agent_id},
        )
    assert agent is not None
    messages_objs = _parse_run_with_files_messages(messages)
    session_id = session_id or f"asess_{uuid.uuid4().hex[:12]}"
    workspace_dir = _get_agent_workspaces_root() / session_id
    workspace_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir_str = str(workspace_dir.resolve())
    saved_names: List[str] = []
    logger.info(f"[Agent API] run/with-files received files count={len(files)} session_id={session_id}")
    if len(files or []) > MAX_AGENT_UPLOAD_FILES:
        raise_api_error(
            status_code=413,
            code="agent_upload_too_many_files",
            message=f"too many uploaded files; max allowed is {MAX_AGENT_UPLOAD_FILES}",
        )
    if files:
        await _acquire_upload_slot()
        try:
            workspace_dir_str, saved_names = await _process_uploaded_files(session_id, files)
        finally:
            _upload_semaphore.release()
    _attach_upload_hint(messages_objs, saved_names, agent)
    inv = parse_invoked_from_form(invoked_from_json)
    collab = build_api_root_collaboration(
        agent_id,
        correlation_id=correlation_id,
        orchestrator_agent_id=orchestrator_agent_id,
        invoked_from=inv,
    )
    session = _prepare_run_with_files_session(
        session_store=session_store,
        session_id=session_id,
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        messages_objs=messages_objs,
        saved_names=saved_names,
        workspace_dir_str=workspace_dir_str,
        collaboration=collab,
    )

    try:
        runtime = get_agent_runtime(executor)
        result_session = await runtime.run(agent, session, workspace=workspace_dir_str)
        return result_session
    except asyncio.CancelledError:
        # Request cancelled/timed out by client/proxy: avoid leaving session in running forever.
        session.status = "error"
        session.error_message = REQUEST_CANCELLED_OR_TIMED_OUT_MESSAGE
        session_store.save_session(session)
        logger.warning(
            f"[Agent API] run/with-files cancelled session_id={session_id} agent_id={agent_id}"
        )
        raise
    except Exception as e:
        # 避免会话卡在 idle 且前端无反馈
        session.status = "error"
        session.error_message = str(e)
        session_store.save_session(session)
        logger.exception(f"[Agent API] run/with-files failed session_id={session_id} agent_id={agent_id}: {e}")
        raise

@session_router.get("/agent-sessions", response_model=AgentSessionsListEnvelope)
async def list_agent_sessions(
    request: Request, agent_id: Optional[str] = None, limit: int = 50
) -> AgentSessionsListEnvelope:
    user_id = get_user_id(request)
    tenant_id = get_effective_tenant_id(request)
    session_store = get_agent_session_store()
    sessions = session_store.list_sessions(
        user_id=user_id, limit=limit, agent_id=agent_id, tenant_id=tenant_id
    )
    return AgentSessionsListEnvelope(object="list", data=sessions)

@session_router.get(
    "/agent-sessions/{session_id}",
    response_model=AgentSession,
    responses={
        404: {
            "model": APIErrorHttpEnvelope,
            "description": "Session not found.",
        },
    },
)
async def get_agent_session(session_id: str, request: Request) -> AgentSession:
    session_store = get_agent_session_store()
    user_id = get_user_id(request)
    tenant_id = get_effective_tenant_id(request)
    session = session_store.get_session(session_id, user_id=user_id, tenant_id=tenant_id)
    if not session:
        raise_api_error(
            status_code=404,
            code="agent_session_not_found",
            message=SESSION_NOT_FOUND_MESSAGE,
            details={"session_id": session_id},
        )
    return session


def _agent_sse_data(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _build_agent_session_delta(session: AgentSession) -> Dict[str, Any]:
    """构造轻量增量状态，避免频繁下发完整 session。"""
    return {
        "schema_version": SSE_STATUS_DELTA_SCHEMA_VERSION,
        "session_id": session.session_id,
        "status": session.status,
        "step": session.step,
        "updated_at": session.updated_at,
        "error_message": session.error_message,
        "messages_count": len(session.messages or []),
    }


@session_router.get(
    "/agent-sessions/{session_id}/stream",
    responses={
        404: {
            "model": APIErrorHttpEnvelope,
            "description": "Session not found.",
        },
    },
)
async def stream_agent_session_status(
    session_id: str,
    request: Request,
    interval_ms: Annotated[int, Query(ge=300, le=5000, description="SSE 推送间隔（毫秒）")] = 900,
    compact: Annotated[bool, Query(description="true 时推送 status_delta（轻量增量）")] = False,
    lang: Annotated[
        Optional[str],
        Query(description="UI locale for SSE payloads (zh|en); EventSource cannot set Accept-Language"),
    ] = None,
) -> StreamingResponse:
    """SSE 推送 Agent Session 状态，前端可用来替代高频轮询。"""
    accept_sse = resolve_accept_language_for_sse(request, lang)
    sse_session_not_found_text = localize_error_message(
        code="agent_session_not_found",
        default_message=SESSION_NOT_FOUND_MESSAGE,
        accept_language=accept_sse,
    )
    session_store = get_agent_session_store()
    stream_uid = get_user_id(request)
    stream_tid = get_effective_tenant_id(request)
    if not session_store.get_session(session_id, user_id=stream_uid, tenant_id=stream_tid):
        raise_api_error(
            status_code=404,
            code="agent_session_not_found",
            message=SESSION_NOT_FOUND_MESSAGE,
            details={"session_id": session_id},
        )

    async def _event_stream() -> AsyncIterator[str]:
        last_hash: Optional[str] = None
        heartbeat_every_s = 15
        loop = asyncio.get_running_loop()
        heartbeat_at = loop.time()
        sleep_s = max(0.3, interval_ms / 1000.0)
        terminal_status = {"finished", "error", "idle"}

        while True:
            try:
                session = session_store.get_session(
                    session_id, user_id=stream_uid, tenant_id=stream_tid
                )
                if not session:
                    yield _agent_sse_data(
                        {
                            "type": "error",
                            "error_code": SSE_STREAM_RESOURCE_NOT_FOUND_ERROR_CODE,
                            "message": sse_session_not_found_text,
                        }
                    )
                    break

                payload = session.model_dump(mode="json")
                current_hash = hashlib.sha256(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest()
                now = loop.time()
                event: Optional[str] = None
                if current_hash != last_hash:
                    if compact:
                        event = _agent_sse_data({"type": "status_delta", "payload": _build_agent_session_delta(session)})
                    else:
                        event = _agent_sse_data({"type": "status", "payload": payload})
                    last_hash = current_hash
                    heartbeat_at = now
                elif (now - heartbeat_at) >= heartbeat_every_s:
                    event = _agent_sse_data({"type": "heartbeat"})
                    heartbeat_at = now

                if event is not None:
                    yield event

                if session.status in terminal_status:
                    yield _agent_sse_data({"type": "terminal", "state": session.status})
                    break

                await asyncio.sleep(sleep_s)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(f"[Agent API] session stream loop error: session_id={session_id} err={e}")
                yield _agent_sse_data(
                    {
                        "type": "error",
                        "error_code": SSE_STREAM_RUNTIME_ERROR_CODE,
                        "message": str(e),
                    }
                )
                await asyncio.sleep(min(2.0, sleep_s))

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@session_router.get(
    "/agent-sessions/{session_id}/files/{filename}",
    responses={
        400: {
            "model": APIErrorHttpEnvelope,
            "description": "Invalid workspace path.",
        },
        404: {
            "model": APIErrorHttpEnvelope,
            "description": "Session, workspace, or file not found.",
        },
    },
)
async def get_agent_session_file(
    session_id: str, filename: str, request: Request
) -> FileResponse:
    """Serve a file from the agent session workspace."""
    session_store = get_agent_session_store()
    session = session_store.get_session(
        session_id,
        user_id=get_user_id(request),
        tenant_id=get_effective_tenant_id(request),
    )
    if not session:
        raise_api_error(
            status_code=404,
            code="agent_session_not_found",
            message=SESSION_NOT_FOUND_MESSAGE,
            details={"session_id": session_id},
        )
    assert session is not None
    workspace = getattr(session, "workspace_dir", None)
    if not workspace:
        raise_api_error(
            status_code=404,
            code="agent_workspace_not_found",
            message="Workspace not found",
            details={"session_id": session_id},
        )
        raise AssertionError("unreachable")
    workspace = cast(str, workspace)
    try:
        resolved = resolve_in_workspace(workspace=workspace, path=filename, allowed_absolute_roots=None)
    except WorkspacePathError as e:
        raise_api_error(
            status_code=400,
            code="agent_invalid_workspace_path",
            message=str(e),
            details={"session_id": session_id},
        )
    if not resolved.exists() or not resolved.is_file():
        raise_api_error(
            status_code=404,
            code="agent_session_file_not_found",
            message="File not found",
            details={"session_id": session_id, "filename": filename},
        )
    return FileResponse(str(resolved))

class UpdateAgentSessionRequest(BaseModel):
    messages: Optional[List[Message]] = None
    status: Optional[str] = None

@session_router.patch(
    "/agent-sessions/{session_id}",
    response_model=AgentSession,
    responses={
        404: {
            "model": APIErrorHttpEnvelope,
            "description": "Session not found.",
        },
        500: {
            "model": APIErrorHttpEnvelope,
            "description": "Failed to persist session update.",
        },
    },
)
async def update_agent_session(
    session_id: str, req: UpdateAgentSessionRequest, request: Request
) -> AgentSession:
    session_store = get_agent_session_store()
    session = session_store.get_session(
        session_id,
        user_id=get_user_id(request),
        tenant_id=get_effective_tenant_id(request),
    )
    if not session:
        raise_api_error(
            status_code=404,
            code="agent_session_not_found",
            message=SESSION_NOT_FOUND_MESSAGE,
            details={"session_id": session_id},
        )
    assert session is not None
    
    if req.messages is not None:
        session.messages = req.messages
    if req.status is not None:
        session.status = req.status
    
    if session_store.save_session(session):
        return session
    raise_api_error(
        status_code=500,
        code="agent_session_save_failed",
        message="Failed to update session",
        details={"session_id": session_id},
    )

@session_router.get(
    "/agent-sessions/{session_id}/trace",
    response_model=AgentTraceEventsListEnvelope,
    responses={
        404: {
            "model": APIErrorHttpEnvelope,
            "description": "Session not found.",
        },
    },
)
async def get_agent_trace(session_id: str, request: Request) -> AgentTraceEventsListEnvelope:
    session_store = get_agent_session_store()
    session = session_store.get_session(
        session_id,
        user_id=get_user_id(request),
        tenant_id=get_effective_tenant_id(request),
    )
    if not session:
        raise_api_error(
            status_code=404,
            code="agent_session_not_found",
            message=SESSION_NOT_FOUND_MESSAGE,
            details={"session_id": session_id},
        )
    assert session is not None
    tid = (str(getattr(session, "tenant_id", None) or "").strip()) or DEFAULT_AGENT_SESSION_TENANT_ID
    trace_store = get_agent_trace_store()
    traces = trace_store.get_session_traces(session_id, tenant_id=tid)
    return AgentTraceEventsListEnvelope(object="list", data=traces)

@session_router.delete(
    "/agent-sessions/{session_id}/messages/{message_index}",
    response_model=AgentSession,
    responses={
        404: {
            "model": APIErrorHttpEnvelope,
            "description": "Session or message not found.",
        },
    },
)
async def delete_agent_session_message(
    session_id: str, message_index: int, request: Request
) -> AgentSession:
    """Delete a message from agent session by index"""
    session_store = get_agent_session_store()
    success = session_store.delete_message(
        session_id,
        message_index,
        user_id=get_user_id(request),
        tenant_id=get_effective_tenant_id(request),
    )
    if not success:
        raise_api_error(
            status_code=404,
            code="agent_session_message_not_found",
            message="Session or message not found",
            details={"session_id": session_id, "message_index": message_index},
        )
    # Return updated session
    updated_session = session_store.get_session(
        session_id,
        user_id=get_user_id(request),
        tenant_id=get_effective_tenant_id(request),
    )
    if not updated_session:
        raise_api_error(
            status_code=404,
            code="agent_session_not_found_after_delete",
            message="Session not found after deletion",
            details={"session_id": session_id},
        )
    return updated_session

@session_router.delete(
    "/agent-sessions/{session_id}",
    response_model=AgentSessionDeletedResponse,
    responses={
        404: {
            "model": APIErrorHttpEnvelope,
            "description": "Session not found or not owned by user.",
        },
    },
)
async def delete_agent_session(request: Request, session_id: str) -> AgentSessionDeletedResponse:
    """Delete an entire agent session"""
    user_id = get_user_id(request)
    tenant_id = get_effective_tenant_id(request)
    session_store = get_agent_session_store()
    success = session_store.delete_session(session_id, user_id, tenant_id=tenant_id)
    if not success:
        raise_api_error(
            status_code=404,
            code="agent_session_not_found",
            message=SESSION_NOT_FOUND_MESSAGE,
            details={"session_id": session_id},
        )
    return AgentSessionDeletedResponse(deleted=True, session_id=session_id)
