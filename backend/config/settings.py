"""
配置设置
"""
from io import StringIO
import os
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def bootstrap_env_files(backend_dir: Path) -> None:
    """
    加载环境变量：
    1) 明文 .env（兼容开发）
    2) 加密 .env.encrypted（生产推荐，需通过密钥环境变量解密）
    """
    try:
        from dotenv import dotenv_values, load_dotenv
    except Exception:
        return

    candidates = [
        backend_dir / ".env",
        backend_dir.parent / ".env",
    ]
    for file_path in candidates:
        if file_path.is_file():
            load_dotenv(file_path, override=False)

    encryption_key = os.environ.get("PERILLA_ENV_ENCRYPTION_KEY", "").strip()
    encrypted_candidates = [
        backend_dir / ".env.encrypted",
        backend_dir.parent / ".env.encrypted",
    ]
    for encrypted_file in encrypted_candidates:
        if not encrypted_file.is_file():
            continue
        if not encryption_key:
            raise RuntimeError(
                f"Found encrypted env file but PERILLA_ENV_ENCRYPTION_KEY is empty: {encrypted_file}"
            )
        try:
            from cryptography.fernet import Fernet
        except Exception as exc:
            raise RuntimeError(
                "Encrypted env support requires the cryptography package (pip install cryptography)"
            ) from exc
        cipher = Fernet(encryption_key.encode("utf-8"))
        decrypted = cipher.decrypt(encrypted_file.read_bytes()).decode("utf-8")
        parsed = dotenv_values(stream=StringIO(decrypted))
        for key, value in parsed.items():
            if key and value is not None:
                os.environ.setdefault(key, value)


def _cors_origin_looks_insecure_http(origin: str) -> bool:
    """生产场景下浏览器源应为 https；允许 http://localhost / 127.0.0.1 供本地前端。"""
    o = (origin or "").strip()
    if not o or o == "*":
        return False
    low = o.lower()
    if low.startswith("https://"):
        return False
    if not low.startswith("http://"):
        return False
    if "localhost" in low or "127.0.0.1" in low:
        return False
    return True


def _normalize_roots(raw_roots: str) -> list[Path]:
    out: list[Path] = []
    for root in (raw_roots or "").split(","):
        trimmed = root.strip()
        if not trimmed:
            continue
        out.append(Path(trimmed).expanduser().resolve())
    return out


def _database_url_is_sqlite_or_memory(url: str) -> bool:
    raw = (url or "").strip()
    if not raw or "://" not in raw:
        return False
    scheme = raw.split("://", 1)[0].lower()
    if scheme.startswith("sqlite"):
        return True
    return ":memory:" in raw.lower()


def _database_url_appears_postgres_family(url: str) -> bool:
    """生产库须为 PostgreSQL 族 DSN（postgresql* / postgres:// 等）。"""
    if _database_url_is_sqlite_or_memory(url):
        return False
    raw = (url or "").strip()
    if not raw or "://" not in raw:
        return False
    scheme = raw.split("://", 1)[0].lower()
    return scheme.startswith("postgres")


_TRIVIAL_DATABASE_PASSWORDS = frozenset(
    {
        "postgres",
        "password",
        "secret",
        "changeme",
        "admin",
        "root",
        "pass",
        "123456",
        "12345678",
        "postgresql",
        "mysql",
        "sample",
        "demo",
    }
)


def _database_url_has_placeholder_password(url: str) -> bool:
    """检测 PostgreSQL 族 URL 用户口令是否为常见默认/占位（urllib 解析 userinfo）。"""
    raw = (url or "").strip()
    if not raw or "://" not in raw:
        return False
    try:
        from urllib.parse import urlparse, unquote

        parsed = urlparse(raw)
        pw = unquote(parsed.password or "")
        if not pw:
            return False
        return pw.lower() in _TRIVIAL_DATABASE_PASSWORDS
    except Exception:
        return False


_MIN_RBAC_API_KEY_SEGMENT_LEN = 12
# 逗号分段键值完全匹配（大小写不敏感）；避免教程/示例占位串进入生产
_WEAK_RBAC_API_KEY_TOKENS = frozenset(
    {
        "changeme",
        "change-me",
        "password",
        "secret",
        "admin",
        "root",
        "test",
        "testing",
        "example",
        "demo",
        "dummy",
        "sample",
        "placeholder",
        "apikey",
        "api-key",
        "api_key",
        "admin-key",
        "adminkey",
        "administrator",
        "dev-key",
        "devkey",
        "test-key",
        "testkey",
        "sample-key",
        "redacted",
        "redacted-admin-key",
        "token",
        "your-token-here",
        "insert-api-key",
    }
)


def _rbac_api_keys_config_nonempty(s: object) -> bool:
    """rbac_*_api_keys 为逗号分隔列表，任一片段非空即视为已配置。"""
    for attr in ("rbac_admin_api_keys", "rbac_operator_api_keys", "rbac_viewer_api_keys"):
        raw = str(getattr(s, attr, "") or "")
        for part in raw.split(","):
            if part.strip():
                return True
    return False


def _rbac_api_key_strength_issues(s: object) -> list[str]:
    """生产环境下 RBAC 密钥片段长度与占位符检测。"""
    if not _rbac_api_keys_config_nonempty(s):
        return []
    out: list[str] = []
    fields = (
        ("RBAC_ADMIN_API_KEYS", "rbac_admin_api_keys"),
        ("RBAC_OPERATOR_API_KEYS", "rbac_operator_api_keys"),
        ("RBAC_VIEWER_API_KEYS", "rbac_viewer_api_keys"),
    )
    for label, attr in fields:
        raw = str(getattr(s, attr, "") or "")
        for part in raw.split(","):
            seg = part.strip()
            if not seg:
                continue
            low = seg.lower()
            if len(seg) < _MIN_RBAC_API_KEY_SEGMENT_LEN:
                out.append(
                    f"{label}: each key segment must be at least "
                    f"{_MIN_RBAC_API_KEY_SEGMENT_LEN} characters in production"
                )
            elif low in _WEAK_RBAC_API_KEY_TOKENS:
                out.append(
                    f"{label}: denylisted placeholder token not allowed in production "
                    f"(replace with a strong secret)"
                )
    return out


def apply_production_security_defaults(s: "Settings") -> list[str]:
    """
    在非 debug 环境下自动收敛关键安全开关，返回变更项列表。
    """
    changes: list[str] = []
    if getattr(s, "debug", True):
        return changes

    def _set_true(attr: str) -> None:
        if not bool(getattr(s, attr, False)):
            setattr(s, attr, True)
            changes.append(attr)

    _set_true("rbac_enabled")
    _set_true("rbac_enforcement")
    _set_true("tenant_enforcement_enabled")
    _set_true("tenant_api_key_binding_enabled")
    _set_true("events_strict_workflow_binding")
    _set_true("events_api_require_authenticated")
    # X-Content-Type-Options / X-Frame-Options / Referrer-Policy（HSTS 仍由配置显式开启）
    _set_true("security_headers_enabled")
    # 断连时停止上游生成，避免僵尸推理占用 GPU/配额（可按环境关闭）
    _set_true("chat_stream_resume_cancel_upstream_on_disconnect")
    required_roots = (getattr(s, "production_file_read_required_roots", "") or "").strip()
    if required_roots and (getattr(s, "file_read_allowed_roots", "") or "").strip() != required_roots:
        setattr(s, "file_read_allowed_roots", required_roots)
        changes.append("file_read_allowed_roots")
    # 0 = 不设上限（与 Ingress client_max_body_size 脱节）；生产收敛为 52MiB，可按需提高 HTTP_MAX_REQUEST_BODY_BYTES
    _mb = int(getattr(s, "http_max_request_body_bytes", 0) or 0)
    if _mb == 0:
        setattr(s, "http_max_request_body_bytes", 52428800)
        changes.append("http_max_request_body_bytes")
    if bool(getattr(s, "inference_cache_enabled", False)) and not bool(
        getattr(s, "health_ready_strict_inference_redis", False)
    ):
        setattr(s, "health_ready_strict_inference_redis", True)
        changes.append("health_ready_strict_inference_redis")
    _arl_u = (getattr(s, "api_rate_limit_redis_url", "") or "").strip()
    if (
        bool(getattr(s, "api_rate_limit_enabled", False))
        and int(getattr(s, "api_rate_limit_requests", 0) or 0) > 0
        and bool(_arl_u)
        and not bool(getattr(s, "health_ready_strict_api_rate_limit_redis", False))
    ):
        setattr(s, "health_ready_strict_api_rate_limit_redis", True)
        changes.append("health_ready_strict_api_rate_limit_redis")
    if (
        bool(getattr(s, "api_rate_limit_enabled", False))
        and int(getattr(s, "api_rate_limit_requests", 0) or 0) > 0
        and bool(_arl_u)
        and not bool(getattr(s, "api_rate_limit_redis_fail_closed", False))
    ):
        setattr(s, "api_rate_limit_redis_fail_closed", True)
        changes.append("api_rate_limit_redis_fail_closed")
    return changes


def validate_production_security_guardrails(s: "Settings") -> list[str]:
    """
    校验高危配置并返回违规项列表。
    开发模式（debug=True）且 security_guardrails_strict=False 时跳过校验（便于本地宽松开发）；
    其余情况执行校验；是否在启动时阻断由 main 中结合 debug / strict 决定。
    """
    issues: list[str] = []
    if getattr(s, "debug", True) and not getattr(s, "security_guardrails_strict", True):
        return issues

    raw_roots = (getattr(s, "file_read_allowed_roots", "") or "").strip()
    if raw_roots == "/":
        issues.append("file_read_allowed_roots must not be '/' in production")
    allowed_roots = _normalize_roots(raw_roots)
    if not allowed_roots:
        issues.append("file_read_allowed_roots must be explicitly configured in production")
    required_roots = _normalize_roots(getattr(s, "production_file_read_required_roots", "") or "")
    for required_root in required_roots:
        if required_root not in allowed_roots:
            issues.append(
                f"file_read_allowed_roots must include required production root: {required_root}"
            )
    production_allowlist = _normalize_roots(getattr(s, "production_file_read_allowed_roots", "") or "")
    if production_allowlist:
        allow_set = {str(p) for p in production_allowlist}
        for root in allowed_roots:
            if str(root) not in allow_set:
                issues.append(
                    f"file_read_allowed_roots contains disallowed production root: {root}"
                )
    if (getattr(s, "cors_allowed_origins", "") or "").strip() == "":
        issues.append("cors_allowed_origins must be explicitly configured in production")
    elif not getattr(s, "debug", True):
        _cors_raw = (getattr(s, "cors_allowed_origins", "") or "")
        _cors_handled = False
        for _co in _cors_raw.split(","):
            if _co.strip() == "*":
                issues.append(
                    "cors_allowed_origins must not include '*' in production; "
                    "use explicit https:// origins for browser clients"
                )
                _cors_handled = True
                break
        if not _cors_handled:
            for _co in _cors_raw.split(","):
                seg = _co.strip()
                if _cors_origin_looks_insecure_http(seg):
                    issues.append(
                        f"cors_allowed_origins must use https:// for non-local browser origins in production (got {seg!r}); "
                        "http://localhost and http://127.0.0.1 are allowed for local frontends"
                    )
                    break
    if not getattr(s, "debug", True):
        th = (getattr(s, "trusted_hosts", "") or "").strip()
        if not th:
            issues.append(
                "trusted_hosts must be set in production (comma-separated allowed Host headers); set TRUSTED_HOSTS"
            )
    raw_db_url = (getattr(s, "database_url", "") or "").strip()
    if not raw_db_url:
        issues.append(
            "database_url must be set (PostgreSQL) for production; SQLite fallback is single-process only"
        )
    elif _database_url_is_sqlite_or_memory(raw_db_url):
        issues.append(
            "database_url must not use SQLite or in-memory DSN in production (not safe for multi-replica)"
        )
    elif raw_db_url and not _database_url_appears_postgres_family(raw_db_url):
        issues.append(
            "database_url must use PostgreSQL in production (postgresql+psycopg2 / postgresql+asyncpg / postgres://)"
        )
    if raw_db_url and _database_url_appears_postgres_family(raw_db_url):
        if _database_url_has_placeholder_password(raw_db_url):
            issues.append(
                "database_url uses a trivial/default PostgreSQL password; rotate credentials in production "
                "(avoid well-known literals in the DSN userinfo)"
            )
    ek_url = (
        str(getattr(s, "execution_kernel_db_url", "") or "").strip()
        or (os.environ.get("EXECUTION_KERNEL_DB_URL") or "").strip()
    )
    if ek_url:
        if _database_url_is_sqlite_or_memory(ek_url):
            issues.append(
                "EXECUTION_KERNEL_DB_URL must not use SQLite or in-memory DSN in production when set"
            )
        elif not _database_url_appears_postgres_family(ek_url):
            issues.append(
                "EXECUTION_KERNEL_DB_URL must use PostgreSQL when set in production"
            )
        elif _database_url_has_placeholder_password(ek_url):
            issues.append(
                "EXECUTION_KERNEL_DB_URL uses a trivial/default PostgreSQL password in production when set"
            )
    if getattr(s, "tool_net_http_enabled", False) and (getattr(s, "tool_net_http_allowed_hosts", "") or "").strip() == "":
        issues.append("tool_net_http_allowed_hosts must be set when tool_net_http_enabled=True in production")
    if not getattr(s, "debug", True):
        lf = str(getattr(s, "log_format", "") or "text").strip().lower()
        if lf != "json":
            issues.append(
                "log_format must be 'json' in production for structured logging (set LOG_FORMAT=json)"
            )
    if bool(getattr(s, "event_bus_enabled", False)):
        backend = str(getattr(s, "event_bus_backend", "redis") or "redis").strip().lower()
        if backend == "kafka":
            bootstrap = str(getattr(s, "event_bus_kafka_bootstrap_servers", "") or "").strip()
            if not bootstrap:
                issues.append(
                    "event_bus_kafka_bootstrap_servers must be set when event_bus_enabled=True and event_bus_backend=kafka"
                )
        elif backend == "redis":
            redis_url = str(getattr(s, "event_bus_redis_url", "") or "").strip()
            if not redis_url:
                issues.append(
                    "event_bus_redis_url must be set when event_bus_enabled=True and event_bus_backend=redis"
                )
    if not getattr(s, "debug", True) and bool(getattr(s, "event_bus_enabled", False)):
        if not bool(getattr(s, "event_bus_strict_startup", False)):
            issues.append(
                "event_bus_strict_startup must be True in production when event_bus_enabled=True "
                "(set EVENT_BUS_STRICT_STARTUP=true so misconfigured Redis/Kafka fails startup)"
            )
    if bool(getattr(s, "health_ready_strict_event_bus", False)) and not bool(
        getattr(s, "event_bus_enabled", False)
    ):
        issues.append(
            "health_ready_strict_event_bus has no effect when event_bus_enabled=False; unset strict flag or enable event bus"
        )
    if bool(getattr(s, "health_ready_strict_inference_redis", False)) and not bool(
        getattr(s, "inference_cache_enabled", False)
    ):
        issues.append(
            "health_ready_strict_inference_redis has no effect when inference_cache_enabled=False; unset strict flag or disable unused strict mode"
        )
    if bool(getattr(s, "health_ready_strict_api_rate_limit_redis", False)):
        arl_url = str(getattr(s, "api_rate_limit_redis_url", "") or "").strip()
        if not arl_url:
            issues.append(
                "health_ready_strict_api_rate_limit_redis has no effect without api_rate_limit_redis_url; "
                "set API_RATE_LIMIT_REDIS_URL or unset strict flag"
            )
    if getattr(s, "audit_log_enabled", False):
        raw_audit = (getattr(s, "audit_log_path_prefixes", "") or "").strip()
        for part in raw_audit.split(","):
            if part.strip() == "/":
                issues.append(
                    "audit_log_path_prefixes must not include '/' alone (would audit every HTTP path)"
                )
                break
    if (
        not getattr(s, "debug", True)
        and bool(getattr(s, "rbac_enabled", False))
        and not _rbac_api_keys_config_nonempty(s)
    ):
        issues.append(
            "rbac_enabled=True in production requires at least one key in "
            "RBAC_ADMIN_API_KEYS, RBAC_OPERATOR_API_KEYS, or RBAC_VIEWER_API_KEYS (comma-separated); "
            "see rbac_default_role for unauthenticated behavior"
        )
    if not getattr(s, "debug", True) and bool(getattr(s, "rbac_enabled", False)):
        role = str(getattr(s, "rbac_default_role", "operator") or "").strip().lower()
        if role == "operator":
            issues.append(
                "rbac_default_role must not be 'operator' in production when rbac_enabled=True "
                "(unauthenticated requests inherit this role); set RBAC_DEFAULT_ROLE=viewer "
                "unless you intentionally grant anonymous operator access"
            )
        if _rbac_api_keys_config_nonempty(s):
            issues.extend(_rbac_api_key_strength_issues(s))
    if not getattr(s, "debug", True) and bool(getattr(s, "openapi_public_enabled", False)):
        issues.append(
            "openapi_public_enabled=True exposes /docs, /redoc and /openapi.json in production; "
            "set OPENAPI_PUBLIC_ENABLED=false or restrict at ingress"
        )
    if not getattr(s, "debug", True) and not bool(getattr(s, "data_redaction_enabled", True)):
        issues.append(
            "data_redaction_enabled=False disables structured log/data redaction in production; "
            "set DATA_REDACTION_ENABLED=true"
        )
    if not getattr(s, "debug", True) and bool(getattr(s, "workflow_allow_draft_execution", False)):
        issues.append(
            "workflow_allow_draft_execution=True allows unpublished draft workflow execution in production; "
            "set WORKFLOW_ALLOW_DRAFT_EXECUTION=false"
        )
    if not getattr(s, "debug", True) and bool(getattr(s, "workflow_allow_latest_subworkflow_in_production", False)):
        issues.append(
            "workflow_allow_latest_subworkflow_in_production=True resolves subworkflows to floating 'latest' in production; "
            "set WORKFLOW_ALLOW_LATEST_SUBWORKFLOW_IN_PRODUCTION=false"
        )
    if not getattr(s, "debug", True) and bool(getattr(s, "tool_system_env_allow_all", False)):
        issues.append(
            "tool_system_env_allow_all=True exposes all process environment variables via the system.env tool in production; "
            "set TOOL_SYSTEM_ENV_ALLOW_ALL=false"
        )
    return issues


class Settings(BaseSettings):
    """应用配置"""
    app_name: str = "perilla大模型与智能体应用平台"
    version: str = "1.0.0"
    api_prefix: str = "/api/v1"
    debug: bool = True
    
    # 服务器
    host: str = "0.0.0.0"
    port: int = 8000
    # 仅 `python main.py` 直连 uvicorn 时生效；None 表示使用 uvicorn 默认。生产可与 K8s terminationGracePeriodSeconds 对齐。
    uvicorn_timeout_graceful_shutdown_seconds: Optional[int] = Field(default=None, ge=1, le=600)
    # 仅 python main.py 直连 uvicorn；None=默认 5s。流式/SSE 长连接可适度调大，并与反代 keepalive 协同
    uvicorn_timeout_keep_alive_seconds: Optional[int] = Field(default=None, ge=1, le=300)
    # 仅 python main.py 直连 uvicorn：是否信任代理头（X-Forwarded-Proto / X-Forwarded-For）；置于 Ingress 后通常为 True；直连公网且无反代可 False
    uvicorn_proxy_headers: bool = True
    # 可信上游 IP/CIDR（逗号分隔），传给 uvicorn forwarded_allow_ips。为空时不覆盖，沿用环境变量 FORWARDED_ALLOW_IPS（uvicorn 未设置 env 时默认为 127.0.0.1）。置于 K8s Ingress 后常需列入 Ingress Controller Pod 网段或 “*”（仅在可信链前置）
    uvicorn_forwarded_allow_ips: str = ""
    # 仅 python main.py：限制活跃连接数（uvicorn limit_concurrency）；None=不限制。高并发可与反代 worker 协同设上限防拖垮
    uvicorn_limit_concurrency: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    # 仅 python main.py：进程处理若干请求后退出 worker（uvicorn limit_max_requests，缓解内存碎片）；None=不启用
    uvicorn_limit_max_requests: Optional[int] = Field(default=None, ge=1, le=1_000_000_000)
    # 仅 python main.py：是否响应 Server 头（关闭可降低指纹；反代可能已覆盖）
    uvicorn_server_header: bool = True
    # 仅 python main.py：h11 不完整事件上限字节（缓解慢连接；None=uvicorn/h11 默认）
    uvicorn_h11_max_incomplete_event_size: Optional[int] = Field(default=None, ge=256, le=16_777_216)
    # 仅 python main.py：是否输出 uvicorn access log（极高 QPS 或已由反代采集时可 false）
    uvicorn_access_log: bool = True
    # 仅 python main.py：监听 backlog（内核未完成三次握手队列）；None=uvicorn 默认（常为 2048）
    uvicorn_backlog: Optional[int] = Field(default=None, ge=64, le=65535)
    # 仅 python main.py：单帧 WebSocket 消息上限字节（None=uvicorn 默认 16MiB）；生产可酌情调低缓解恶意大包内存压力
    uvicorn_ws_max_size: Optional[int] = Field(default=None, ge=1024, le=1_073_741_824)
    # 仅 python main.py：与 limit_max_requests 配套的随机抖动上限，减轻多 worker 同时退出（None=uvicorn 默认）
    uvicorn_limit_max_requests_jitter: Optional[int] = Field(default=None, ge=0, le=1_000_000)
    # 仅 python main.py：是否发送 HTTP Date 响应头（False 略减指纹）
    uvicorn_date_header: bool = True
    # 仅 python main.py：WebSocket ping 间隔秒（None=uvicorn 默认 20）；宜小于 Ingress idle_timeout，减少长连接被静默断开
    uvicorn_ws_ping_interval_seconds: Optional[float] = Field(default=None, ge=0.0, le=86400.0)
    # 仅 python main.py：WebSocket ping 超时秒（None=uvicorn 默认 20）
    uvicorn_ws_ping_timeout_seconds: Optional[float] = Field(default=None, ge=0.0, le=86400.0)
    # 仅 python main.py：worker 健康检查超时秒（None=uvicorn 默认 5）；仅多 worker 场景常用
    uvicorn_timeout_worker_healthcheck_seconds: Optional[int] = Field(default=None, ge=1, le=600)
    # HTTP 请求体上限（字节），仅当请求携带 Content-Length 时校验；0=不限制（请与 Ingress / 反代上限协同）
    http_max_request_body_bytes: int = Field(default=0, ge=0, le=5368709120)
    # 生产（debug=false）是否挂载 /docs、/redoc、/openapi.json；开发不受此项限制（debug=true 始终挂载）
    openapi_public_enabled: bool = False
    # 为响应追加安全头（默认关闭；空字符串表示不发送对应头，便于 iframe / 自定义策略）
    security_headers_enabled: bool = False
    security_headers_x_content_type_options: str = "nosniff"
    security_headers_x_frame_options: str = "DENY"
    security_headers_referrer_policy: str = "strict-origin-when-cross-origin"
    # 非空时设置 Strict-Transport-Security（仅应在全站 HTTPS 终端启用；空表示不发送）
    security_headers_strict_transport_security: str = ""
    # 逗号分隔的 Host 头白名单（如 api.example.com,*.example.com）；非空则挂载 TrustedHostMiddleware。生产门禁 debug=false 时必填。
    trusted_hosts: str = ""
    # 为 True 时：健康/指标路径跳过 Host 校验（Kubelet 探针常为 Pod IP）；设 False 则所有路径均校验（探针须配置 httpHeaders.Host 或列入 TRUSTED_HOSTS）
    trusted_host_exempt_ops_paths: bool = True

    # 模型配置
    default_model: str = "llama-3-70b-instruct"
    
    # Ollama 配置
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = ""  # 为空则自动使用本地已下载的第一个模型
    # OpenAI-compatible 本地后端
    localai_base_url: str = "http://localhost:8080"
    textgen_webui_base_url: str = "http://localhost:5000"

    # 数据库配置 (统一合并管理)
    db_path: str = ""  # 为空则使用默认 backend/data/platform.db
    # 生产环境可通过 DATABASE_URL 切换 PostgreSQL（示例：postgresql+psycopg2://user:pass@host:5432/dbname）
    database_url: str = ""
    # 可选：execution_kernel 专用 DB（通常为 postgresql+asyncpg）；为空则复用 DATABASE_URL / 默认 platform.db（EXECUTION_KERNEL_DB_URL）
    execution_kernel_db_url: str = ""
    # 连接池参数（适配 10+ 并发）
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 1800
    # 从池中获取连接的最大等待（秒）；PostgreSQL 等池化后端生效，SQLite 文件库通常不显式传入
    db_pool_timeout_seconds: float = Field(default=30.0, ge=1.0, le=600.0)
    # PostgreSQL：TCP 连接超时（秒）；仅非 SQLite 时注入 psycopg2/asyncpg
    db_connect_timeout_seconds: int = Field(default=10, ge=1, le=120)
    # PostgreSQL：语句超时（毫秒），0 表示不通过连接参数覆盖（使用服务端默认）
    db_statement_timeout_ms: int = Field(default=60000, ge=0, le=86400000)

    # 文件读取工具：允许的绝对路径根目录（逗号分隔）。在此列表下的绝对路径可被 file.read 读取。
    # 例如："/" 表示允许本机任意目录；"/Users/tony,/data" 表示仅允许这两棵目录。
    # 为空时默认仅允许当前用户主目录。
    file_read_allowed_roots: str = "~"
    # 生产环境下 file.read 强制根目录（建议仅业务数据目录）
    production_file_read_required_roots: str = "./data"
    # 生产环境允许的 file.read 根目录白名单
    production_file_read_allowed_roots: str = "./data,/app/data,/app/backend/data"

    # -------------------------
    # Tool permissions (Local-first & Privacy-first)
    # -------------------------
    # HTTP tools: default disabled; enable explicitly for private deployments.
    tool_net_http_enabled: bool = False
    # Optional allowlist (comma-separated). Supports exact host match and suffix match via "*.example.com".
    # Empty means "no host restrictions" when tool_net_http_enabled is True.
    tool_net_http_allowed_hosts: str = ""
    # 是否允许访问私网/环回/链路本地目标（默认禁止，防 SSRF）
    tool_net_http_allow_private_targets: bool = False
    # Agent 创建/更新时是否允许高危内置技能（python/shell/写文件等）
    agent_allow_dangerous_skills: bool = False
    # Agent 文件上传并发上限（run/with-files）
    agent_upload_max_concurrency: int = 4

    # Web search (DuckDuckGo). Default below; optional override via env TOOL_NET_WEB_ENABLED (no .env required).
    tool_net_web_enabled: bool = True
    # Optional: WEB_SEARCH_SERPER_API_KEY for Google search (Serper). If set, uses Serper instead of DuckDuckGo.
    web_search_serper_api_key: str = ""
    # 可选：通过 Vault Agent/Secret Manager 注入的环境变量名
    web_search_serper_api_key_vault_env: str = "VAULT_WEB_SEARCH_SERPER_API_KEY"
    # 可选：从文件加载密钥（例如 /vault/secrets/serper_api_key）
    web_search_serper_api_key_file: str = ""
    # 可选：密文 token（Fernet），运行时用 PERILLA_ENV_ENCRYPTION_KEY 解密
    web_search_serper_api_key_encrypted: str = ""

    # system.env tool is sensitive (may leak secrets): default disabled.
    tool_system_env_enabled: bool = False
    # Allowlist env var names (comma-separated). Empty means "deny all names" unless tool_system_env_enabled is True and name is explicitly allowed.
    tool_system_env_allowed_names: str = ""
    # Whether system.env may return all variables (very sensitive). Default: False.
    tool_system_env_allow_all: bool = False

    # 模型存储目录
    local_model_directory: str = "~/.local-ai/models/"

    # YOLO 目标检测模型路径（可选，为空则使用 local_model_directory/perception/YOLOv8/yolov8s.pt）
    yolo_model_path: str = ""
    # YOLO 运行设备：cpu / cuda / mps / auto（auto 自动选择 cuda > mps > cpu）
    yolo_device: str = "mps"
    # YOLO 默认 backend：yolov8 / yolov11 / onnx
    yolo_default_backend: str = "yolov8"
    # 文生图默认模型 ID（可选，为空则按运行时可用模型自动选择）
    image_generation_default_model_id: str = ""

    # 本地模型切换时是否自动卸载上一个模型（默认关闭，避免频繁冷启动）
    auto_unload_local_model_on_switch: bool = False
    # 运行时资源回收（通用）
    runtime_auto_release_enabled: bool = True
    # 缓存本地重模型的上限（超出后回收最久未使用模型）
    runtime_max_cached_local_runtimes: int = 3
    # 按模型类型拆分的缓存上限；未配置时回退到 runtime_max_cached_local_runtimes
    runtime_max_cached_local_llm_runtimes: int = 3
    runtime_max_cached_local_vlm_runtimes: int = 3
    runtime_max_cached_local_image_generation_runtimes: int = 3
    # Redis 推理缓存
    inference_cache_enabled: bool = True
    inference_cache_redis_url: str = "redis://127.0.0.1:6379/0"
    inference_cache_prefix: str = "perilla:inference"
    # 启动时将 Redis 中旧前缀 openvitamin:* SCAN+RENAME 到当前 inference/event/kbvec 配置前缀（幂等）
    redis_legacy_openvitamin_prefix_migrate_on_startup: bool = True
    # True：推理缓存、事件总线、KB 向量快照等使用 Redis Cluster 客户端（URL 指向任一可访问节点即可）
    redis_cluster_mode: bool = False
    # L1: 内存缓存（优先读）+ Redis（次级回源）
    inference_cache_memory_enabled: bool = True
    inference_cache_memory_max_entries: int = 2048
    # 相同模型+相同请求缓存 5 分钟
    inference_cache_ttl_seconds: int = 300
    # 智能路由（负载感知 + 灰度/蓝绿）
    inference_smart_routing_enabled: bool = True
    # 示例：
    # {"reasoning-model":{"strategy":"blue_green","stable":"deepseek-r1","candidate":"deepseek-r1-v2","candidate_percent":10}}
    inference_smart_routing_policies_json: str = ""
    # 推理队列 SLO 感知调度与抢占策略
    inference_queue_slo_enabled: bool = True
    inference_queue_slo_high_ms: int = 3000
    inference_queue_slo_medium_ms: int = 6000
    inference_queue_slo_low_ms: int = 10000
    inference_queue_preemption_enabled: bool = True
    inference_queue_preemption_max_per_high_request: int = 1
    inference_queue_preemption_max_per_task: int = 2
    inference_queue_preemption_cooldown_ms: int = 300
    # 前端 SLO 看板阈值（可在系统设置中动态调整）
    inference_priority_panel_high_slo_critical_rate: float = 0.95
    inference_priority_panel_high_slo_warning_rate: float = 0.99
    inference_priority_panel_preemption_cooldown_busy_threshold: int = 10
    # 按模型类型覆盖 TTL（JSON），例如 {"llm":900,"vlm":300}
    inference_cache_ttl_by_model_type_json: str = "{\"llm\":900,\"vlm\":300,\"embedding\":86400}"
    # 全量清理挑战码有效期（秒）
    inference_cache_clear_challenge_ttl_seconds: int = 120
    # 挑战码申请限流窗口与阈值
    inference_cache_clear_challenge_rate_window_seconds: int = 60
    inference_cache_clear_challenge_rate_max_per_window: int = 5
    # Embedding 缓存 24 小时
    embedding_cache_ttl_seconds: int = 86400
    # 事件总线（跨模块异步通信）
    event_bus_enabled: bool = False
    event_bus_backend: str = "redis"  # redis | kafka | inprocess
    event_bus_redis_url: str = "redis://127.0.0.1:6379/1"
    event_bus_channel_prefix: str = "perilla:event"
    event_bus_handler_retry_attempts: int = 1
    event_bus_handler_retry_delay_ms: int = 200
    event_bus_dlq_max_items: int = 200
    event_bus_replay_max_batch: int = 100
    event_bus_replay_min_interval_ms: int = 1000
    # Kafka 事件总线（需 pip install aiokafka；event_bus_backend=kafka 且配置 bootstrap）
    event_bus_kafka_bootstrap_servers: str = ""
    event_bus_kafka_topic_prefix: str = "perilla.events"
    event_bus_kafka_consumer_group: str = "perilla-event-bus"
    # 启动时对 Kafka bootstrap 做 TCP 连通探测（仅 backend=kafka 且已配置 bootstrap）；秒
    event_bus_kafka_ping_timeout_seconds: float = Field(default=3.0, gt=0, le=120)
    # 为 True 时：配置的跨进程后端（redis/kafka）若未挂载到 composite bus（初始化失败等），启动直接失败
    event_bus_strict_startup: bool = False
    # 启动时对 EVENT_BUS_REDIS_URL 做 PING（仅 backend=redis）；超时秒数
    event_bus_redis_ping_timeout_seconds: float = Field(default=2.0, gt=0, le=120)
    # 为 True 时：/api/health/ready 在事件总线降级时返回 HTTP 503（便于编排 readiness 摘流量）
    health_ready_strict_event_bus: bool = False
    # 为 True 且 inference_cache_enabled：推理缓存 Redis PING 失败时 /ready 返回 503（生产共池 Redis 时常开）
    health_ready_strict_inference_redis: bool = False
    health_ready_inference_redis_ping_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    # False：非 strict 时不做推理缓存 PING（降负载）；strict 仍会 PING
    health_ready_inference_redis_probe_enabled: bool = True
    # 非 strict 时复用最近一次 PING 结果（秒），减轻大规模副本下对 Redis 的 QPS；0 表示每次请求都 PING
    health_ready_inference_redis_probe_cache_seconds: float = Field(default=5.0, ge=0, le=120)
    # MCP Streamable HTTP：GET SSE 上服务端推送是否发到事件总线（mcp.streamable.server_rpc，仅摘要payload）
    mcp_http_emit_server_push_events: bool = True
    # 知识库向量索引 Redis 快照（用于重启后快速恢复向量表）
    kb_vector_snapshot_redis_enabled: bool = True
    kb_vector_snapshot_redis_prefix: str = "perilla:kbvec"
    # Prometheus：并行注册旧指标名 openvitamin_*（与 perilla_* 同步更新），便于过渡期仪表盘与告警
    metrics_legacy_openvitamin_names_enabled: bool = True
    # 文档类型分块大小覆盖（JSON），例如 {"pdf":256,"md":512}
    kb_chunk_size_overrides_json: str = "{\"pdf\":256,\"md\":512,\"txt\":256,\"docx\":384}"
    # 空闲回收阈值（秒）
    runtime_release_idle_ttl_seconds: int = 300
    # 自动回收最小触发间隔（秒），用于抑制并发尖峰抖动
    runtime_release_min_interval_seconds: int = 5
    # Agent Plan 并行工具调用上限（parallel_calls 与 parallel_group 批内并发共用上限）
    agent_plan_max_parallel_steps: int = 4
    # 步骤默认不超时；>0 时作为 PlanBasedExecutor 的全局单步超时时长（秒）
    agent_step_default_timeout_seconds: Optional[float] = None
    # 无 Step/Plan 配置时的默认重试次数与间隔
    agent_step_default_max_retries: int = 0
    agent_step_default_retry_interval_seconds: float = 1.0
    # V2.9 按 runtime 类型的并发上限覆盖（JSON 对象，如 {"llama.cpp": 1, "ollama": 4}）。为空则使用代码默认 MODEL_RUNTIME_CONFIG。
    runtime_max_concurrency_overrides: str = ""
    # 连续动态批处理（非流式 chat）
    continuous_batch_enabled: bool = True
    continuous_batch_wait_ms: int = 12
    continuous_batch_max_size: int = 8
    # 异步 chat 任务查询缓存
    async_chat_job_ttl_seconds: int = 1800
    async_chat_job_max_entries: int = 2000

    # 技能语义发现（SkillDiscoveryEngine）：混合排序中「标签匹配」权重，其余为语义余弦（两者之和为 1）
    skill_discovery_tag_match_weight: float = 0.3
    # 仅保留余弦相似度 >= 该值的候选（0 表示不启用下限过滤）
    skill_discovery_min_semantic_similarity: float = 0.0
    # 仅保留混合分 >= 该值的候选（0 表示不启用）
    skill_discovery_min_hybrid_score: float = 0.0
    # model.json 备份根目录，为空则使用 backend/data/backups（与 DB 备份目录并列时其下为 model_json/）
    model_json_backup_directory: str = ""
    # model.json 定时全量快照：是否启用、每日执行时间（UTC，如 "02:00" 或 "02:00:00"）
    model_json_backup_daily_enabled: bool = False
    model_json_backup_daily_time: str = "02:00"
    # MPS 内存压力阈值（current/recommended），超阈值触发积极回收
    runtime_mps_pressure_threshold: float = 0.85
    # Torch VLM HF 流式：generate 线程 join 超时（秒）；超时仍存活则记结构化错误日志（无法强制终止 CUDA kernel）
    torch_stream_thread_join_timeout_sec: int = 600
    # Torch VLM 流式异步桥接队列是否限制深度：0 表示不限制（等同无限队列，依赖下游消费速度）
    torch_stream_chunk_queue_max: int = 0

    # 系统内存压力阈值（psutil.virtual_memory().percent），超阈值触发积极回收
    # 用于覆盖 llama.cpp 等不计入 torch.mps 统计的内存占用场景。
    runtime_ram_pressure_threshold: float = 85.0
    # 启动时将超过该阈值的 running 会话标记为 error（秒）
    agent_stale_running_session_seconds: int = 1800

    # execution_kernel 调度器：单实例内 DAG 可并行节点同时执行上限（与 Agent 并行上限取 min）
    workflow_scheduler_max_concurrency: int = Field(default=10, ge=1, le=256)
    # Workflow wait=true 同步等待超时（秒）
    workflow_wait_timeout_seconds: int = 120
    # Workflow wait=true 允许的最大超时上限（秒）
    workflow_wait_timeout_max_seconds: int = 3600
    # Workflow 执行接口默认等待策略（False=默认异步）
    workflow_execution_wait_default: bool = False
    # 是否允许执行未发布（draft）版本；关闭后仅允许 published 版本执行
    # 生产建议：False。调试环境可通过 debug 覆盖开关放开。
    workflow_allow_draft_execution: bool = False
    # 当 debug=True 且 workflow_allow_draft_execution=False 时，是否允许调试环境自动放开 draft 执行
    workflow_allow_draft_execution_debug_override: bool = True
    # 无已发布版本时回退 draft 的告警最小间隔（秒）
    workflow_draft_fallback_warn_interval_seconds: float = 60.0
    # Workflow 持久化写入重试（SQLite 锁冲突）
    workflow_db_write_retry_attempts: int = 4
    workflow_db_write_retry_base_delay_ms: int = 50
    # Workflow 跨进程并发兜底（基于 DB running 数量的软限制）
    workflow_distributed_running_limit_enabled: bool = True
    workflow_distributed_running_limit_per_workflow: int = 3
    workflow_distributed_running_limit_wait_seconds: float = 15.0
    # 分布式并发兜底等待超时后是否 fail-open 继续执行（True 可避免直接失败）
    workflow_distributed_running_limit_fail_open: bool = True
    # 视为“陈旧 running”并在分布式并发限流时忽略/回收的阈值（秒）
    workflow_distributed_running_stale_seconds: int = 1800
    # 分布式并发限流检查时，是否自动将陈旧 running 回收为 failed
    workflow_distributed_running_auto_reconcile_stale: bool = True
    # 子工作流最大嵌套深度（父=0，子=1）
    workflow_subworkflow_max_depth: int = 5
    # 生产环境（debug=False）是否允许子工作流使用 latest 引用策略
    workflow_allow_latest_subworkflow_in_production: bool = False
    # 发布子工作流新版本时，若检测到 breaking 影响已发布父流程则阻断发布
    workflow_block_publish_on_subworkflow_breaking_impact: bool = True
    # 契约兼容策略：新增 required 入参是否视为 breaking（否则视为 risky）
    workflow_contract_required_input_added_breaking: bool = True
    # 契约兼容策略：新增输出字段是否视为 risky（否则为 info）
    workflow_contract_output_added_risky: bool = True
    # 契约兼容策略：逗号分隔字段豁免（支持 input.foo / output.bar）
    workflow_contract_field_exemptions: str = ""
    # Reflector 默认重试策略（全局），节点可覆盖
    workflow_reflector_max_retries: int = 0
    workflow_reflector_retry_interval_seconds: float = 1.0
    workflow_reflector_fallback_agent_id: str = ""
    # Reflector 治理成熟度阈值（前端巡检/软门禁）
    workflow_governance_healthy_threshold: float = 0.1
    workflow_governance_warning_threshold: float = 0.3
    # Workflow 执行长期 pending 告警（秒）
    workflow_pending_warn_seconds: float = 8.0
    # Workflow 执行 pending 告警重复间隔（秒）
    workflow_pending_warn_interval_seconds: float = 5.0
    # Workflow approvals legacy response deprecation headers
    workflow_approvals_legacy_deprecated_header: str = "approvals-legacy-format"
    workflow_approvals_legacy_sunset: str = "Wed, 31 Dec 2026 23:59:59 GMT"

    # 长期记忆（MVP）
    enable_long_term_memory: bool = False
    memory_inject_mode: str = "recent"  # recent | keyword | vector
    memory_inject_top_k: int = 5

    # 向量检索（sqlite-vec 优先，失败则自动降级 python cosine）
    memory_vector_enabled: bool = True
    memory_embedding_dim: int = 256
    memory_default_confidence: float = 0.6

    # 冲突/合并/衰减（MVP）
    memory_merge_enabled: bool = True
    memory_merge_similarity_threshold: float = 0.92
    memory_conflict_enabled: bool = True
    memory_conflict_similarity_threshold: float = 0.85
    memory_decay_half_life_days: int = 30

    # 结构化 Memory Key Schema（确定性）
    memory_key_schema_enforced: bool = True
    memory_key_schema_allow_unlisted: bool = False

    # 记忆提取器（使用 OpenAI 兼容 chat/completions）
    memory_extractor_enabled: bool = False
    memory_extractor_temperature: float = 0.0
    memory_extractor_top_p: float = 1.0
    memory_extractor_max_tokens: int = 256

    # Chat 持久化策略：
    # - off: 不创建会话/不落库，仅做推理
    # - minimal: 仅在有有效 user_text 且推理成功时落库，避免中间态噪声
    # - full: 完整记录（默认）
    chat_persistence_mode: str = "full"
    # 无 X-Session-Id 时，复用最近活跃会话窗口（分钟）。0 表示不复用。
    chat_session_reuse_window_minutes: int = 15
    # 自动生成会话标题的最大长度
    chat_session_title_max_len: int = 50
    # 幂等键 header（逗号分隔），用于防重写入
    chat_idempotency_headers: str = "Idempotency-Key,X-Request-Id"
    # 强制新会话 header（逗号分隔）；命中后跳过会话复用逻辑
    chat_force_new_session_headers: str = "X-Force-New-Session,X-New-Chat"
    # 输入清洗：剥离上游传输层包装文本（如 sender metadata 包裹）
    chat_input_strip_transport_wrappers: bool = True
    # 输出清洗：剥离推理思维链外显（<think>...</think> / 思维前缀）
    chat_output_strip_reasoning: bool = True
    # 流式断点续传：断连后继续生成并缓冲 SSE，客户端可携带 chunk_index 恢复拉取
    chat_stream_resume_enabled: bool = True
    chat_stream_resume_ttl_seconds: int = 600
    chat_stream_resume_max_sessions: int = 500
    chat_stream_resume_wait_timeout_seconds: int = 120
    # Chat SSE 墙钟上限（秒）：从首 token 起算，含等待下一 chunk 的时间；0 表示不限制
    chat_stream_wall_clock_max_seconds: int = 0
    # 断点续传开启时：客户端断连后是否立即停止上游（默认 False=继续生成直至结束以便 resume 缓冲完整）
    chat_stream_resume_cancel_upstream_on_disconnect: bool = False
    # HTTP 响应 GZip（GZip 中间件对 text/event-stream 不压缩；SSE 请用 ChatCompletionRequest.stream_gzip）
    response_gzip_enabled: bool = True
    response_gzip_minimum_size: int = 256
    # Auto 选模是否强制本地优先（存在本地候选时仅在本地中选择）
    model_selector_auto_local_first_strict: bool = True
    # 文生图任务队列：每个模型最多允许 queued+running 的任务数
    image_generation_max_pending_jobs_per_model: int = 4

    # API 可观测性与治理（enhanced）
    # 日志输出格式：text | json（生产建议 json）
    log_format: str = "text"
    # 日志级别：为空时按 debug 自动选择（debug=True => DEBUG，False => INFO）
    log_level: str = ""
    # 日志文件保留天数（按天轮转）
    log_backup_count: int = 30
    # 请求追踪：响应中返回 X-Request-Id，并输出请求耗时日志
    request_trace_enabled: bool = True
    request_trace_header_name: str = "X-Request-Id"
    # Prometheus 指标端点
    prometheus_enabled: bool = True
    prometheus_metrics_path: str = "/metrics"
    # 简化限流：每个窗口内允许的请求数。<=0 时关闭限流。
    api_rate_limit_enabled: bool = True
    api_rate_limit_requests: int = 120
    api_rate_limit_window_seconds: int = 60
    # 单用户并发请求上限（防止个别用户占满资源）
    api_rate_limit_user_max_concurrent_requests: int = 5
    # 限流身份优先级：API Key Header >（若启用）X-Forwarded-For 首跳 > Client IP
    # 直连公网或未信任反代时设为 false，避免客户端伪造 X-Forwarded-For 绕过限流；审计日志 client_ip 与同开关一致
    api_rate_limit_trust_x_forwarded_for: bool = True
    api_rate_limit_api_key_header: str = "X-Api-Key"
    # 非空时使用 Redis 共池限流（多副本）；为空则仅进程内计数
    api_rate_limit_redis_url: str = ""
    # Redis 键前缀（ standalone / cluster 均适用）
    api_rate_limit_redis_key_prefix: str = "perilla:ratelimit"
    # Execution Kernel：对 /api/events* 使用独立窗口计数（同一 api_rate_limit_window_seconds）。
    # 为 0 时不启用专用配额（与全局 api_rate_limit_requests 共用同一计数键）。
    # 生产可对观测类密集读路径单独收紧（例如 30～60），键前缀 ev: 与全局 identity 隔离。
    api_rate_limit_events_requests: int = 0
    api_rate_limit_events_path_prefix: str = "/api/events"
    # 为 True 且配置了 Redis URL：Redis 故障时不放行请求，返回 503（默认 False：fail-open）
    api_rate_limit_redis_fail_closed: bool = False
    api_rate_limit_redis_ping_timeout_seconds: float = Field(default=2.0, gt=0, le=120)
    # /ready 中对 API 限流 Redis 做 PING（与 fail_closed 正交；可与 inference Redis 分开实例）
    health_ready_strict_api_rate_limit_redis: bool = False
    health_ready_api_rate_limit_redis_probe_enabled: bool = True
    health_ready_api_rate_limit_redis_probe_cache_seconds: float = Field(default=5.0, ge=0, le=300)

    # ---------- RBAC（平台角色，与 Workflow ACL 正交）----------
    rbac_enabled: bool = False
    # 开启后对 viewer 拒绝写控制面（见 middleware/rbac_enforcement.py）
    rbac_enforcement: bool = False
    # 未匹配任何 API Key 时的默认角色：operator | viewer | admin（不推荐默认 admin）
    rbac_default_role: str = "operator"
    # 逗号分隔的 API Key 列表（与 api_rate_limit_api_key_header 使用同一 Header 名）
    rbac_admin_api_keys: str = ""
    rbac_operator_api_keys: str = ""
    rbac_viewer_api_keys: str = ""

    # ---------- 审计日志 ----------
    audit_log_enabled: bool = False
    # 逗号分隔路径前缀；匹配则记录（响应完成后写入 audit_logs）
    # 逗号分隔；/api/v1/audit 由中间件硬编码排除，避免自引用写放大
    # 合规场景可将 /api/events 加入前缀并开启 audit_log_include_get 以审计观测读路径
    audit_log_path_prefixes: str = "/api/v1/workflows"
    # 是否记录 GET（默认仅写操作语义上已包含 GET 时需显式打开）
    audit_log_include_get: bool = False

    # ---------- Trace 链路（与 request_id 对齐；支持 traceparent）----------
    trace_link_enabled: bool = True

    # ---------- 生产化补强（P0/P1 baseline）----------
    # 1) API Key scope: JSON 字典，key 为 API Key，value 为 scope 列表
    # 示例: {"k-admin":["admin","audit:read"],"k-ro":["read"]}
    api_key_scopes_json: str = "{}"
    # API Key 注册表（细粒度权限）：JSON 字典，key 为 API Key
    # value 示例：
    # {
    #   "scopes": ["agent:read","knowledge:read"],
    #   "expires_at": "2026-12-31T23:59:59Z",
    #   "revoked": false,
    #   "resources": {"agent_ids":["agent_a"], "knowledge_base_ids":["kb_a"]}
    # }
    api_keys_json: str = "{}"
    # 静态吊销列表（逗号分隔），用于紧急失效
    api_key_revoked_list: str = ""
    # 2) 多租户隔离：默认租户与强制开关
    tenant_enforcement_enabled: bool = False
    tenant_default_id: str = "default"
    tenant_header_name: str = "X-Tenant-Id"
    # API Key 与租户绑定校验（JSON：{"api-key-1":["tenant-a"],"api-key-2":["*"]}）
    tenant_api_key_binding_enabled: bool = False
    tenant_api_key_tenants_json: str = "{}"
    # Execution Kernel /events：无 workflow_executions(graph_instance_id) 行时是否拒绝访问（True=仅允许已登记实例）
    events_strict_workflow_binding: bool = False
    # /api/events：是否要求 X-Api-Key + 平台 admin（与 system/mcp 控制面对齐；本地可调 false）
    events_api_require_authenticated: bool = False
    # 6) CORS 白名单（逗号分隔）。为空时由 main.py 回退到 http://localhost 与 http://127.0.0.1，而非通配 "*"
    cors_allowed_origins: str = ""
    # 7) CSRF（双提交 Cookie）：对非安全方法校验 X-CSRF-Token 与 csrf cookie 一致
    csrf_enabled: bool = True
    csrf_header_name: str = "X-CSRF-Token"
    csrf_cookie_name: str = "csrf_token"
    csrf_cookie_path: str = "/"
    csrf_cookie_samesite: str = "lax"
    csrf_cookie_secure: bool = False
    csrf_cookie_max_age_seconds: int = 86400
    # 生产安全护栏是否严格阻断启动（False=仅告警）
    security_guardrails_strict: bool = True

    # ---------- 输入校验与脱敏 ----------
    # 对外 API body 顶层字段白名单校验（基于对应 Pydantic 请求模型）
    api_request_whitelist_enabled: bool = True
    # 全局敏感字段脱敏（请求/响应 JSON）
    data_redaction_enabled: bool = True
    # 逗号分隔关键字；字段名包含任一关键字即脱敏
    data_redaction_sensitive_fields: str = (
        "api_key,password,secret,token,authorization,access_token,refresh_token,"
        "client_secret,private_key"
    )
    data_redaction_mask_keep_prefix: int = 4
    data_redaction_mask_keep_suffix: int = 4

    @field_validator("log_format")
    @classmethod
    def _validate_log_format(cls, v: object) -> str:
        s = str(v or "text").strip().lower()
        if s not in ("text", "json"):
            raise ValueError("log_format must be 'text' or 'json'")
        return s

    @field_validator("prometheus_metrics_path")
    @classmethod
    def _validate_prometheus_metrics_path(cls, v: object) -> str:
        s = str(v or "/metrics").strip() or "/metrics"
        if not s.startswith("/"):
            raise ValueError("prometheus_metrics_path must start with /")
        if ".." in s:
            raise ValueError("prometheus_metrics_path must not contain '..'")
        if any(c in s for c in "\n\r\0"):
            raise ValueError("prometheus_metrics_path contains invalid characters")
        return s

    model_config = SettingsConfigDict(env_file=".env")

    def model_post_init(self, __context: object) -> None:
        if self.web_search_serper_api_key:
            return

        vault_env_name = (self.web_search_serper_api_key_vault_env or "").strip()
        if vault_env_name:
            vault_value = (os.environ.get(vault_env_name) or "").strip()
            if vault_value:
                self.web_search_serper_api_key = vault_value
                return

        secret_file = (self.web_search_serper_api_key_file or "").strip()
        if secret_file:
            secret_path = Path(secret_file).expanduser()
            if secret_path.is_file():
                self.web_search_serper_api_key = secret_path.read_text(encoding="utf-8").strip()
                if self.web_search_serper_api_key:
                    return

        encrypted_token = (self.web_search_serper_api_key_encrypted or "").strip()
        encryption_key = (os.environ.get("PERILLA_ENV_ENCRYPTION_KEY") or "").strip()
        if encrypted_token and encryption_key:
            try:
                from cryptography.fernet import Fernet

                self.web_search_serper_api_key = (
                    Fernet(encryption_key.encode("utf-8"))
                    .decrypt(encrypted_token.encode("utf-8"))
                    .decode("utf-8")
                    .strip()
                )
            except Exception as exc:
                raise RuntimeError("Failed to decrypt WEB_SEARCH_SERPER_API_KEY_ENCRYPTED") from exc


# 全局配置实例
settings = Settings()
