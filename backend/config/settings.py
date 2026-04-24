"""
配置设置
"""
from io import StringIO
import os
from pathlib import Path
from typing import Optional

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

    encryption_key = os.environ.get("OPENVITAMIN_ENV_ENCRYPTION_KEY", "").strip()
    encrypted_candidates = [
        backend_dir / ".env.encrypted",
        backend_dir.parent / ".env.encrypted",
    ]
    for encrypted_file in encrypted_candidates:
        if not encrypted_file.is_file():
            continue
        if not encryption_key:
            raise RuntimeError(
                f"Found encrypted env file but OPENVITAMIN_ENV_ENCRYPTION_KEY is empty: {encrypted_file}"
            )
        try:
            from cryptography.fernet import Fernet
        except Exception as exc:
            raise RuntimeError(
                "Encrypted env support requires python-dotenv[encrypted] / cryptography dependency"
            ) from exc
        cipher = Fernet(encryption_key.encode("utf-8"))
        decrypted = cipher.decrypt(encrypted_file.read_bytes()).decode("utf-8")
        parsed = dotenv_values(stream=StringIO(decrypted))
        for key, value in parsed.items():
            if key and value is not None:
                os.environ.setdefault(key, value)


def _normalize_roots(raw_roots: str) -> list[Path]:
    out: list[Path] = []
    for root in (raw_roots or "").split(","):
        trimmed = root.strip()
        if not trimmed:
            continue
        out.append(Path(trimmed).expanduser().resolve())
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
    required_roots = (getattr(s, "production_file_read_required_roots", "") or "").strip()
    if required_roots and (getattr(s, "file_read_allowed_roots", "") or "").strip() != required_roots:
        setattr(s, "file_read_allowed_roots", required_roots)
        changes.append("file_read_allowed_roots")
    return changes


def validate_production_security_guardrails(s: "Settings") -> list[str]:
    """
    在生产模式（debug=False）下校验高危配置，返回违规项列表。
    """
    issues: list[str] = []
    if getattr(s, "debug", True):
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
    if getattr(s, "tool_net_http_enabled", False) and (getattr(s, "tool_net_http_allowed_hosts", "") or "").strip() == "":
        issues.append("tool_net_http_allowed_hosts must be set when tool_net_http_enabled=True in production")
    return issues


class Settings(BaseSettings):
    """应用配置"""
    app_name: str = "OpenVitamin大模型与智能体应用平台"
    version: str = "1.0.0"
    api_prefix: str = "/api/v1"
    debug: bool = True
    
    # 服务器
    host: str = "0.0.0.0"
    port: int = 8000
    
    # 模型配置
    default_model: str = "llama-3-70b-instruct"
    
    # Ollama 配置
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = ""  # 为空则自动使用本地已下载的第一个模型

    # 数据库配置 (统一合并管理)
    db_path: str = ""  # 为空则使用默认 backend/data/platform.db
    # 生产环境可通过 DATABASE_URL 切换 PostgreSQL（示例：postgresql+psycopg2://user:pass@host:5432/dbname）
    database_url: str = ""
    # 连接池参数（适配 10+ 并发）
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 1800

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
    # 可选：密文 token（Fernet），运行时用 OPENVITAMIN_ENV_ENCRYPTION_KEY 解密
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
    inference_cache_prefix: str = "openvitamin:inference"
    # 相同模型+相同请求缓存 5 分钟
    inference_cache_ttl_seconds: int = 300
    # Embedding 缓存 24 小时
    embedding_cache_ttl_seconds: int = 86400
    # 空闲回收阈值（秒）
    runtime_release_idle_ttl_seconds: int = 300
    # 自动回收最小触发间隔（秒），用于抑制并发尖峰抖动
    runtime_release_min_interval_seconds: int = 5
    # Agent Plan 并行工具调用上限（仅对显式 parallel_calls 生效）
    agent_plan_max_parallel_steps: int = 4
    # V2.9 按 runtime 类型的并发上限覆盖（JSON 对象，如 {"llama.cpp": 1, "ollama": 4}）。为空则使用代码默认 MODEL_RUNTIME_CONFIG。
    runtime_max_concurrency_overrides: str = ""
    # model.json 备份根目录，为空则使用 backend/data/backups（与 DB 备份目录并列时其下为 model_json/）
    model_json_backup_directory: str = ""
    # model.json 定时全量快照：是否启用、每日执行时间（UTC，如 "02:00" 或 "02:00:00"）
    model_json_backup_daily_enabled: bool = False
    model_json_backup_daily_time: str = "02:00"
    # MPS 内存压力阈值（current/recommended），超阈值触发积极回收
    runtime_mps_pressure_threshold: float = 0.85
    # 系统内存压力阈值（psutil.virtual_memory().percent），超阈值触发积极回收
    # 用于覆盖 llama.cpp 等不计入 torch.mps 统计的内存占用场景。
    runtime_ram_pressure_threshold: float = 85.0
    # 启动时将超过该阈值的 running 会话标记为 error（秒）
    agent_stale_running_session_seconds: int = 1800

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
    # HTTP 响应 GZip（含流式 body；弱网可显著降低体积；前置代理请勿二次 gzip）
    response_gzip_enabled: bool = True
    response_gzip_minimum_size: int = 256
    # Auto 选模是否强制本地优先（存在本地候选时仅在本地中选择）
    model_selector_auto_local_first_strict: bool = True
    # 文生图任务队列：每个模型最多允许 queued+running 的任务数
    image_generation_max_pending_jobs_per_model: int = 4

    # API 可观测性与治理（enhanced）
    # 请求追踪：响应中返回 X-Request-Id，并输出请求耗时日志
    request_trace_enabled: bool = True
    request_trace_header_name: str = "X-Request-Id"
    # 简化限流：每个窗口内允许的请求数。<=0 时关闭限流。
    api_rate_limit_enabled: bool = True
    api_rate_limit_requests: int = 120
    api_rate_limit_window_seconds: int = 60
    # 单用户并发请求上限（防止个别用户占满资源）
    api_rate_limit_user_max_concurrent_requests: int = 5
    # 限流身份优先级：API Key Header > X-Forwarded-For > Client IP
    api_rate_limit_api_key_header: str = "X-Api-Key"

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
    # 6) CORS 白名单（逗号分隔）；为空时回退到 ["*"]（开发友好）
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
        encryption_key = (os.environ.get("OPENVITAMIN_ENV_ENCRYPTION_KEY") or "").strip()
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
