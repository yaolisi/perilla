# 公网 SaaS · 多租户 · 上线门禁（工程 Gate）

适用范围：**面向互联网的托管服务**、**完整 SaaS 商业化路径**、**多租户数据与配额隔离**。本文档为上线前评审与签字用的检查清单；与后端 **`validate_production_security_guardrails`**、**`apply_production_security_defaults`**（`backend/config/settings.py`，生产 `DEBUG=false` 启动路径）、Helm Chart **`deploy/helm/perilla-backend`**、根目录 **`docker-compose.prod.yml`** 对齐。

---

## 如何使用

1. **P0**：未勾选完毕不得视为「生产可面向公网租户开放」。  
2. **P1**：可在首发后 30～90 天内补齐，但须有 owner 与截止时间。  
3. **代码门禁**：配置项以环境变量 / Helm `values` / Secret 为准；后端启动若 **`SECURITY_GUARDRAILS_STRICT=true`** 且 **`DEBUG=false`**，高危组合会直接 **拒绝启动**（见日志 `[SecurityBaseline] BLOCKED`）。

---

## P0 — 边界与传输（公网必选）

| # | 检查项 | 落地要点 |
|---|--------|----------|
| P0-1 | 全站 HTTPS | Ingress / CDN TLS；后端 **`SECURITY_HEADERS_STRICT_TRANSPORT_SECURITY`** 仅在 **HTTPS 终端** 启用（见 `settings.security_headers_*`）。 |
| P0-2 | Host 与伪造请求头 | **`TRUSTED_HOSTS`**；探针/指标路径豁免策略见 **`trusted_host_exempt_ops_paths`**（`middleware/trusted_host.py`）。 |
| P0-3 | 转发信任范围 | **`FORWARDED_ALLOW_IPS`** / **`UVICORN_FORWARDED_ALLOW_IPS`**：仅列入可信反代网段；`**` 仅限可控 ingress 后（启动日志中有风险提示）。 |
| P0-4 | CORS | **`CORS_ALLOWED_ORIGINS`**：仅列出租户控制台等 **`https://` 源**；门禁禁止生产使用 `*` 及非 localhost 的明文 `http://`。 |
| P0-5 | 请求体上限 | **`HTTP_MAX_REQUEST_BODY_BYTES`** 与 Ingress **`client_max_body_size`** 一致；生产默认由 apply 收敛（未配置非 0 时）。 |

---

## P0 — 身份、RBAC、租户

| # | 检查项 | 落地要点 |
|---|--------|----------|
| P0-6 | RBAC 密钥 | **`RBAC_ADMIN_API_KEYS` / `RBAC_OPERATOR_API_KEYS` / `RBAC_VIEWER_API_KEYS`**：至少一项非空；分段长度与占位符门禁见 `settings`。 |
| P0-7 | 默认角色 | **`RBAC_DEFAULT_ROLE=viewer`**（匿名/未带 Key 回落）；禁止生产长期 **`operator`**（门禁拦截）。 |
| P0-8 | 租户强制与绑定 | **`TENANT_ENFORCEMENT_ENABLED`**、**`TENANT_API_KEY_BINDING_ENABLED`**；Key→租户映射 **`tenant_api_key_tenants_json`** / Secret。 |
| P0-9 | 租户隔离（业务层） | **每条查询与写入携带 tenant_id**；会话、知识库、工作流、计费实体等均须在 ORM/仓库层过滤；本清单无法代替代码评审。 |

---

## P0 — 滥用防护与配额（SaaS）

| # | 检查项 | 落地要点 |
|---|--------|----------|
| P0-10 | 分布式限流 | **`API_RATE_LIMIT_REDIS_URL`**；生产默认 **`API_RATE_LIMIT_REDIS_FAIL_CLOSED`**、**`/ready` 对限流 Redis 严格**（apply 在已配 URL 时收紧）。 |
| P0-11 | 限流维度 | 按产品决策：**IP / API Key / Tenant**；与 **`API_RATE_LIMIT_TRUST_X_FORWARDED_FOR`** 协同（直连公网常为 false）。 |
| P0-12 | 推理资源 | 单租户并发、流式墙钟、队列优先级等与商务套餐一致；避免单租户占满共享池。 |

---

## P0 — 数据、密钥、日志

| # | 检查项 | 落地要点 |
|---|--------|----------|
| P0-13 | PostgreSQL | **`DATABASE_URL`** 生产须 Postgres；禁止 SQLite；DSN 口令非占位（门禁）。 |
| P0-14 | 结构化脱敏 | **`DATA_REDACTION_ENABLED=true`**（门禁）。 |
| P0-15 | 审计 | **`AUDIT_LOG_ENABLED`** 与 **`AUDIT_LOG_PATH_PREFIXES`**：覆盖租户账单相关控制面写操作（路径勿单独 **`/`**）。 |
| P0-16 | Secret | DB/Redis/API Key 仅存 Secret/Vault；镜像与 CI 无明文密钥。 |

---

## P0 — 依赖 Redis/Kafka 的运行时一致性

| # | 检查项 | 落地要点 |
|---|--------|----------|
| P0-17 | 事件总线 | **`EVENT_BUS_ENABLED=true`** 时 **`EVENT_BUS_STRICT_STARTUP=true`**（门禁）；Redis/Kafka URL 与 backend 一致。 |
| P0-18 | 推理缓存 | **`INFERENCE_CACHE_ENABLED=true`** 时建议 **`HEALTH_READY_STRICT_INFERENCE_REDIS=true`**（apply 默认收紧）；与 **`INFERENCE_CACHE_REDIS_URL`** 就绪摘除协同。 |
| P0-19 | 流式断连 | **`CHAT_STREAM_RESUME_CANCEL_UPSTREAM_ON_DISCONNECT`**（apply 默认 true）：减少僵尸推理。 |

---

## P0 — 暴露面减缩

| # | 检查项 | 落地要点 |
|---|--------|----------|
| P0-20 | OpenAPI / 文档 | 公网默认 **`OPENAPI_PUBLIC_ENABLED=false`** 或由 Ingress 限制网段（门禁对生产开启为 true 会拦截）。 |
| P0-21 | 安全响应头 | **`SECURITY_HEADERS_ENABLED`**（apply 默认 true）；iframe 需求时调整 **`SECURITY_HEADERS_X_FRAME_OPTIONS`**。 |
| P0-22 | CSRF | 浏览器 Cookie 场景保持 **`CSRF_ENABLED`**；**`CSRF_COOKIE_SECURE`** 在 HTTPS 终端为 true。 |

---

## P0 — 合规与产品（SaaS 对外承诺）

| # | 检查项 | 落地要点 |
|---|--------|----------|
| P0-23 | 隐私与条款 | 对外隐私政策、DPA、子处理方列表；数据驻留与跨境说明。 |
| P0-24 | 租户数据生命周期 | 退订/删除 **SLA**；导出能力范围与接口（产品+法务定稿）。 |

---

## P1 — 上线后 30～90 天（建议有 owner）

- WAF / Bot / DDoS 与限流分层。  
- 密钥轮换 Runbook（RBAC、DB、Redis、Webhook）。  
- PostgreSQL 备份、PITR、**季度恢复演练**记录。  
- 告警与 on-call：5xx、延迟、**`/ready` 失败**、Redis/DB 连接。  
- 依赖与镜像：CVE 扫描与修复 SLA。  
- 多 AZ / 灾备（按 SLA 承诺）。

---

## 相关代码与部署路径（索引）

| 主题 | 路径 |
|------|------|
| 租户头强制路径前缀（HTTP 层，与工作流/审计/系统控制面对齐） | `backend/middleware/tenant_paths.py`：`is_tenant_enforcement_protected_path` |
| 生产门禁与默认值 | `backend/config/settings.py`：`validate_production_security_guardrails`、`apply_production_security_defaults` |
| 启动顺序 | `backend/main.py`：`_apply_security_baseline`、`_log_production_operational_warnings` |
| Helm | `deploy/helm/perilla-backend/`（Chart **`values.yaml`**、`templates/deployment.yaml`） |
| Compose 生产叠加 | `docker-compose.prod.yml` |

---

*本文档为工程检查清单，不构成法律意见；合规条款以法务与客户合同为准。*
