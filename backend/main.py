"""
本地 AI 推理平台 - FastAPI 主入口
"""
import sys
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional
import atexit
import signal
from datetime import datetime, timedelta, timezone

# 添加后端目录到 Python 路径
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

# 尽早加载 .env：先加载 backend/.env，再加载项目根 .env，确保 TOOL_NET_WEB_ENABLED 等生效
try:
    from config.settings import bootstrap_env_files

    bootstrap_env_files(backend_dir)
except ImportError:
    pass

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
import asyncio

from log import logger
from config.settings import settings
from config.settings import apply_production_security_defaults
from config.settings import validate_production_security_guardrails
from api.chat import router as chat_router
from api.memory import router as memory_router
from api.sessions import router as sessions_router
from api.system import router as system_router
from api.knowledge import router as knowledge_router
from api.rag_trace import router as rag_trace_router
from api.agents import router as agents_router, session_router as agent_sessions_router
from api.tools import router as tools_router
from api.skills import router as skills_router
from api.vlm import router as vlm_router
from api.asr import router as asr_router
from api.images import router as images_router
from api.backup import router as backup_router
from api.model_backups import router as model_backups_router
from api.events import router as events_router
from api.workflows import router as workflows_router
from api.audit import router as audit_router
from api.errors import register_error_handlers
from core.security.deps import require_authenticated_platform_admin
from middleware.request_whitelist import enforce_request_body_whitelist

MODEL_NOT_FOUND_ERROR = "Model not found"
AdminRole = Annotated[Any, Depends(require_authenticated_platform_admin)]


def _apply_security_baseline() -> None:
    security_changes = apply_production_security_defaults(settings)
    if security_changes:
        logger.warning(
            "[SecurityBaseline] Auto-enabled production security defaults (debug=False): %s",
            ",".join(security_changes),
        )
    security_issues = validate_production_security_guardrails(settings)
    if security_issues:
        for issue in security_issues:
            logger.error("[SecurityBaseline] BLOCKED: %s", issue)
        if getattr(settings, "security_guardrails_strict", True):
            raise RuntimeError("Unsafe production security configuration. Refuse to start.")
        logger.warning(
            "[SecurityBaseline] security_guardrails_strict=False, continue startup with unsafe production settings."
        )
    if getattr(settings, "debug", True):
        return
    if (getattr(settings, "cors_allowed_origins", "") or "").strip() == "":
        logger.warning("[SecurityBaseline] cors_allowed_origins is empty in production; avoid wildcard CORS.")
    if getattr(settings, "file_read_allowed_roots", "").strip() == "/":
        logger.warning("[SecurityBaseline] file_read_allowed_roots='/' in production; narrow this allowlist.")
    if getattr(settings, "tool_net_http_enabled", False):
        logger.warning("[SecurityBaseline] tool_net_http_enabled=True in production; verify outbound policy.")
    if getattr(settings, "tool_net_web_enabled", False):
        logger.warning("[SecurityBaseline] tool_net_web_enabled=True in production; verify privacy policy.")


def _log_startup_banner() -> None:
    logger.info(f"Starting {settings.app_name} v{settings.version}...")
    logger.info("Log files will be kept for 30 days in logs/ directory")
    web_enabled = getattr(settings, "tool_net_web_enabled", True)
    logger.info(f"tool_net_web_enabled={web_enabled} (web.search: True=real, False=disabled)")
    if not web_enabled:
        logger.warning("Web search is DISABLED. Set TOOL_NET_WEB_ENABLED=true (or remove from .env) and restart for real search.")


def _initialize_database_tables() -> None:
    try:
        from core.data.base import Base, get_engine
        from core.data.models import (  # noqa: F401
            SystemSetting,
            Model,
            ModelConfig,
            Agent,
            Skill,
            AgentSession,
            AgentTrace,
            ImageGenerationJobORM,
            ImageGenerationWarmupORM,
        )
        from core.data.models.audit import AuditLogORM  # noqa: F401
        from core.data.models.workflow import WorkflowExecutionQueueORM  # noqa: F401
        from sqlalchemy import text

        engine = get_engine()
        Base.metadata.create_all(engine)
        with engine.connect() as conn:
            cols = {str(row[1]) for row in conn.execute(text("PRAGMA table_info(workflow_executions)")).fetchall()}
            if "queue_position" not in cols:
                conn.execute(text("ALTER TABLE workflow_executions ADD COLUMN queue_position INTEGER"))
            if "queued_at" not in cols:
                conn.execute(text("ALTER TABLE workflow_executions ADD COLUMN queued_at DATETIME"))
            if "wait_duration_ms" not in cols:
                conn.execute(text("ALTER TABLE workflow_executions ADD COLUMN wait_duration_ms INTEGER"))
            audit_cols = {str(row[1]) for row in conn.execute(text("PRAGMA table_info(audit_logs)")).fetchall()}
            if audit_cols and "tenant_id" not in audit_cols:
                conn.execute(text("ALTER TABLE audit_logs ADD COLUMN tenant_id VARCHAR(128) DEFAULT 'default'"))
            conn.commit()
        logger.info("Database tables initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database tables: {e}", exc_info=True)


def _recover_stale_running_sessions() -> None:
    try:
        from core.data.base import db_session
        from core.data.models.session import AgentSession as AgentSessionORM

        stale_seconds = max(60, int(getattr(settings, "agent_stale_running_session_seconds", 1800)))
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
        with db_session(retry_count=3, retry_delay=0.1) as db:
            stmt = (
                AgentSessionORM.__table__.update()
                .where(AgentSessionORM.status == "running", AgentSessionORM.updated_at < cutoff)
                .values(
                    status="error",
                    error_message="Recovered on startup: stale running session",
                    updated_at=datetime.now(timezone.utc),
                )
            )
            result = db.execute(stmt)
            recovered = int(getattr(result, "rowcount", 0) or 0)
        if recovered > 0:
            logger.warning(f"[Startup] Recovered {recovered} stale running agent session(s) (threshold={stale_seconds}s)")
        else:
            logger.info(f"[Startup] No stale running agent sessions (threshold={stale_seconds}s)")
    except Exception as e:
        logger.warning(f"[Startup] Failed to recover stale running sessions: {e}")


def _recover_stale_image_jobs() -> None:
    try:
        from core.data.base import db_session
        from core.data.models.image_generation import ImageGenerationJobORM

        with db_session(retry_count=3, retry_delay=0.1) as db:
            stmt = (
                ImageGenerationJobORM.__table__.update()
                .where(ImageGenerationJobORM.status.in_(["queued", "running"]))
                .values(
                    status="failed",
                    phase="recovered_on_startup",
                    error="Recovered on startup: stale queued/running image generation job",
                    finished_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            result = db.execute(stmt)
            recovered_image_jobs = int(getattr(result, "rowcount", 0) or 0)
        if recovered_image_jobs > 0:
            logger.warning(f"[Startup] Recovered {recovered_image_jobs} stale image generation job(s)")
        else:
            logger.info("[Startup] No stale image generation jobs")
    except Exception as e:
        logger.warning(f"[Startup] Failed to recover stale image generation jobs: {e}")


def _recover_expired_workflow_leases() -> None:
    try:
        from core.data.base import db_session
        from core.data.models.workflow import WorkflowExecutionQueueORM

        now = datetime.now(timezone.utc)
        with db_session(retry_count=3, retry_delay=0.1) as db:
            stmt = (
                WorkflowExecutionQueueORM.__table__.update()
                .where(
                    WorkflowExecutionQueueORM.status == "leased",
                    WorkflowExecutionQueueORM.lease_expire_at.isnot(None),
                    WorkflowExecutionQueueORM.lease_expire_at < now,
                )
                .values(status="queued", lease_owner=None, lease_expire_at=None, updated_at=now)
            )
            result = db.execute(stmt)
            recovered_leases = int(getattr(result, "rowcount", 0) or 0)
        if recovered_leases > 0:
            logger.warning(f"[Startup] Recovered {recovered_leases} expired workflow queue lease(s)")
        else:
            logger.info("[Startup] No expired workflow queue leases")
    except Exception as e:
        logger.warning(f"[Startup] Failed to recover workflow queue leases: {e}")


def _start_model_json_snapshot_task(app: FastAPI) -> None:
    if not getattr(settings, "model_json_backup_daily_enabled", False):
        return
    try:
        from core.backup.model_json.scheduler import run_daily_snapshot_loop

        app.state.model_json_snapshot_task = asyncio.create_task(run_daily_snapshot_loop())
    except Exception as e:
        logger.warning(f"[Startup] Model.json daily snapshot scheduler not started: {e}")


async def _shutdown_cleanup_async() -> int:
    logger.info("[Shutdown] Performing cleanup of loaded models...")
    unloaded_count = 0
    try:
        from core.models.registry import get_model_registry
        from core.runtimes.factory import get_runtime_factory

        registry = get_model_registry()
        factory = get_runtime_factory()
        unloaded_count = await _shutdown_unload_registered_models(registry, factory)
        await _shutdown_cleanup_cached_runtimes(factory)
    except Exception as e:
        logger.error(f"[Shutdown] Cleanup failed: {e}")
    logger.info(f"[Shutdown] Cleanup complete. Unloaded {unloaded_count} models.")
    return unloaded_count


async def _shutdown_unload_registered_models(registry: Any, factory: Any) -> int:
    unloaded_count = 0
    for model_descriptor in registry.list_models():
        try:
            if getattr(model_descriptor, "model_type", "").lower() == "perception":
                continue
            runtime = factory.get_runtime(model_descriptor.runtime)
            if await runtime.is_loaded(model_descriptor):
                logger.info(f"[Shutdown] Unloading model: {model_descriptor.id}")
                ok = await runtime.unload(model_descriptor)
                if ok:
                    unloaded_count += 1
                else:
                    logger.warning(f"[Shutdown] Failed to unload: {model_descriptor.id}")
        except Exception as e:
            logger.error(f"[Shutdown] Error unloading {model_descriptor.id}: {e}")
    return unloaded_count


async def _shutdown_cleanup_cached_runtimes(factory: Any) -> None:
    try:
        n_embed = factory.close_embedding_runtimes()
        if n_embed:
            logger.info(f"[Shutdown] Closed {n_embed} embedding runtime(s)")
    except Exception as e:
        logger.warning(f"[Shutdown] Failed to close embedding runtimes: {e}")
    try:
        n_vlm = await factory.unload_vlm_runtimes()
        if n_vlm:
            logger.info(f"[Shutdown] Unloaded {n_vlm} VLM runtime(s)")
    except Exception as e:
        logger.warning(f"[Shutdown] Failed to unload VLM runtimes: {e}")
    try:
        n_asr = await factory.unload_asr_runtimes()
        if n_asr:
            logger.info(f"[Shutdown] Unloaded {n_asr} ASR runtime(s)")
    except Exception as e:
        logger.warning(f"[Shutdown] Failed to unload ASR runtimes: {e}")
    try:
        n_perception = await factory.unload_perception_runtimes()
        if n_perception:
            logger.info(f"[Shutdown] Unloaded {n_perception} perception runtime(s)")
    except Exception as e:
        logger.warning(f"[Shutdown] Failed to unload perception runtimes: {e}")


def _register_shutdown_handlers() -> None:
    def cleanup_handler_sync() -> None:
        try:
            asyncio.run(_shutdown_cleanup_async())
        except Exception as e:
            logger.error(f"[Shutdown] atexit cleanup failed: {e}")

    atexit.register(cleanup_handler_sync)

    prev_signal_handlers: Dict[int, Any] = {}

    def _exit_request_handler(signum: int, frame: Any) -> None:
        try:
            sig_name = signal.Signals(signum).name
        except Exception:
            sig_name = str(signum)
        logger.info(f"[Shutdown] Received signal {sig_name} ({signum}); delegating to previous signal handler.")
        prev = prev_signal_handlers.get(signum)
        if callable(prev):
            prev(signum, frame)
            return
        if prev == signal.SIG_IGN:
            return
        raise KeyboardInterrupt

    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            prev_signal_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, _exit_request_handler)
    except Exception:
        pass


async def _load_plugins_and_skills() -> None:
    from core.models.registry import get_model_registry
    from core.plugins.registry import get_plugin_registry

    registry = get_model_registry()
    plugin_registry = get_plugin_registry()
    try:
        from api.chat import memory_store
        await plugin_registry.load_builtin_plugins(logger=logger, memory=memory_store, model_registry=registry)
        logger.info(f"[Main] Loaded {len(plugin_registry.list())} plugins")

        from core.plugins.builtin.tools import bootstrap_tools
        bootstrap_tools()
        logger.info("[Main] Registered built-in tools")

        from core.skills.registry import SkillRegistry
        from core.skills.service import bootstrap_builtin_skills
        from core.skills.discovery import get_discovery_engine

        SkillRegistry.load()
        logger.info("[Main] Loaded Skill registry")
        n_builtin = bootstrap_builtin_skills()
        if n_builtin:
            logger.info(f"[Main] Registered {n_builtin} built-in skills from tools")
        try:
            engine = get_discovery_engine()
            engine.bind_registry(SkillRegistry)
            n_indexed = engine.build_index()
            logger.info(f"[Main] Skill discovery index built ({n_indexed} skills)")
        except Exception as e:
            logger.warning(f"[Main] Skill discovery index build failed: {e}")
    except Exception as e:
        logger.error(f"Plugin initialization failed: {e}")


async def _startup_scan_models() -> None:
    from core.models.scanner.ollama import OllamaScanner
    from core.models.scanner.lmstudio import LMStudioScanner
    from core.models.scanner.local import LocalScanner

    try:
        await OllamaScanner().scan()
    except Exception as e:
        logger.error(f"Ollama scan failed: {e}")
    try:
        await LMStudioScanner().scan()
    except Exception as e:
        logger.debug(f"LM Studio scan failed: {e}")
    try:
        await LocalScanner().scan()
    except Exception as e:
        logger.error(f"Local model scan failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _apply_security_baseline()
    _log_startup_banner()
    _initialize_database_tables()
    _recover_stale_running_sessions()
    _recover_stale_image_jobs()
    _recover_expired_workflow_leases()
    _start_model_json_snapshot_task(app)
    _register_shutdown_handlers()
    await _load_plugins_and_skills()
    await _startup_scan_models()
    try:
        yield
    finally:
        await _shutdown_cleanup_async()

# 创建应用
app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="本地 AI 推理网关",
    lifespan=lifespan,
    dependencies=[Depends(enforce_request_body_whitelist)],
)
register_error_handlers(app)

# 中间件顺序：先注册的更靠近应用内核；外层后注册，请求先经过外层。
# 期望链路：Audit(外) → CORS → RBAC 强制 → UserContext → RBAC 角色 → RateLimit → RequestTrace(内)
from middleware.user_context import UserContextMiddleware
from middleware.request_trace import RequestTraceMiddleware
from middleware.rate_limit import InMemoryRateLimitMiddleware
from middleware.rbac_context import RBACContextMiddleware
from middleware.rbac_enforcement import RBACEnforcementMiddleware
from middleware.audit_log import AuditLogMiddleware
from middleware.tenant_context import TenantContextMiddleware
from middleware.tenant_key_binding import TenantApiKeyBindingMiddleware
from middleware.api_key_scope import ApiKeyScopeMiddleware
from middleware.csrf_protection import CSRFMiddleware
from middleware.sensitive_data_redaction import SensitiveDataRedactionMiddleware

_api_key_hdr = getattr(settings, "api_rate_limit_api_key_header", "X-Api-Key")

if getattr(settings, "request_trace_enabled", True):
    app.add_middleware(
        RequestTraceMiddleware,
        header_name=getattr(settings, "request_trace_header_name", "X-Request-Id"),
    )

if getattr(settings, "api_rate_limit_enabled", True) and int(getattr(settings, "api_rate_limit_requests", 0)) > 0:
    app.add_middleware(
        InMemoryRateLimitMiddleware,
        requests_per_window=int(getattr(settings, "api_rate_limit_requests", 120)),
        window_seconds=int(getattr(settings, "api_rate_limit_window_seconds", 60)),
        api_key_header=_api_key_hdr,
        max_concurrent_per_user=int(getattr(settings, "api_rate_limit_user_max_concurrent_requests", 5)),
    )

app.add_middleware(TenantContextMiddleware)
app.add_middleware(TenantApiKeyBindingMiddleware)
app.add_middleware(ApiKeyScopeMiddleware)
app.add_middleware(CSRFMiddleware)

if getattr(settings, "rbac_enabled", False):
    app.add_middleware(RBACContextMiddleware, api_key_header=_api_key_hdr)

app.add_middleware(UserContextMiddleware)
app.add_middleware(SensitiveDataRedactionMiddleware)

if getattr(settings, "rbac_enabled", False) and getattr(settings, "rbac_enforcement", False):
    app.add_middleware(RBACEnforcementMiddleware)

if getattr(settings, "audit_log_enabled", False):
    app.add_middleware(AuditLogMiddleware)

# CORS 中间件配置（按顺序要求放在最后）
_cors_origins = [x.strip() for x in (getattr(settings, "cors_allowed_origins", "") or "").split(",") if x.strip()]
_cors_allow_credentials = bool(_cors_origins) and "*" not in _cors_origins
if getattr(settings, "response_gzip_enabled", True):
    app.add_middleware(
        GZipMiddleware,
        minimum_size=int(getattr(settings, "response_gzip_minimum_size", 256) or 256),
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["http://localhost", "http://127.0.0.1"],
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Session-Id",
        "X-Request-Id",
        "X-Trace-Id",
        "X-Response-Time-Ms",
        "X-CSRF-Token",
        "Content-Encoding",
    ],
)

# 包含路由
app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(sessions_router)
app.include_router(system_router)
app.include_router(knowledge_router)
app.include_router(rag_trace_router)
app.include_router(agents_router)
app.include_router(agent_sessions_router)
app.include_router(tools_router)
app.include_router(skills_router)
app.include_router(vlm_router)
app.include_router(asr_router)
app.include_router(images_router)
app.include_router(backup_router)
app.include_router(model_backups_router)
app.include_router(events_router)
app.include_router(workflows_router)
app.include_router(audit_router)


@app.get("/")
async def root():
    """根端点"""
    return {
        "message": "Welcome to OpenVitamin大模型与智能体应用平台",
        "version": settings.version,
    }


@app.get("/api/health")
async def health_check(request: Request):
    """健康检查端点"""
    return {
        "status": "healthy",
        "version": settings.version,
        "request_id": getattr(request.state, "request_id", None),
        "trace_id": getattr(request.state, "trace_id", None),
    }


@app.get("/api/health/live")
async def health_live():
    """存活探针：进程是否在线。"""
    return {"status": "alive", "service": settings.app_name, "version": settings.version}


@app.get("/api/health/ready")
async def health_ready():
    """就绪探针：关键依赖（数据库）是否可用。"""
    try:
        from core.data.base import get_engine
        from sqlalchemy import text

        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok", "version": settings.version}
    except Exception as e:
        logger.warning(f"[HealthReady] dependency check failed: {e}")
        return {"status": "not_ready", "database": "error", "detail": str(e), "version": settings.version}


class CreateModelRequest(BaseModel):
    id: str
    name: str
    provider: str
    provider_model_id: str
    runtime: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    description: Optional[str] = None


SENSITIVE_METADATA_KEYS = {"api_key", "token", "secret", "password"}


def _sanitize_metadata(metadata: Optional[dict]) -> dict:
    out = {}
    for k, v in (metadata or {}).items():
        if str(k).lower() in SENSITIVE_METADATA_KEYS:
            out[k] = "***"
        else:
            out[k] = v
    return out


async def _fill_model_status(model_item: Dict[str, Any], reg: Any, factory: Any) -> None:
    model_item["status"] = "detached"
    model_id = str(model_item.get("id", ""))
    if not model_id:
        return
    desc = reg.get_model(model_id)
    if not desc:
        return

    descriptor_type = getattr(desc, "model_type", "").lower()
    if descriptor_type == "perception":
        if factory.is_perception_loaded(desc.id):
            model_item["status"] = "active"
        return
    if descriptor_type == "image_generation":
        if factory.is_image_generation_loaded(desc.id):
            model_item["status"] = "active"
        return

    runtime = factory.get_runtime(desc.runtime)
    if await runtime.is_loaded(desc):
        model_item["status"] = "active"
        if desc.runtime == "llama.cpp":
            model_item["device"] = "GPU:0"  # 暂时硬编码为 GPU:0，未来可从 runtime 获取


async def _scan_model_count(scanner_cls: Any, key: str, results: Dict[str, int], *, log_level: str = "error") -> List[Any]:
    try:
        scanner = scanner_cls()
        models = await scanner.scan()
        results[key] = len(models)
        return list(models)
    except Exception as e:
        if log_level == "debug":
            logger.debug(f"{key} scan failed: {e}")
        else:
            logger.error(f"{key} scan failed: {e}")
        return []


async def _unload_model_for_rescan(factory: Any, desc: Any) -> None:
    descriptor_type = getattr(desc, "model_type", "").lower()
    if descriptor_type == "perception":
        factory.unload_perception_runtime(desc.id)
        return
    if descriptor_type == "image_generation":
        await factory.unload_image_generation_runtime(desc.id)
        return
    runtime = factory.get_runtime(desc.runtime)
    if await runtime.is_loaded(desc):
        await runtime.unload(desc)


async def _remove_outdated_local_models(local_models: List[Any], results: Dict[str, int]) -> None:
    from core.models.registry import get_model_registry
    from core.runtimes.factory import get_runtime_factory

    reg = get_model_registry()
    factory = get_runtime_factory()
    scanned_ids = {d.id for d in local_models}
    existing_local = reg.list_models(provider="local")

    for desc in existing_local:
        if desc.id in scanned_ids:
            continue
        try:
            try:
                await _unload_model_for_rescan(factory, desc)
            except Exception:
                pass
            reg.delete_model(desc.id)
            results["removed"] += 1
            logger.info(f"[Scan] Removed outdated local model: {desc.id}")
        except Exception as e:
            logger.warning(f"[Scan] Failed to remove {desc.id}: {e}")

@app.post("/api/models")
async def register_model(req: CreateModelRequest, _role: AdminRole = None):
    """手动注册模型（如云端 OpenAI, DeepSeek 等）"""
    from core.models.registry import get_model_registry
    from core.models.descriptor import ModelDescriptor
    
    reg = get_model_registry()
    
    descriptor = ModelDescriptor(
        id=req.id,
        name=req.name,
        provider=req.provider,
        provider_model_id=req.provider_model_id,
        runtime=req.runtime,
        base_url=req.base_url,
        metadata={"api_key": req.api_key} if req.api_key else {},
        description=req.description,
        source="Cloud API",
        family=req.provider
    )
    
    reg.upsert_model(descriptor)
    return {"success": True, "id": descriptor.id}

@app.get("/api/models")
async def list_models(model_type: Optional[str] = None):
    """列出可用模型"""
    from core.agents.router import get_router
    from core.runtimes.factory import get_runtime_factory
    from core.models.registry import get_model_registry
    
    router = get_router()
    models = await router.list_models(model_type=model_type)
    factory = get_runtime_factory()
    reg = get_model_registry()
    
    # 注入实时状态
    for m in models:
        await _fill_model_status(m, reg, factory)
            
    return {
        "object": "list",
        "data": models,
    }


@app.post("/api/models/scan")
async def scan_models(_role: AdminRole = None):
    """手动扫描模型，同步本地模型状态（移除磁盘上已不存在的本地模型）"""
    from core.models.scanner.ollama import OllamaScanner
    from core.models.scanner.lmstudio import LMStudioScanner
    from core.models.scanner.local import LocalScanner
    from core.models.registry import get_model_registry
    from core.runtimes.factory import get_runtime_factory
    
    results = {"ollama": 0, "lmstudio": 0, "local": 0, "removed": 0}
    
    await _scan_model_count(OllamaScanner, "ollama", results)
    await _scan_model_count(LMStudioScanner, "lmstudio", results, log_level="debug")
    local_models = await _scan_model_count(LocalScanner, "local", results)
    if local_models:
        await _remove_outdated_local_models(local_models, results)
        
    return {"success": True, "results": results}


@app.post("/api/models/{model_id}/load")
async def load_model(model_id: str, _role: AdminRole = None):
    """手动加载模型"""
    from core.models.registry import get_model_registry
    from core.runtimes.factory import get_runtime_factory
    
    reg = get_model_registry()
    desc = reg.get_model(model_id)
    if not desc:
        return {"error": MODEL_NOT_FOUND_ERROR}, 404
        
    factory = get_runtime_factory()
    
    # Perception 模型：通过 Factory 创建并缓存 runtime
    model_type = getattr(desc, "model_type", "").lower()
    if model_type == "perception":
        try:
            factory.create_perception_runtime(desc)
            success = True
        except Exception as e:
            logger.exception("Failed to load perception model")
            return {"error": str(e)}, 500
    elif model_type == "image_generation":
        try:
            runtime = factory.create_image_generation_runtime(desc)
            success = await runtime.load()
        except Exception as e:
            logger.exception("Failed to load image generation model")
            return {"error": str(e)}, 500
    else:
        runtime = factory.get_runtime(desc.runtime)
        success = await runtime.load(desc)
    
    res = {"success": success, "status": "active" if success else "detached"}
    if success and desc.runtime == "llama.cpp":
        res["device"] = "GPU:0"
    
    return res


@app.post("/api/models/{model_id}/unload")
async def unload_model(model_id: str, _role: AdminRole = None):
    """手动卸载模型"""
    from core.models.registry import get_model_registry
    from core.runtimes.factory import get_runtime_factory
    
    reg = get_model_registry()
    desc = reg.get_model(model_id)
    if not desc:
        return {"error": MODEL_NOT_FOUND_ERROR}, 404
        
    factory = get_runtime_factory()
    success = await factory.unload_model(desc.id)
    return {"success": success, "status": "detached"}


def _estimate_model_size_gb(size_text: Optional[str]) -> float:
    import re

    if not size_text:
        return 0.0
    match = re.search(r"(\d+(\.\d+)?)\s*(GB|MB)", size_text)
    if not match:
        return 0.0
    value = float(match.group(1))
    unit = match.group(3)
    return value if unit == "GB" else value / 1024


def _build_vram_warning(vram_available: float, estimated_total_gb: float) -> Optional[str]:
    if vram_available > estimated_total_gb:
        return None
    if vram_available + 2 > estimated_total_gb:
        return (
            f"VRAM is tight ({round(vram_available, 1)}GB available). "
            "The model might be slow or fail to load."
        )
    return (
        f"Insufficient VRAM! Estimated {round(estimated_total_gb, 1)}GB required, "
        f"but only {round(vram_available, 1)}GB available."
    )


def _resolve_local_model_dir(desc: Any) -> Optional[str]:
    import os

    if not desc or desc.provider != "local":
        return None
    model_path_val = desc.metadata.get("model_path") or desc.metadata.get("path")
    if not model_path_val:
        return None
    return os.path.dirname(model_path_val)


def _is_browse_path_allowed(model_dir: str, browse_dir: str) -> bool:
    import os

    model_dir_real = os.path.realpath(model_dir)
    browse_real = os.path.realpath(browse_dir)
    return browse_real.startswith(model_dir_real) or model_dir_real.startswith(browse_real)


def _list_browse_entries(browse_dir: str) -> Dict[str, List[str]]:
    import os

    entries = sorted(os.listdir(browse_dir))
    dirs: List[str] = []
    files: List[str] = []
    for name in entries:
        if name.startswith("."):
            continue
        full = os.path.join(browse_dir, name)
        if os.path.isdir(full):
            dirs.append(name)
        else:
            files.append(name)
    return {"dirs": sorted(dirs), "files": sorted(files)}


async def _try_read_local_manifest(desc: Any, model_id: str) -> Optional[Dict[str, Any]]:
    import os
    import json
    import aiofiles  # type: ignore[import-untyped]

    model_dir = _resolve_local_model_dir(desc)
    if not model_dir:
        return None

    manifest_path = os.path.join(model_dir, "model.json")
    if not os.path.exists(manifest_path):
        return None
    try:
        async with aiofiles.open(manifest_path, "r", encoding="utf-8") as f:
            content = await f.read()
        manifest = json.loads(content)
        if not isinstance(manifest, dict):
            return None
        manifest["metadata"] = _sanitize_metadata(manifest.get("metadata"))
        rel_path = manifest.get("path", "")
        if rel_path and not os.path.isabs(rel_path):
            abs_path = os.path.normpath(os.path.join(model_dir, rel_path))
            manifest = {**manifest, "path": abs_path}
        return manifest
    except Exception as e:
        logger.warning(f"Failed to read manifest for {model_id}: {e}")
        return None


def _build_default_manifest(desc: Any) -> Dict[str, Any]:
    return {
        "model_id": desc.id,
        "name": desc.name,
        "model_type": getattr(desc, "model_type", None) or desc.metadata.get("modality", "llm"),
        "runtime": desc.runtime,
        "format": desc.metadata.get("format", "gguf"),
        "path": desc.metadata.get("model_path") or desc.metadata.get("path", ""),
        "capabilities": getattr(desc, "capabilities", None) or desc.metadata.get("capabilities", []),
        "quantization": desc.metadata.get("quantization", ""),
        "description": desc.description or "",
        "metadata": _sanitize_metadata(desc.metadata),
    }


@app.get("/api/models/{model_id}/safety_check")
async def model_safety_check(model_id: str):
    """检查模型加载的 VRAM 安全性"""
    from core.models.registry import get_model_registry
    from api.system import get_gpu_metrics
    
    reg = get_model_registry()
    desc = reg.get_model(model_id)
    if not desc:
        return {"error": MODEL_NOT_FOUND_ERROR}, 404
        
    # 获取当前 GPU 状态
    gpu = get_gpu_metrics()
    vram_total = gpu["vram_total"]
    vram_used = gpu["vram_used"]
    vram_available = max(0, vram_total - vram_used)
    
    # 估算模型所需 VRAM
    # 基础: 模型文件大小
    size_gb = _estimate_model_size_gb(desc.size)
            
    # 上下文开销 (估算: 8k 约 0.5GB, 32k 约 2GB)
    ctx_kb = desc.context_length or 4096
    ctx_overhead_gb = (ctx_kb / 1024 / 8) * 0.5 
    
    estimated_total_gb = size_gb + ctx_overhead_gb
    
    # 安全检查
    is_safe = vram_available > estimated_total_gb
    
    # 如果是 Ollama，可能已经加载了，或者 Ollama 会自动调度
    if desc.provider == "ollama":
        # Ollama 比较智能，通常不需要严格限制，但给个提示
        return {
            "is_safe": True,
            "estimated_vram_gb": round(estimated_total_gb, 2),
            "available_vram_gb": round(vram_available, 2),
            "message": "Ollama handles memory management automatically.",
            "warning": None if vram_available > size_gb else "Ollama may use system RAM if VRAM is low."
        }
        
    warning = _build_vram_warning(vram_available, estimated_total_gb)
            
    return {
        "is_safe": is_safe,
        "estimated_vram_gb": round(estimated_total_gb, 2),
        "available_vram_gb": round(vram_available, 2),
        "message": "Safe to load" if is_safe else "Low VRAM warning",
        "warning": warning
    }


@app.patch("/api/models/{model_id}")
async def update_model(model_id: str, data: dict, _role: AdminRole = None):
    """更新模型元数据/配置"""
    from core.models.registry import get_model_registry
    
    reg = get_model_registry()
    desc = reg.get_model(model_id)
    if not desc:
        return {"error": MODEL_NOT_FOUND_ERROR}, 404
        
    # 更新字段
    if "name" in data:
        desc.name = data["name"]
    if "provider_model_id" in data:
        desc.provider_model_id = data["provider_model_id"]
    if "context_length" in data:
        desc.context_length = data["context_length"]
    if "description" in data:
        desc.description = data["description"]
    if "base_url" in data:
        desc.base_url = data["base_url"]
    if "metadata" in data:
        desc.metadata.update(data["metadata"])
        
    reg.upsert_model(desc)
    payload = desc.model_dump()
    payload["metadata"] = _sanitize_metadata(payload.get("metadata"))
    return {"success": True, "data": payload}


@app.get("/api/models/{model_id}/chat-params")
async def get_model_chat_params(model_id: str):
    """获取模型的聊天参数"""
    from core.models.registry import get_model_registry
    reg = get_model_registry()
    params = reg.get_model_chat_params(model_id)
    return {"success": True, "data": params}


@app.post("/api/models/{model_id}/chat-params")
async def save_model_chat_params(model_id: str, data: dict, _role: AdminRole = None):
    """保存模型的聊天参数"""
    from core.models.registry import get_model_registry
    logger.info(f"Updating chat parameters for model {model_id}: {data}")
    reg = get_model_registry()
    reg.save_model_chat_params(model_id, data)
    return {"success": True}


@app.get("/api/models/{model_id}/browse")
async def browse_model_dir(model_id: str, dir: str = ""):
    """列出目录内容，用于模型路径选择。dir 为空时使用模型所在目录。"""
    from core.models.registry import get_model_registry
    import os

    reg = get_model_registry()
    desc = reg.get_model(model_id)
    model_dir = _resolve_local_model_dir(desc)
    if not model_dir:
        return {"error": "Model not found or not local"}, 404

    browse_dir = os.path.normpath(os.path.join(model_dir, dir)) if dir else model_dir

    if not os.path.isdir(browse_dir):
        return {"error": "Directory not found", "path": browse_dir}, 404

    # 安全检查：仅允许模型目录及其父级（便于选择模型文件）
    if not _is_browse_path_allowed(model_dir, browse_dir):
        return {"error": "Access denied"}, 403

    try:
        entry_map = _list_browse_entries(browse_dir)
        parent_dir = os.path.dirname(browse_dir) if browse_dir != model_dir else None
        return {
            "path": browse_dir,
            "dirs": entry_map["dirs"],
            "files": entry_map["files"],
            "parent": parent_dir,
            "model_dir": model_dir,
        }
    except PermissionError:
        return {"error": "Permission denied"}, 403
    except Exception as e:
        logger.warning(f"Browse failed: {e}")
        return {"error": str(e)}, 500


@app.get("/api/models/{model_id}/manifest")
async def get_model_manifest(model_id: str):
    """获取模型清单配置"""
    from core.models.registry import get_model_registry
    reg = get_model_registry()
    desc = reg.get_model(model_id)
    if not desc:
        return {"error": MODEL_NOT_FOUND_ERROR}, 404

    manifest = await _try_read_local_manifest(desc, model_id)
    if manifest is not None:
        return manifest
    return _build_default_manifest(desc)


@app.put("/api/models/{model_id}/manifest")
async def update_model_manifest(model_id: str, data: dict, _role: AdminRole = None):
    """更新模型清单配置"""
    from core.models.registry import get_model_registry
    import os
    import json
    import aiofiles  # type: ignore[import-untyped]
    
    reg = get_model_registry()
    desc = reg.get_model(model_id)
    if not desc:
        return {"error": MODEL_NOT_FOUND_ERROR}, 404
    
    # 对于本地模型，更新 model.json
    model_path_val = desc.metadata.get("model_path") or desc.metadata.get("path")
    if desc.provider == "local" and model_path_val:
        model_dir = os.path.dirname(model_path_val)
        manifest_path = os.path.join(model_dir, "model.json")
        
        try:
            # 保存前将绝对路径转为相对路径（model.json 约定使用相对路径）
            save_data = dict(data)
            path_val = save_data.get("path", "")
            if path_val and os.path.isabs(path_val):
                try:
                    rel = os.path.relpath(path_val, model_dir)
                    if not rel.startswith(".."):
                        save_data["path"] = rel
                except ValueError:
                    pass
            serialized = json.dumps(save_data, indent=2, ensure_ascii=False)
            async with aiofiles.open(manifest_path, "w", encoding="utf-8") as f:
                await f.write(serialized)
            logger.info(f"Updated manifest for {model_id} at {manifest_path}")
        except Exception as e:
            logger.error(f"Failed to write manifest for {model_id}: {e}")
            return {"error": f"Failed to save manifest: {str(e)}"}, 500
    
    return {"success": True}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
