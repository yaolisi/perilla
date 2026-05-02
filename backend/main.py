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

import time
import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from middleware.trusted_host import SelectiveTrustedHostMiddleware, trusted_host_exempt_path_predicate
from pydantic import BaseModel
from contextlib import asynccontextmanager
import asyncio
import os

from log import logger, setup_logger
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
from api.skill_discovery import router as skill_discovery_router
from api.vlm import router as vlm_router
from api.asr import router as asr_router
from api.images import router as images_router
from api.backup import router as backup_router
from api.model_backups import router as model_backups_router
from api.events import router as events_router
from api.collaboration import router as collaboration_router
from api.workflows import router as workflows_router
from api.audit import router as audit_router
from api.mcp import router as mcp_router
from api.errors import register_error_handlers
from core.security.deps import require_authenticated_platform_admin
from middleware.request_whitelist import enforce_request_body_whitelist

MODEL_NOT_FOUND_ERROR = "Model not found"
AdminRole = Annotated[Any, Depends(require_authenticated_platform_admin)]


def _configure_platform_logging() -> None:
    setup_logger(
        name="ai_platform",
        backup_count=max(1, int(getattr(settings, "log_backup_count", 30) or 30)),
        debug=bool(getattr(settings, "debug", True)),
        level=(getattr(settings, "log_level", "") or "").strip() or None,
        format_type=(getattr(settings, "log_format", "text") or "text").strip().lower(),
    )
    logger.info(
        "[Logging] configured format=%s level=%s backup_count=%s",
        (getattr(settings, "log_format", "text") or "text").strip().lower(),
        (getattr(settings, "log_level", "") or "auto").strip() or "auto",
        max(1, int(getattr(settings, "log_backup_count", 30) or 30)),
    )


def _configure_prometheus_metrics(app: FastAPI) -> None:
    if not bool(getattr(settings, "prometheus_enabled", True)):
        logger.info("[Metrics] Prometheus disabled by settings")
        return
    try:
        from middleware.ops_paths import get_prometheus_metrics_path
        from prometheus_fastapi_instrumentator import Instrumentator

        endpoint = get_prometheus_metrics_path()
        # 与 ops_paths 一致：探针 + 指标端点不进入默认 http 请求指标，避免 scrape/探针刷高基线
        excluded = list(
            dict.fromkeys(
                (
                    "/api/health",
                    "/api/health/live",
                    "/api/health/ready",
                    endpoint,
                )
            )
        )
        Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            excluded_handlers=excluded,
        ).instrument(app).expose(app, endpoint=endpoint, include_in_schema=False)
        logger.info("[Metrics] Prometheus endpoint enabled at %s", endpoint)
    except Exception as e:
        logger.warning("[Metrics] Prometheus setup skipped: %s", e)


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
        strict = getattr(settings, "security_guardrails_strict", True)
        debug_mode = getattr(settings, "debug", True)
        if strict and not debug_mode:
            raise RuntimeError("Unsafe production security configuration. Refuse to start.")
        if not strict:
            logger.warning(
                "[SecurityBaseline] security_guardrails_strict=False, continue startup with unsafe production settings."
            )
        elif debug_mode:
            logger.warning(
                "[SecurityBaseline] debug=True: guardrail violations logged above; startup continues "
                "(set DEBUG=false for strict refusal)."
            )
    if getattr(settings, "debug", True):
        return
    _log_production_operational_warnings()


def _log_production_operational_warnings() -> None:
    """生产环境（debug=False）下的运维建议；不阻断启动。由 _apply_security_baseline 在 return 前调用。"""
    if (getattr(settings, "cors_allowed_origins", "") or "").strip() == "":
        logger.warning("[SecurityBaseline] cors_allowed_origins is empty in production; avoid wildcard CORS.")
    _cors_parts = [x.strip() for x in (getattr(settings, "cors_allowed_origins", "") or "").split(",") if x.strip()]
    if any(p == "*" for p in _cors_parts):
        logger.warning(
            "[SecurityBaseline] CORS includes origin '*': allow_credentials is off in the gateway; "
            "for browser + cookies use explicit https://... origins, not a wildcard."
        )
    if getattr(settings, "file_read_allowed_roots", "").strip() == "/":
        logger.warning("[SecurityBaseline] file_read_allowed_roots='/' in production; narrow this allowlist.")
    if getattr(settings, "tool_net_http_enabled", False):
        logger.warning("[SecurityBaseline] tool_net_http_enabled=True in production; verify outbound policy.")
    if getattr(settings, "tool_net_web_enabled", False):
        logger.warning("[SecurityBaseline] tool_net_web_enabled=True in production; verify privacy policy.")
    if (
        getattr(settings, "api_rate_limit_enabled", True)
        and int(getattr(settings, "api_rate_limit_requests", 0) or 0) > 0
        and not (getattr(settings, "api_rate_limit_redis_url", "") or "").strip()
    ):
        logger.warning(
            "[SecurityBaseline] api_rate_limit_redis_url is empty while API rate limiting is enabled: "
            "limits apply per process only; set API_RATE_LIMIT_REDIS_URL for consistent enforcement across replicas."
        )
    _csrf_secure_effective = bool(
        getattr(settings, "csrf_cookie_secure", False)
        or not bool(getattr(settings, "debug", True))
    )
    if getattr(settings, "csrf_enabled", True) and not _csrf_secure_effective:
        logger.warning(
            "[SecurityBaseline] CSRF cookies would be sent without Secure flag (csrf_cookie_secure=False "
            "and debug=True); set CSRF_COOKIE_SECURE=true for HTTPS or use DEBUG=false so cookies are Secure."
        )
    if not getattr(settings, "csrf_enabled", True):
        logger.warning(
            "[SecurityBaseline] csrf_enabled=False in production; unsafe HTTP methods are not CSRF double-submit "
            "protected (only suitable for machine-only APIs without browser cookie sessions)."
        )
    if getattr(settings, "openapi_public_enabled", False):
        logger.warning(
            "[SecurityBaseline] OPENAPI_PUBLIC_ENABLED=true: /docs, /redoc and /openapi.json are exposed; "
            "restrict at ingress or set to false."
        )
    if not getattr(settings, "security_headers_enabled", False):
        logger.warning(
            "[SecurityBaseline] security_headers_enabled=False in production; "
            "enable SECURITY_HEADERS_ENABLED and set HSTS/referrer/frame headers for browser-facing deployments."
        )
    if (getattr(settings, "trusted_hosts", "") or "").strip() and not getattr(
        settings, "trusted_host_exempt_ops_paths", True
    ):
        logger.warning(
            "[SecurityBaseline] trusted_host_exempt_ops_paths=false with TRUSTED_HOSTS set: "
            "Kubernetes probes must send a matching Host header (httpGet.httpHeaders) or include probe IPs/DNS in TRUSTED_HOSTS."
        )
    _fwd_cfg = (getattr(settings, "uvicorn_forwarded_allow_ips", "") or "").strip()
    _fwd_env = (os.environ.get("FORWARDED_ALLOW_IPS") or "").strip()
    _fwd_eff = _fwd_cfg or _fwd_env
    if _fwd_eff == "*" and bool(getattr(settings, "uvicorn_proxy_headers", True)):
        logger.warning(
            "[SecurityBaseline] forwarded allow IPs are '*' (FORWARDED_ALLOW_IPS or UVICORN_FORWARDED_ALLOW_IPS); "
            "only safe behind a trusted reverse proxy or private network."
        )
    if not getattr(settings, "data_redaction_enabled", True):
        logger.warning(
            "[SecurityBaseline] data_redaction_enabled=False in production; structured logs may retain sensitive fields "
            "(set DATA_REDACTION_ENABLED=true unless you fully trust log sinks and retention)."
        )
    if getattr(settings, "tool_system_env_enabled", False):
        logger.warning(
            "[SecurityBaseline] tool_system_env_enabled=True: scope TOOL_SYSTEM_ENV_ALLOWED_NAMES tightly; "
            "never set TOOL_SYSTEM_ENV_ALLOW_ALL=true in production (guardrails block allow-all)."
        )
    if not getattr(settings, "audit_log_enabled", False):
        logger.warning(
            "[SecurityBaseline] audit_log_enabled=False in production; control-plane mutations may lack audit trail "
            "(enable AUDIT_LOG_ENABLED and tune AUDIT_LOG_PATH_PREFIXES for compliance)."
        )
    if getattr(settings, "enable_long_term_memory", False):
        logger.warning(
            "[SecurityBaseline] enable_long_term_memory=True in production; confirm retention policies, "
            "tenant isolation, and regulatory requirements for stored memories."
        )
    if bool(getattr(settings, "workflow_distributed_running_limit_enabled", True)) and bool(
        getattr(settings, "workflow_distributed_running_limit_fail_open", True)
    ):
        logger.warning(
            "[SecurityBaseline] workflow_distributed_running_limit_fail_open=True: Redis coordination loss may let "
            "running workflow instances exceed per-workflow caps (set WORKFLOW_DISTRIBUTED_RUNNING_LIMIT_FAIL_OPEN=false "
            "to reject publishes/runs when the limit cannot be enforced)."
        )
    if not getattr(settings, "api_request_whitelist_enabled", True):
        logger.warning(
            "[SecurityBaseline] api_request_whitelist_enabled=False in production; broader request payloads may enter logs/traces; "
            "keep DATA_REDACTION_ENABLED=true and narrow sensitive paths."
        )


def _migrate_legacy_redis_prefixes_sync() -> None:
    """将 Redis 中 openvitamin:* 键迁移到当前 perilla 前缀（可配置关闭）。"""
    try:
        from core.cache.redis_prefix_migration import migrate_legacy_openvitamin_keys

        migrate_legacy_openvitamin_keys()
    except Exception as e:
        logger.warning("[Startup] Redis legacy prefix migration failed: %s", e)


def _verify_event_bus_startup_alignment() -> None:
    """事件总线：配置意图 vs 实际挂载后端不一致时告警；可选 strict 模式下拒绝启动。"""
    if not bool(getattr(settings, "event_bus_enabled", False)):
        return
    strict = bool(getattr(settings, "event_bus_strict_startup", False))
    try:
        from core.events.bus import CompositeEventBus, get_event_bus

        bus = get_event_bus()
        if not isinstance(bus, CompositeEventBus):
            return
        kinds = bus.list_backend_kinds()
        intended = str(getattr(settings, "event_bus_backend", "redis") or "redis").strip().lower()
        if intended == "kafka" and "kafka" not in kinds:
            msg = (
                "EVENT_BUS_BACKEND=kafka but Kafka did not attach to the composite bus "
                "(check aiokafka, EVENT_BUS_KAFKA_BOOTSTRAP_SERVERS, broker reachability). "
                "Only in-process event delivery would be active."
            )
            logger.warning("[Startup] %s", msg)
            if strict:
                raise RuntimeError(f"event_bus_strict_startup: {msg}")
        elif intended == "redis" and "redis" not in kinds:
            msg = (
                "EVENT_BUS_BACKEND=redis but Redis bus is missing from the composite stack (unexpected)."
            )
            logger.warning("[Startup] %s", msg)
            if strict:
                raise RuntimeError(f"event_bus_strict_startup: {msg}")
    except RuntimeError:
        raise
    except Exception as exc:
        logger.debug("[Startup] event bus alignment check skipped: %s", exc)


async def _probe_event_bus_kafka_if_configured() -> tuple[Optional[bool], Optional[str]]:
    """
    启动时对 Kafka bootstrap 做一次 TCP 连通探测（不依赖 aiokafka）。
    返回语义同 _probe_event_bus_redis_if_configured。
    """
    if not bool(getattr(settings, "event_bus_enabled", False)):
        return None, None
    if str(getattr(settings, "event_bus_backend", "") or "").strip().lower() != "kafka":
        return None, None
    bootstrap = str(getattr(settings, "event_bus_kafka_bootstrap_servers", "") or "").strip()
    if not bootstrap:
        return None, None
    timeout = float(getattr(settings, "event_bus_kafka_ping_timeout_seconds", 3.0) or 3.0)
    try:
        from core.events.kafka_ping import probe_kafka_bootstrap_tcp

        await probe_kafka_bootstrap_tcp(bootstrap, timeout_seconds=timeout)
        logger.info("[Startup] event_bus Kafka bootstrap TCP ok")
        return True, None
    except Exception as exc:
        err = str(exc)[:512]
        logger.warning("[Startup] event_bus Kafka bootstrap TCP failed: %s", exc)
        if bool(getattr(settings, "event_bus_strict_startup", False)):
            raise RuntimeError(f"event_bus_strict_startup: Kafka bootstrap TCP failed: {err}") from exc
        return False, err


async def _probe_event_bus_redis_if_configured() -> tuple[Optional[bool], Optional[str]]:
    """
    启动时对 Redis 事件总线做一次 PING（短超时）。
    返回 (None, None) 表示未启用或未配置 redis 后端；否则 (True/False, 错误摘要)。
    strict 模式下失败则抛出 RuntimeError。
    """
    if not bool(getattr(settings, "event_bus_enabled", False)):
        return None, None
    if str(getattr(settings, "event_bus_backend", "") or "").strip().lower() != "redis":
        return None, None
    url = str(getattr(settings, "event_bus_redis_url", "") or "").strip()
    if not url:
        return None, None
    timeout = float(getattr(settings, "event_bus_redis_ping_timeout_seconds", 2.0) or 2.0)
    try:
        from core.events.redis_ping import probe_event_bus_redis

        await probe_event_bus_redis(url, timeout_seconds=timeout)
        logger.info("[Startup] event_bus Redis PING ok")
        return True, None
    except Exception as exc:
        err = str(exc)[:512]
        logger.warning("[Startup] event_bus Redis PING failed: %s", exc)
        if bool(getattr(settings, "event_bus_strict_startup", False)):
            raise RuntimeError(f"event_bus_strict_startup: Redis PING failed: {err}") from exc
        return False, err


async def _probe_api_rate_limit_redis_if_configured() -> tuple[Optional[bool], Optional[str]]:
    """
    启动时对 API 限流 Redis URL 做一次 PING（与中间件共 URL，独立短连接）。
    """
    url = str(getattr(settings, "api_rate_limit_redis_url", "") or "").strip()
    if not url:
        return None, None
    timeout = float(getattr(settings, "api_rate_limit_redis_ping_timeout_seconds", 2.0) or 2.0)
    try:
        from core.events.redis_ping import probe_redis_url

        await probe_redis_url(url, timeout_seconds=timeout)
        logger.info("[Startup] api_rate_limit Redis PING ok")
        return True, None
    except Exception as exc:
        err = str(exc)[:512]
        logger.warning("[Startup] api_rate_limit Redis PING failed: %s", exc)
        return False, err


def _log_startup_banner() -> None:
    logger.info(f"Starting {settings.app_name} v{settings.version}...")
    logger.info("Log files will be kept for 30 days in logs/ directory")
    web_enabled = getattr(settings, "tool_net_web_enabled", True)
    logger.info(f"tool_net_web_enabled={web_enabled} (web.search: True=real, False=disabled)")
    if not web_enabled:
        logger.warning("Web search is DISABLED. Set TOOL_NET_WEB_ENABLED=true (or remove from .env) and restart for real search.")
    try:
        from core.system.runtime_settings import get_workflow_scheduler_max_concurrency

        _wf_cap = get_workflow_scheduler_max_concurrency()
        logger.info("[Startup] workflow_scheduler_platform_max_concurrency=%s (DAG parallel cap)", _wf_cap)
    except Exception as exc:
        logger.debug("[Startup] workflow scheduler cap unavailable: %s", exc)
    try:
        eb_on = bool(getattr(settings, "event_bus_enabled", False))
        eb_be = str(getattr(settings, "event_bus_backend", "redis")).strip().lower()
        logger.info("[Startup] event_bus_enabled=%s event_bus_backend=%s", eb_on, eb_be if eb_on else "(ignored)")
        if eb_on and eb_be == "kafka":
            _kb = str(getattr(settings, "event_bus_kafka_bootstrap_servers", "") or "").strip()
            _hint = _kb if len(_kb) <= 48 else _kb[:45] + "..."
            logger.info("[Startup] event_bus_kafka_bootstrap_servers=%s", _hint or "(empty)")
        if eb_on and bool(getattr(settings, "event_bus_strict_startup", False)):
            logger.info(
                "[Startup] event_bus_strict_startup=True (misconfigured transport will terminate startup)",
            )
    except Exception as exc:
        logger.debug("[Startup] event bus banner skipped: %s", exc)


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
            EventDlqORM,
            McpServer,
            PluginPackageORM,
            PluginInstallationORM,
        )
        from core.data.models.audit import AuditLogORM  # noqa: F401
        from core.data.models.idempotency import IdempotencyRecordORM  # noqa: F401
        from core.data.models.workflow import WorkflowExecutionQueueORM  # noqa: F401
        from sqlalchemy import text

        engine = get_engine()
        Base.metadata.create_all(engine)
        from sqlalchemy import inspect as sa_inspect

        with engine.connect() as conn:
            insp = sa_inspect(conn)
            if "workflow_executions" in insp.get_table_names():
                cols = {c["name"] for c in insp.get_columns("workflow_executions")}
                if "queue_position" not in cols:
                    conn.execute(text("ALTER TABLE workflow_executions ADD COLUMN queue_position INTEGER"))
                if "queued_at" not in cols:
                    conn.execute(text("ALTER TABLE workflow_executions ADD COLUMN queued_at TIMESTAMP"))
                if "wait_duration_ms" not in cols:
                    conn.execute(text("ALTER TABLE workflow_executions ADD COLUMN wait_duration_ms INTEGER"))
                if "tenant_id" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE workflow_executions ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'"
                        )
                    )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_workflow_executions_tenant_workflow "
                        "ON workflow_executions (tenant_id, workflow_id)"
                    )
                )
            if "workflow_execution_queue" in insp.get_table_names():
                q_cols = {c["name"] for c in insp.get_columns("workflow_execution_queue")}
                if "tenant_id" not in q_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE workflow_execution_queue ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'"
                        )
                    )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_workflow_execution_queue_tenant "
                        "ON workflow_execution_queue (tenant_id)"
                    )
                )
            if "workflow_approval_tasks" in insp.get_table_names():
                ap_cols = {c["name"] for c in insp.get_columns("workflow_approval_tasks")}
                if "tenant_id" not in ap_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE workflow_approval_tasks ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'"
                        )
                    )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_workflow_approval_tasks_tenant_execution "
                        "ON workflow_approval_tasks (tenant_id, execution_id)"
                    )
                )
            if "workflow_governance_audits" in insp.get_table_names():
                ga_cols = {c["name"] for c in insp.get_columns("workflow_governance_audits")}
                if "tenant_id" not in ga_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE workflow_governance_audits "
                            "ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'"
                        )
                    )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_workflow_governance_audits_tenant_workflow "
                        "ON workflow_governance_audits (tenant_id, workflow_id)"
                    )
                )
            if "audit_logs" in insp.get_table_names():
                audit_cols = {c["name"] for c in insp.get_columns("audit_logs")}
                if audit_cols and "tenant_id" not in audit_cols:
                    conn.execute(
                        text("ALTER TABLE audit_logs ADD COLUMN tenant_id VARCHAR(128) DEFAULT 'default'")
                    )
            if "mcp_servers" in insp.get_table_names():
                mcp_cols = {c["name"] for c in insp.get_columns("mcp_servers")}
                if "transport" not in mcp_cols:
                    conn.execute(text("ALTER TABLE mcp_servers ADD COLUMN transport VARCHAR(32) DEFAULT 'stdio'"))
                if "base_url" not in mcp_cols:
                    conn.execute(text("ALTER TABLE mcp_servers ADD COLUMN base_url TEXT"))
                if "tenant_id" not in mcp_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE mcp_servers ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'"
                        )
                    )
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_mcp_servers_tenant_id ON mcp_servers (tenant_id)")
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_mcp_servers_tenant_updated "
                        "ON mcp_servers (tenant_id, updated_at)"
                    )
                )
            if "agent_sessions" in insp.get_table_names():
                as_cols = {c["name"] for c in insp.get_columns("agent_sessions")}
                if "tenant_id" not in as_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE agent_sessions ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'"
                        )
                    )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_agent_sessions_user_tenant_updated "
                        "ON agent_sessions (user_id, tenant_id, updated_at)"
                    )
                )
            if "agent_traces" in insp.get_table_names():
                at_cols = {c["name"] for c in insp.get_columns("agent_traces")}
                if "tenant_id" not in at_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE agent_traces ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'"
                        )
                    )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_agent_traces_session_tenant "
                        "ON agent_traces (session_id, tenant_id)"
                    )
                )
            if "idempotency_records" in insp.get_table_names():
                idem_cols = {c["name"] for c in insp.get_columns("idempotency_records")}
                if "tenant_id" not in idem_cols:
                    dialect = conn.engine.dialect.name
                    if dialect == "sqlite":
                        conn.execute(
                            text(
                                """
CREATE TABLE idempotency_records__new (
    id VARCHAR(36) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    scope VARCHAR(64) NOT NULL,
    owner_id VARCHAR(128) NOT NULL,
    idempotency_key VARCHAR(256) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    response_ref VARCHAR(128),
    error_message TEXT,
    expire_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_idem_tenant_scope_owner_key UNIQUE (tenant_id, scope, owner_id, idempotency_key)
)
"""
                            )
                        )
                        conn.execute(
                            text(
                                """
INSERT INTO idempotency_records__new (
    id, tenant_id, scope, owner_id, idempotency_key, request_hash, status,
    response_ref, error_message, expire_at, created_at, updated_at
)
SELECT
    id, 'default', scope, owner_id, idempotency_key, request_hash, status,
    response_ref, error_message, expire_at, created_at, updated_at
FROM idempotency_records
"""
                            )
                        )
                        conn.execute(text("DROP TABLE idempotency_records"))
                        conn.execute(text("ALTER TABLE idempotency_records__new RENAME TO idempotency_records"))
                        for ix_sql in (
                            "CREATE INDEX IF NOT EXISTS ix_idempotency_records_tenant_id ON idempotency_records (tenant_id)",
                            "CREATE INDEX IF NOT EXISTS ix_idempotency_records_scope ON idempotency_records (scope)",
                            "CREATE INDEX IF NOT EXISTS ix_idempotency_records_owner_id ON idempotency_records (owner_id)",
                            "CREATE INDEX IF NOT EXISTS ix_idempotency_records_status ON idempotency_records (status)",
                            "CREATE INDEX IF NOT EXISTS ix_idempotency_records_response_ref ON idempotency_records (response_ref)",
                            "CREATE INDEX IF NOT EXISTS ix_idempotency_records_expire_at ON idempotency_records (expire_at)",
                            "CREATE INDEX IF NOT EXISTS ix_idempotency_records_created_at ON idempotency_records (created_at)",
                        ):
                            conn.execute(text(ix_sql))
                    elif dialect == "postgresql":
                        conn.execute(
                            text(
                                "ALTER TABLE idempotency_records "
                                "ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'"
                            )
                        )
                        conn.execute(text("ALTER TABLE idempotency_records DROP CONSTRAINT IF EXISTS uq_idem_scope_owner_key"))
                        conn.execute(
                            text(
                                "ALTER TABLE idempotency_records ADD CONSTRAINT "
                                "uq_idem_tenant_scope_owner_key UNIQUE (tenant_id, scope, owner_id, idempotency_key)"
                            )
                        )
                        conn.execute(
                            text(
                                "CREATE INDEX IF NOT EXISTS ix_idempotency_records_tenant_id "
                                "ON idempotency_records (tenant_id)"
                            )
                        )
                    elif dialect in ("mysql", "mariadb"):
                        conn.execute(
                            text(
                                "ALTER TABLE idempotency_records "
                                "ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'"
                            )
                        )
                        conn.execute(text("ALTER TABLE idempotency_records DROP INDEX uq_idem_scope_owner_key"))
                        conn.execute(
                            text(
                                "ALTER TABLE idempotency_records ADD CONSTRAINT "
                                "uq_idem_tenant_scope_owner_key UNIQUE (tenant_id, scope, owner_id, idempotency_key)"
                            )
                        )
                        conn.execute(
                            text(
                                "CREATE INDEX IF NOT EXISTS ix_idempotency_records_tenant_id "
                                "ON idempotency_records (tenant_id)"
                            )
                        )
            if "plugin_installations" in insp.get_table_names():
                pi_cols = {c["name"] for c in insp.get_columns("plugin_installations")}
                if "tenant_id" not in pi_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE plugin_installations ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'"
                        )
                    )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_plugin_installations_tenant_package "
                        "ON plugin_installations (tenant_id, package_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_plugin_installations_tenant_updated "
                        "ON plugin_installations (tenant_id, updated_at)"
                    )
                )
            if "image_generation_jobs" in insp.get_table_names():
                ig_cols = {c["name"] for c in insp.get_columns("image_generation_jobs")}
                if "tenant_id" not in ig_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE image_generation_jobs ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'"
                        )
                    )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_image_generation_jobs_tenant_id ON image_generation_jobs (tenant_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_image_generation_jobs_tenant_created "
                        "ON image_generation_jobs (tenant_id, created_at)"
                    )
                )
            if "image_generation_warmups" in insp.get_table_names():
                iw_cols = {c["name"] for c in insp.get_columns("image_generation_warmups")}
                if "tenant_id" not in iw_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE image_generation_warmups ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'"
                        )
                    )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_image_generation_warmups_tenant_id ON image_generation_warmups (tenant_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_image_generation_warmups_tenant_model_latest "
                        "ON image_generation_warmups (tenant_id, model, latest)"
                    )
                )
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
        from core.events import get_event_bus

        await get_event_bus().stop()
    except Exception as e:
        logger.error("[Shutdown] Event bus stop failed (continuing model/runtime cleanup): %s", e)
    try:
        from core.models.registry import get_model_registry
        from core.runtimes.factory import get_runtime_factory

        registry = get_model_registry()
        factory = get_runtime_factory()
        unloaded_count = await _shutdown_unload_registered_models(registry, factory)
        await _shutdown_cleanup_cached_runtimes(factory)
    except Exception as e:
        logger.error(f"[Shutdown] Model/runtime cleanup failed: {e}")
    try:
        from execution_kernel.persistence.db import close_global_database

        await close_global_database()
    except Exception as e:
        logger.debug("[Shutdown] Execution kernel DB close skipped: %s", e)
    try:
        from core.cache.redis_cache import aclose_redis_cache_client

        await aclose_redis_cache_client()
    except Exception as e:
        logger.debug("[Shutdown] Inference Redis cache close skipped: %s", e)
    try:
        from middleware.rate_limit import aclose_rate_limit_redis_client

        await aclose_rate_limit_redis_client()
    except Exception as e:
        logger.debug("[Shutdown] Rate-limit Redis client close skipped: %s", e)
    try:
        from core.data.base import dispose_engine

        dispose_engine()
    except Exception as e:
        logger.debug("[Shutdown] Database engine dispose skipped: %s", e)
    logger.info(f"[Shutdown] Cleanup complete. Unloaded {unloaded_count} models.")
    return unloaded_count


def _set_application_shutting_down(app: Any, shutting_down: bool) -> None:
    """就绪探针与 Prometheus：优雅关停期间摘流量（仅当 shutting_down 为字面量 True 时生效）。"""
    setattr(app.state, "shutting_down", shutting_down)
    try:
        from core.observability.prometheus_metrics import get_prometheus_business_metrics

        get_prometheus_business_metrics().set_health_ready_shutting_down(shutting_down)
    except Exception:
        pass


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
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            logger.warning(
                "[Shutdown] atexit: event loop still running; skip asyncio.run cleanup (avoid nested loop crash)"
            )
            return
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
    from core.models.scanner.localai import LocalAIScanner
    from core.models.scanner.textgen_webui import TextGenerationWebUIScanner

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
    try:
        await LocalAIScanner().scan()
    except Exception as e:
        logger.debug(f"LocalAI scan failed: {e}")
    try:
        await TextGenerationWebUIScanner().scan()
    except Exception as e:
        logger.debug(f"Text Generation WebUI scan failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _apply_security_baseline()
    _log_startup_banner()
    setattr(app.state, "event_bus_redis_ping_ok", None)
    setattr(app.state, "event_bus_redis_ping_error", None)
    setattr(app.state, "event_bus_kafka_tcp_ok", None)
    setattr(app.state, "event_bus_kafka_tcp_error", None)
    setattr(app.state, "api_rate_limit_redis_ping_ok", None)
    setattr(app.state, "api_rate_limit_redis_ping_error", None)
    setattr(app.state, "health_ready_last_eb_degraded_key", None)
    _set_application_shutting_down(app, False)
    try:
        await asyncio.to_thread(_migrate_legacy_redis_prefixes_sync)
    except Exception as e:
        logger.warning("[Startup] Redis legacy prefix migration task failed: %s", e)
    _initialize_database_tables()
    _recover_stale_running_sessions()
    _recover_stale_image_jobs()
    _recover_expired_workflow_leases()
    _start_model_json_snapshot_task(app)
    _register_shutdown_handlers()
    try:
        from core.events import get_event_bus

        await get_event_bus().start()
        _verify_event_bus_startup_alignment()
        ping_ok, ping_err = await _probe_event_bus_redis_if_configured()
        setattr(app.state, "event_bus_redis_ping_ok", ping_ok)
        setattr(app.state, "event_bus_redis_ping_error", ping_err)
        k_ok, k_err = await _probe_event_bus_kafka_if_configured()
        setattr(app.state, "event_bus_kafka_tcp_ok", k_ok)
        setattr(app.state, "event_bus_kafka_tcp_error", k_err)
        await _sync_health_ready_event_bus_degraded_gauge(app)
    except RuntimeError as exc:
        if "event_bus_strict_startup" in str(exc):
            logger.error("[Startup] Refusing to start: %s", exc)
            raise
        logger.warning("[Startup] Event bus startup RuntimeError (non-fatal): %s", exc)
    except Exception as e:
        logger.warning(f"[Startup] Event bus start failed: {e}")
    arl_ok, arl_err = await _probe_api_rate_limit_redis_if_configured()
    setattr(app.state, "api_rate_limit_redis_ping_ok", arl_ok)
    setattr(app.state, "api_rate_limit_redis_ping_error", arl_err)
    _sync_health_ready_api_rate_limit_redis_degraded_gauge(app)
    await _load_plugins_and_skills()
    await _startup_scan_models()
    try:
        yield
    finally:
        _set_application_shutting_down(app, True)
        await _shutdown_cleanup_async()


def _fastapi_openapi_kwargs() -> Dict[str, Any]:
    """生产环境默认关闭公开 OpenAPI，减少攻击面；debug=true 时始终暴露以便本地与契约测试。"""
    if bool(getattr(settings, "debug", True)):
        return {}
    if bool(getattr(settings, "openapi_public_enabled", False)):
        return {}
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


# 创建应用
app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="本地 AI 推理网关",
    lifespan=lifespan,
    dependencies=[Depends(enforce_request_body_whitelist)],
    **_fastapi_openapi_kwargs(),
)
_configure_platform_logging()
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
from middleware.request_size_limit import HttpRequestSizeLimitMiddleware
from middleware.security_headers import SecurityHeadersMiddleware
from middleware.sensitive_data_redaction import SensitiveDataRedactionMiddleware

_api_key_hdr = getattr(settings, "api_rate_limit_api_key_header", "X-Api-Key")

if getattr(settings, "request_trace_enabled", True):
    app.add_middleware(
        RequestTraceMiddleware,
        header_name=getattr(settings, "request_trace_header_name", "X-Request-Id"),
    )

if getattr(settings, "api_rate_limit_enabled", True) and int(getattr(settings, "api_rate_limit_requests", 0)) > 0:
    _rl_redis = (getattr(settings, "api_rate_limit_redis_url", "") or "").strip()
    app.add_middleware(
        InMemoryRateLimitMiddleware,
        requests_per_window=int(getattr(settings, "api_rate_limit_requests", 120)),
        window_seconds=int(getattr(settings, "api_rate_limit_window_seconds", 60)),
        api_key_header=_api_key_hdr,
        max_concurrent_per_user=int(getattr(settings, "api_rate_limit_user_max_concurrent_requests", 5)),
        redis_url=_rl_redis or None,
        redis_key_prefix=str(getattr(settings, "api_rate_limit_redis_key_prefix", "perilla:ratelimit") or "perilla:ratelimit"),
        trust_x_forwarded_for=bool(getattr(settings, "api_rate_limit_trust_x_forwarded_for", True)),
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
    from middleware.gzip_selective import SelectiveGZipMiddleware

    app.add_middleware(
        SelectiveGZipMiddleware,
        minimum_size=int(getattr(settings, "response_gzip_minimum_size", 256) or 256),
    )
if int(getattr(settings, "http_max_request_body_bytes", 0) or 0) > 0:
    app.add_middleware(HttpRequestSizeLimitMiddleware)
if getattr(settings, "security_headers_enabled", False):
    app.add_middleware(SecurityHeadersMiddleware)
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

_trusted_hosts = [x.strip() for x in (getattr(settings, "trusted_hosts", "") or "").split(",") if x.strip()]
if _trusted_hosts:
    app.add_middleware(
        SelectiveTrustedHostMiddleware,
        allowed_hosts=_trusted_hosts,
        www_redirect=False,
        exempt_host_check=trusted_host_exempt_path_predicate,
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
app.include_router(skill_discovery_router)
app.include_router(vlm_router)
app.include_router(asr_router)
app.include_router(images_router)
app.include_router(backup_router)
app.include_router(model_backups_router)
app.include_router(events_router)
app.include_router(collaboration_router)
app.include_router(workflows_router)
app.include_router(audit_router)
app.include_router(mcp_router)
_configure_prometheus_metrics(app)


@app.get("/")
async def root():
    """根端点"""
    return {
        "message": "Welcome to perilla大模型与智能体应用平台",
        "version": settings.version,
    }


@app.get("/api/health", tags=["Health"], summary="基础健康状态（存活向）")
async def health_check(request: Request):
    """健康检查端点"""
    return {
        "status": "healthy",
        "version": settings.version,
        "request_id": getattr(request.state, "request_id", None),
        "trace_id": getattr(request.state, "trace_id", None),
    }


@app.get("/api/health/live", tags=["Health"], summary="存活探针（Kubernetes liveness）")
async def health_live():
    """存活探针：进程是否在线。"""
    return {"status": "alive", "service": settings.app_name, "version": settings.version}


def _event_bus_degraded_reasons(
    *,
    event_bus_enabled: bool,
    intended_backend: str,
    redis_ping_ok: Optional[bool],
    kafka_tcp_ok: Optional[bool],
    bus_backends: Optional[Any],
) -> List[str]:
    """
    事件总线启用时，根据启动探测与运行时挂载推导降级原因码。
    仍为 HTTP 200 / status=ready（数据库可用）；编排层可据 degraded_reasons 决定是否摘流量。
    """
    if not event_bus_enabled:
        return []
    be = (intended_backend or "redis").strip().lower()
    reasons: List[str] = []
    bb = bus_backends if isinstance(bus_backends, list) else None
    if be == "redis":
        if redis_ping_ok is False:
            reasons.append("event_bus_redis_ping_failed")
        if bb and "redis" not in bb:
            reasons.append("event_bus_redis_not_attached")
    elif be == "kafka":
        if kafka_tcp_ok is False:
            reasons.append("event_bus_kafka_tcp_failed")
        if bb and "kafka" not in bb:
            reasons.append("event_bus_kafka_not_attached")
    return reasons


async def _resolve_event_bus_ready_snapshot(app: Any) -> tuple[Optional[List[str]], List[str]]:
    """
    基于当前 app.state 中的探测结果与运行时 bus 列表，计算 event_bus_backends 与降级原因。
    与 /api/health/ready 使用同一套逻辑，避免分叉。
    """
    eb_on = bool(getattr(settings, "event_bus_enabled", False))
    intended_be = str(getattr(settings, "event_bus_backend", "redis") or "redis").strip().lower()
    rp_ok = getattr(app.state, "event_bus_redis_ping_ok", None)
    kk_ok = getattr(app.state, "event_bus_kafka_tcp_ok", None)
    bb_list: Optional[List[str]] = None
    try:
        from core.events.bus import get_event_bus_runtime_status

        eb = await get_event_bus_runtime_status()
        bb = eb.get("bus_backends")
        if isinstance(bb, list) and bb:
            bb_list = bb
    except Exception:
        pass
    reasons = _event_bus_degraded_reasons(
        event_bus_enabled=eb_on,
        intended_backend=intended_be,
        redis_ping_ok=rp_ok,
        kafka_tcp_ok=kk_ok,
        bus_backends=bb_list,
    )
    return bb_list, reasons


def _apply_health_ready_event_bus_degraded_metric(reasons: List[str]) -> None:
    try:
        from core.observability.prometheus_metrics import get_prometheus_business_metrics

        get_prometheus_business_metrics().set_health_ready_event_bus_degraded(bool(reasons))
    except Exception:
        pass


def _apply_health_ready_inference_cache_redis_degraded_metric(reasons: List[str]) -> None:
    try:
        from core.observability.prometheus_metrics import get_prometheus_business_metrics

        get_prometheus_business_metrics().set_health_ready_inference_cache_redis_degraded(bool(reasons))
    except Exception:
        pass


def _apply_health_ready_api_rate_limit_redis_degraded_metric(reasons: List[str]) -> None:
    try:
        from core.observability.prometheus_metrics import get_prometheus_business_metrics

        get_prometheus_business_metrics().set_health_ready_api_rate_limit_redis_degraded(bool(reasons))
    except Exception:
        pass


def _sync_health_ready_api_rate_limit_redis_degraded_gauge(app: Any) -> None:
    """启动探测后刷新 Gauge：仅依据启动 PING，供 /metrics 先有意义。"""
    reasons: List[str] = []
    ok = getattr(app.state, "api_rate_limit_redis_ping_ok", None)
    if ok is False:
        reasons.append("api_rate_limit_redis_ping_failed")
    _apply_health_ready_api_rate_limit_redis_degraded_metric(reasons)


async def _sync_health_ready_event_bus_degraded_gauge(app: Any) -> None:
    """更新 Prometheus：事件总线是否处于降级（与就绪探针判定一致）。启动探测后调用，使 /metrics 无需先打 ready。"""
    try:
        _, reasons = await _resolve_event_bus_ready_snapshot(app)
        _apply_health_ready_event_bus_degraded_metric(reasons)
    except Exception:
        pass


def _inference_cache_probe_fill_from_cache(
    payload: dict, app: Any, *, now: float, cache_sec: float, strict_ic: bool
) -> Optional[List[str]]:
    """若命中本地短时缓存则写入 payload 并返回 ic_reasons；未命中返回 None。"""
    if strict_ic or cache_sec <= 0.0:
        return None
    last_ts = getattr(app.state, "health_ready_ic_redis_probe_monotonic_ts", None)
    if last_ts is None or (now - float(last_ts)) >= cache_sec:
        return None
    ic_reasons: List[str] = []
    last_ok = getattr(app.state, "health_ready_ic_redis_probe_last_ok", None)
    last_err = getattr(app.state, "health_ready_ic_redis_probe_last_err", None)
    if last_ok is not None:
        payload["inference_cache_redis_ping_ok"] = bool(last_ok)
    if last_err:
        payload["inference_cache_redis_ping_error"] = str(last_err)
    if last_ok is False:
        ic_reasons.append("inference_cache_redis_ping_failed")
    return ic_reasons


async def _collect_inference_cache_ready_reasons(payload: dict, app: Any) -> List[str]:
    """
    推理缓存 Redis PING；写入 payload 并返回降级原因码。
    strict 模式每次实时 PING；非 strict 可用 health_ready_inference_redis_probe_cache_seconds 复用结果以减轻 Redis 压力。
    """
    ic_reasons: List[str] = []
    if not bool(getattr(settings, "inference_cache_enabled", False)):
        return ic_reasons
    ic_url = (str(getattr(settings, "inference_cache_redis_url", "") or "").strip())
    if not ic_url:
        return ic_reasons

    strict_ic = bool(getattr(settings, "health_ready_strict_inference_redis", False))
    probe_enabled = bool(getattr(settings, "health_ready_inference_redis_probe_enabled", True))
    if not probe_enabled and not strict_ic:
        return ic_reasons

    cache_sec = float(getattr(settings, "health_ready_inference_redis_probe_cache_seconds", 5.0) or 0.0)
    now = time.monotonic()
    cached = _inference_cache_probe_fill_from_cache(payload, app, now=now, cache_sec=cache_sec, strict_ic=strict_ic)
    if cached is not None:
        return cached

    try:
        from core.cache import get_redis_cache_client

        ic_ok, ic_err = await get_redis_cache_client().ping_for_health()
        setattr(app.state, "health_ready_ic_redis_probe_monotonic_ts", now)
        setattr(app.state, "health_ready_ic_redis_probe_last_ok", ic_ok)
        setattr(app.state, "health_ready_ic_redis_probe_last_err", ic_err)
        payload["inference_cache_redis_ping_ok"] = ic_ok
        if ic_err:
            payload["inference_cache_redis_ping_error"] = ic_err
        if not ic_ok:
            ic_reasons.append("inference_cache_redis_ping_failed")
    except Exception:
        pass
    return ic_reasons


def _arl_probe_fill_from_cache(
    payload: dict, app: Any, *, now: float, cache_sec: float, strict_arl: bool
) -> Optional[List[str]]:
    if strict_arl or cache_sec <= 0.0:
        return None
    last_ts = getattr(app.state, "health_ready_arl_redis_probe_monotonic_ts", None)
    if last_ts is None or (now - float(last_ts)) >= cache_sec:
        return None
    arl_reasons: List[str] = []
    last_ok = getattr(app.state, "health_ready_arl_redis_probe_last_ok", None)
    last_err = getattr(app.state, "health_ready_arl_redis_probe_last_err", None)
    if last_ok is not None:
        payload["api_rate_limit_redis_ping_ok"] = bool(last_ok)
    if last_err:
        payload["api_rate_limit_redis_ping_error"] = str(last_err)
    if last_ok is False:
        arl_reasons.append("api_rate_limit_redis_ping_failed")
    return arl_reasons


async def _collect_api_rate_limit_redis_ready_reasons(payload: dict, app: Any) -> List[str]:
    """
    API 限流 Redis PING：写入 payload 并返回降级原因码。
    关闭实时探测且非 strict 时仅反映启动期探测结果（app.state）。
    """
    arl_reasons: List[str] = []
    url = str(getattr(settings, "api_rate_limit_redis_url", "") or "").strip()
    if not url:
        return arl_reasons

    strict_arl = bool(getattr(settings, "health_ready_strict_api_rate_limit_redis", False))
    probe_enabled = bool(getattr(settings, "health_ready_api_rate_limit_redis_probe_enabled", True))
    if not probe_enabled and not strict_arl:
        ok = getattr(app.state, "api_rate_limit_redis_ping_ok", None)
        err = getattr(app.state, "api_rate_limit_redis_ping_error", None)
        if ok is not None:
            payload["api_rate_limit_redis_ping_ok"] = ok
        if err:
            payload["api_rate_limit_redis_ping_error"] = err
        if ok is False:
            arl_reasons.append("api_rate_limit_redis_ping_failed")
        return arl_reasons

    cache_sec = float(getattr(settings, "health_ready_api_rate_limit_redis_probe_cache_seconds", 5.0) or 0.0)
    now = time.monotonic()
    cached = _arl_probe_fill_from_cache(payload, app, now=now, cache_sec=cache_sec, strict_arl=strict_arl)
    if cached is not None:
        return cached

    try:
        from core.events.redis_ping import probe_redis_url

        timeout = float(getattr(settings, "api_rate_limit_redis_ping_timeout_seconds", 2.0) or 2.0)
        await probe_redis_url(url, timeout_seconds=timeout)
        setattr(app.state, "health_ready_arl_redis_probe_monotonic_ts", now)
        setattr(app.state, "health_ready_arl_redis_probe_last_ok", True)
        setattr(app.state, "health_ready_arl_redis_probe_last_err", None)
        payload["api_rate_limit_redis_ping_ok"] = True
        return arl_reasons
    except Exception as exc:
        err = str(exc)[:512]
        setattr(app.state, "health_ready_arl_redis_probe_monotonic_ts", now)
        setattr(app.state, "health_ready_arl_redis_probe_last_ok", False)
        setattr(app.state, "health_ready_arl_redis_probe_last_err", err)
        payload["api_rate_limit_redis_ping_ok"] = False
        payload["api_rate_limit_redis_ping_error"] = err
        arl_reasons.append("api_rate_limit_redis_ping_failed")
        return arl_reasons


async def _assemble_health_ready_payload(request: Request) -> tuple[dict, List[str], List[str], List[str]]:
    """数据库已通过探测后的就绪负载（含事件总线、推理缓存 / API 限流 Redis 与 Prometheus 副作用）。返回四元组。"""
    payload: dict = {"status": "ready", "database": "ok", "version": settings.version}
    try:
        from core.system.runtime_settings import get_workflow_scheduler_max_concurrency

        payload["workflow_scheduler_max_concurrency"] = get_workflow_scheduler_max_concurrency()
    except Exception:
        pass
    try:
        eb_on = bool(getattr(settings, "event_bus_enabled", False))
        if eb_on:
            intended_be = str(getattr(settings, "event_bus_backend", "redis") or "redis").strip().lower()
            payload["event_bus_backend"] = intended_be
    except Exception:
        pass
    rp_ok = getattr(request.app.state, "event_bus_redis_ping_ok", None)
    rp_err = getattr(request.app.state, "event_bus_redis_ping_error", None)
    kk_ok = getattr(request.app.state, "event_bus_kafka_tcp_ok", None)
    kk_err = getattr(request.app.state, "event_bus_kafka_tcp_error", None)
    try:
        if rp_ok is not None:
            payload["event_bus_redis_ping_ok"] = rp_ok
        if rp_err:
            payload["event_bus_redis_ping_error"] = rp_err
        if kk_ok is not None:
            payload["event_bus_kafka_tcp_ok"] = kk_ok
        if kk_err:
            payload["event_bus_kafka_tcp_error"] = kk_err
    except Exception:
        pass
    eb_reasons: List[str] = []
    try:
        bb_list, eb_reasons = await _resolve_event_bus_ready_snapshot(request.app)
        if bb_list:
            payload["event_bus_backends"] = bb_list
    except Exception:
        pass

    ic_reasons = await _collect_inference_cache_ready_reasons(payload, request.app)

    arl_reasons = await _collect_api_rate_limit_redis_ready_reasons(payload, request.app)

    degraded_merge = [*eb_reasons, *ic_reasons, *arl_reasons]
    if degraded_merge:
        payload["degraded"] = True
        payload["degraded_reasons"] = degraded_merge

    _apply_health_ready_event_bus_degraded_metric(eb_reasons)
    _apply_health_ready_inference_cache_redis_degraded_metric(ic_reasons)
    _apply_health_ready_api_rate_limit_redis_degraded_metric(arl_reasons)
    return payload, eb_reasons, ic_reasons, arl_reasons


def _log_event_bus_degraded_transition(app: Any, reasons: List[str]) -> None:
    """仅在事件总线降级原因集合相对上一次 /ready 检查发生变化时打 INFO，避免探针刷屏。"""
    key = tuple(sorted(reasons))
    prev = getattr(app.state, "health_ready_last_eb_degraded_key", None)
    if key == prev:
        return
    setattr(app.state, "health_ready_last_eb_degraded_key", key)
    if prev is None and not key:
        return
    if key:
        logger.info("[HealthReady] event bus degraded: %s", list(key))
    else:
        logger.info("[HealthReady] event bus no longer degraded (recovered)")


def _log_inference_cache_redis_degraded_transition(app: Any, reasons: List[str]) -> None:
    key = tuple(sorted(reasons))
    prev = getattr(app.state, "health_ready_last_ic_redis_degraded_key", None)
    if key == prev:
        return
    setattr(app.state, "health_ready_last_ic_redis_degraded_key", key)
    if prev is None and not key:
        return
    if key:
        logger.info("[HealthReady] inference-cache Redis degraded: %s", list(key))
    else:
        logger.info("[HealthReady] inference-cache Redis no longer degraded (recovered)")


def _log_api_rate_limit_redis_degraded_transition(app: Any, reasons: List[str]) -> None:
    key = tuple(sorted(reasons))
    prev = getattr(app.state, "health_ready_last_arl_redis_degraded_key", None)
    if key == prev:
        return
    setattr(app.state, "health_ready_last_arl_redis_degraded_key", key)
    if prev is None and not key:
        return
    if key:
        logger.info("[HealthReady] API rate-limit Redis degraded: %s", list(key))
    else:
        logger.info("[HealthReady] API rate-limit Redis no longer degraded (recovered)")


@app.get(
    "/api/health/ready",
    tags=["Health"],
    summary="就绪探针（Kubernetes readiness）",
    responses={
        503: {
            "description": "未就绪：数据库不可用；或 STRICT 模式下事件总线/推理缓存 Redis/API 限流 Redis 依赖降级",
            "headers": {
                "Retry-After": {
                    "description": "建议重试间隔（秒），严格就绪返回 5",
                    "schema": {"type": "string"},
                }
            },
        },
    },
)
async def health_ready(request: Request):
    """就绪探针：关键依赖（数据库）是否可用；依赖降级时附带 degraded / degraded_reasons。"""
    app = getattr(request, "app", None)
    st = getattr(app, "state", None) if app is not None else None
    if st is not None and getattr(st, "shutting_down", None) is True:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database": "ok",
                "version": settings.version,
                "degraded": True,
                "degraded_reasons": ["application_shutting_down"],
            },
            headers={"Retry-After": "1"},
        )
    try:
        from core.data.base import get_engine
        from sqlalchemy import text

        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        payload, eb_reasons, ic_reasons, arl_reasons = await _assemble_health_ready_payload(request)
        _log_event_bus_degraded_transition(request.app, eb_reasons)
        _log_inference_cache_redis_degraded_transition(request.app, ic_reasons)
        _log_api_rate_limit_redis_degraded_transition(request.app, arl_reasons)
        strict_eb = bool(getattr(settings, "health_ready_strict_event_bus", False))
        if strict_eb and eb_reasons:
            logger.debug("[HealthReady] strict readiness: event bus degraded: %s", eb_reasons)
            return JSONResponse(
                status_code=503,
                content=payload,
                headers={"Retry-After": "5"},
            )
        strict_ic = bool(getattr(settings, "health_ready_strict_inference_redis", False))
        if strict_ic and ic_reasons:
            logger.debug("[HealthReady] strict readiness: inference-cache Redis degraded: %s", ic_reasons)
            return JSONResponse(
                status_code=503,
                content=payload,
                headers={"Retry-After": "5"},
            )
        strict_arl = bool(getattr(settings, "health_ready_strict_api_rate_limit_redis", False))
        if strict_arl and arl_reasons:
            logger.debug("[HealthReady] strict readiness: API rate-limit Redis degraded: %s", arl_reasons)
            return JSONResponse(
                status_code=503,
                content=payload,
                headers={"Retry-After": "5"},
            )
        return payload
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
    from core.models.scanner.localai import LocalAIScanner
    from core.models.scanner.textgen_webui import TextGenerationWebUIScanner
    from core.models.registry import get_model_registry
    from core.runtimes.factory import get_runtime_factory
    
    results = {"ollama": 0, "lmstudio": 0, "localai": 0, "textgen_webui": 0, "local": 0, "removed": 0}
    
    await _scan_model_count(OllamaScanner, "ollama", results)
    await _scan_model_count(LMStudioScanner, "lmstudio", results, log_level="debug")
    await _scan_model_count(LocalAIScanner, "localai", results, log_level="debug")
    await _scan_model_count(TextGenerationWebUIScanner, "textgen_webui", results, log_level="debug")
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
    _uv_kw: Dict[str, Any] = {
        "host": settings.host,
        "port": settings.port,
        "reload": settings.debug,
    }
    _tgs = getattr(settings, "uvicorn_timeout_graceful_shutdown_seconds", None)
    if _tgs is not None:
        _uv_kw["timeout_graceful_shutdown"] = int(_tgs)
    _ka = getattr(settings, "uvicorn_timeout_keep_alive_seconds", None)
    if _ka is not None:
        _uv_kw["timeout_keep_alive"] = int(_ka)
    _uv_kw["proxy_headers"] = bool(getattr(settings, "uvicorn_proxy_headers", True))
    _fwd_allow = (getattr(settings, "uvicorn_forwarded_allow_ips", "") or "").strip()
    if _fwd_allow:
        _uv_kw["forwarded_allow_ips"] = _fwd_allow
    _lc = getattr(settings, "uvicorn_limit_concurrency", None)
    if _lc is not None:
        _uv_kw["limit_concurrency"] = int(_lc)
    _lmr = getattr(settings, "uvicorn_limit_max_requests", None)
    if _lmr is not None:
        _uv_kw["limit_max_requests"] = int(_lmr)
    _uv_kw["server_header"] = bool(getattr(settings, "uvicorn_server_header", True))
    _h11 = getattr(settings, "uvicorn_h11_max_incomplete_event_size", None)
    if _h11 is not None:
        _uv_kw["h11_max_incomplete_event_size"] = int(_h11)
    _uv_kw["access_log"] = bool(getattr(settings, "uvicorn_access_log", True))
    _bg = getattr(settings, "uvicorn_backlog", None)
    if _bg is not None:
        _uv_kw["backlog"] = int(_bg)
    _wsz = getattr(settings, "uvicorn_ws_max_size", None)
    if _wsz is not None:
        _uv_kw["ws_max_size"] = int(_wsz)
    _lmrj = getattr(settings, "uvicorn_limit_max_requests_jitter", None)
    if _lmrj is not None:
        _uv_kw["limit_max_requests_jitter"] = int(_lmrj)
    _uv_kw["date_header"] = bool(getattr(settings, "uvicorn_date_header", True))
    _wpi = getattr(settings, "uvicorn_ws_ping_interval_seconds", None)
    if _wpi is not None:
        _uv_kw["ws_ping_interval"] = float(_wpi)
    _wpt = getattr(settings, "uvicorn_ws_ping_timeout_seconds", None)
    if _wpt is not None:
        _uv_kw["ws_ping_timeout"] = float(_wpt)
    _twh = getattr(settings, "uvicorn_timeout_worker_healthcheck_seconds", None)
    if _twh is not None:
        _uv_kw["timeout_worker_healthcheck"] = int(_twh)
    uvicorn.run("main:app", **_uv_kw)
