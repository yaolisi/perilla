import json
import asyncio
import re
import hashlib
from string import Formatter
import uuid
from pathlib import Path
from typing import Annotated, List, Optional, Dict, Any, cast

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.agent_runtime.definition import AgentDefinition, get_agent_registry
from core.agent_runtime.session import AgentSession, get_agent_session_store
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
from core.data.base import SessionLocal
from config.settings import settings
from api.errors import raise_api_error  # type: ignore[import-untyped]

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
    model_params: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Model parameters: intent_rules, skill_param_extractors, use_skill_discovery (bool), "
            "skill_discovery (object: tag_match_weight, min_semantic_similarity, min_hybrid_score for runtime discovery), "
            "plan_execution (object: max_parallel_in_group, default_timeout_seconds, default_max_retries, "
            "default_retry_interval_seconds, default_on_timeout_strategy for PlanBasedExecutor), etc."
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
    invoked_from: Optional[Dict[str, Any]] = None

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

@router.get("")
async def list_agents() -> Any:
    registry = get_agent_registry()
    return {"object": "list", "data": registry.list_agents()}

@router.post("")
async def create_agent(req: CreateAgentRequest) -> Any:
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
        for kb_id in rag_ids:
            if not kb_store.get_knowledge_base(kb_id):
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
    model_params = _apply_response_mode(req.model_params, req.response_mode, enabled_skills)
    _validate_execution_strategy_field(req.execution_strategy)
    _validate_kernel_opts_consistency(req.execution_strategy, req.max_parallel_nodes, model_params)

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
        model_params=model_params,
    )
    
    if registry.create_agent(agent):
        logger.info(f"[Agent API] Agent created successfully: {agent_id} - {req.name}")
        return agent
    raise_api_error(status_code=500, code="agent_create_failed", message="Failed to create agent")

@router.get("/{agent_id}")
async def get_agent(agent_id: str) -> Any:
    registry = get_agent_registry()
    agent = registry.get_agent(agent_id)
    if not agent:
        raise_api_error(
            status_code=404,
            code="agent_not_found",
            message=AGENT_NOT_FOUND_MESSAGE,
            details={"agent_id": agent_id},
        )
    return agent

@router.put("/{agent_id}")
async def update_agent(agent_id: str, req: CreateAgentRequest) -> Any:
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
    
    # 深度合并 model_params：保留原有字段，只更新请求中提供的字段
    if req.model_params is not None and req.model_params:
        # 请求中有 model_params，深度合并（保留原有字段）
        existing_params = existing_agent.model_params or {}
        model_params = {**existing_params, **req.model_params}
    else:
        # 请求中没有 model_params，保留原有的
        model_params = existing_agent.model_params or {}
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

    agent = AgentDefinition(
        agent_id=agent_id,
        name=req.name,
        description=req.description,
        model_id=req.model_id,
        system_prompt=req.system_prompt,
        enabled_skills=enabled_skills,
        tool_ids=[s[8:] for s in enabled_skills if s.startswith("builtin_")],
        rag_ids=req.rag_ids,
        max_steps=req.max_steps,
        temperature=req.temperature,
        execution_mode=req.execution_mode or "legacy",
        use_execution_kernel=req.use_execution_kernel,
        execution_strategy=exec_strategy,
        max_parallel_nodes=max_parallel,
        max_replan_count=req.max_replan_count if req.max_replan_count is not None else 3,
        on_failure_strategy=failure_strategy,
        replan_prompt=replan_prompt,
        model_params=model_params,
    )
    if registry.update_agent(agent):
        return agent
    raise_api_error(status_code=500, code="agent_update_failed", message="Failed to update agent")

@router.delete("/{agent_id}")
async def delete_agent(agent_id: str) -> Any:
    registry = get_agent_registry()
    if registry.delete_agent(agent_id):
        return {"status": "ok"}
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

    model_params = getattr(agent, "model_params", {}) or {}
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
    messages_objs: List[Message],
    saved_names: List[str],
    workspace_dir_str: str,
    collaboration: Optional[Dict[str, Any]] = None,
) -> AgentSession:
    session = cast(Optional[AgentSession], session_store.get_session(session_id))
    if not session:
        session = AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            messages=messages_objs,
            status="idle",
        )
    else:
        session.messages.extend(messages_objs)
        session.status = "idle"
        session.step = 0

    if saved_names:
        state = session.state or {}
        state["last_uploaded_images"] = saved_names
        state["last_uploaded_image"] = saved_names[0]
        session.state = state

    if collaboration:
        session.state = merge_collaboration_into_state(session.state, collaboration)

    session.workspace_dir = workspace_dir_str
    session.status = "running"
    session.error_message = None
    session_store.save_session(session)
    return cast(AgentSession, session)


def _claim_run_idempotency(
    *,
    idem_key: Optional[str],
    user_id: str,
    agent_id: str,
    req: RunAgentRequest,
    session_store: Any,
) -> tuple[Optional[Any], Optional[IdempotencyService], Optional[Any]]:
    if not idem_key:
        return None, None, None
    idem_db = SessionLocal()
    idem_service = IdempotencyService(idem_db)
    req_hash = _stable_request_hash(
        {
            "agent_id": agent_id,
            "session_id": req.session_id,
            "messages": [m.model_dump(mode="json") for m in (req.messages or [])],
            "correlation_id": req.correlation_id,
            "orchestrator_agent_id": req.orchestrator_agent_id,
            "invoked_from": req.invoked_from,
        }
    )
    claim = idem_service.claim(
        scope="agent_run",
        owner_id=user_id,
        key=idem_key,
        request_hash=req_hash,
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
            existing_session = session_store.get_session(claim.record.response_ref)
            if existing_session:
                return idem_db, idem_service, existing_session
        raise_api_error(
            status_code=409,
            code="idempotency_in_progress",
            message="Idempotent request is still processing; retry later",
            details={"scope": "agent_run"},
        )
    return idem_db, idem_service, idem_record


def _prepare_run_session(
    *,
    session_store: Any,
    session_id: str,
    agent_id: str,
    messages: List[Message],
    agent: AgentDefinition,
    collaboration: Optional[Dict[str, Any]] = None,
) -> tuple[AgentSession, str]:
    session = session_store.get_session(session_id)
    if not session:
        session = AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            messages=messages,
            status="idle",
        )
    else:
        session.messages.extend(messages)
        session.status = "idle"
        session.step = 0

    if collaboration:
        session.state = merge_collaboration_into_state(session.state, collaboration)

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


@router.post("/{agent_id}/run")
async def run_agent(agent_id: str, req: RunAgentRequest, request: Request) -> Any:
    registry = get_agent_registry()
    session_store = get_agent_session_store()
    executor = get_agent_executor()
    user_id = _get_user_id(request)
    idem_key = _extract_idempotency_key(request)
    idem_db = None
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
    
    try:
        # 获取或创建会话
        session_id = req.session_id or f"asess_{uuid.uuid4().hex[:12]}"

        idem_db, idem_service, idem_claim_or_session = _claim_run_idempotency(
            idem_key=idem_key,
            user_id=user_id,
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
            invoked_from=req.invoked_from,
        )
        session, workspace = _prepare_run_session(
            session_store=session_store,
            session_id=session_id,
            agent_id=agent_id,
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
    finally:
        if idem_db is not None:
            idem_db.close()


@router.post("/{agent_id}/run/with-files")
async def run_agent_with_files(
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
) -> Any:
    """Run agent with uploaded files. Files are saved to session workspace so file.read can access them."""
    registry = get_agent_registry()
    session_store = get_agent_session_store()
    executor = get_agent_executor()
    
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

@session_router.get("/agent-sessions")
async def list_agent_sessions(request: Request, agent_id: Optional[str] = None, limit: int = 50) -> Any:
    user_id = _get_user_id(request)
    session_store = get_agent_session_store()
    sessions = session_store.list_sessions(user_id=user_id, limit=limit, agent_id=agent_id)
    return {"object": "list", "data": sessions}

@session_router.get("/agent-sessions/{session_id}")
async def get_agent_session(session_id: str) -> Any:
    session_store = get_agent_session_store()
    session = session_store.get_session(session_id)
    if not session:
        raise_api_error(
            status_code=404,
            code="agent_session_not_found",
            message=SESSION_NOT_FOUND_MESSAGE,
            details={"session_id": session_id},
        )
    return session

@session_router.get("/agent-sessions/{session_id}/files/{filename}")
async def get_agent_session_file(session_id: str, filename: str) -> FileResponse:
    """Serve a file from the agent session workspace."""
    session_store = get_agent_session_store()
    session = session_store.get_session(session_id)
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

@session_router.patch("/agent-sessions/{session_id}")
async def update_agent_session(session_id: str, req: UpdateAgentSessionRequest) -> Any:
    session_store = get_agent_session_store()
    session = session_store.get_session(session_id)
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

@session_router.get("/agent-sessions/{session_id}/trace")
async def get_agent_trace(session_id: str) -> Any:
    trace_store = get_agent_trace_store()
    traces = trace_store.get_session_traces(session_id)
    # 将Pydantic模型转换为字典，确保可以正确序列化为JSON
    return {"object": "list", "data": [trace.model_dump() for trace in traces]}

@session_router.delete("/agent-sessions/{session_id}/messages/{message_index}")
async def delete_agent_session_message(session_id: str, message_index: int) -> Any:
    """Delete a message from agent session by index"""
    session_store = get_agent_session_store()
    success = session_store.delete_message(session_id, message_index)
    if not success:
        raise_api_error(
            status_code=404,
            code="agent_session_message_not_found",
            message="Session or message not found",
            details={"session_id": session_id, "message_index": message_index},
        )
    # Return updated session
    updated_session = session_store.get_session(session_id)
    if not updated_session:
        raise_api_error(
            status_code=404,
            code="agent_session_not_found_after_delete",
            message="Session not found after deletion",
            details={"session_id": session_id},
        )
    return updated_session

@session_router.delete("/agent-sessions/{session_id}")
async def delete_agent_session(request: Request, session_id: str) -> Any:
    """Delete an entire agent session"""
    user_id = _get_user_id(request)
    session_store = get_agent_session_store()
    success = session_store.delete_session(session_id, user_id)
    if not success:
        raise_api_error(
            status_code=404,
            code="agent_session_not_found",
            message=SESSION_NOT_FOUND_MESSAGE,
            details={"session_id": session_id},
        )
    return {"deleted": True, "session_id": session_id}
