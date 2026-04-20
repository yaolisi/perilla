# OpenVitamin Enhanced 安全基线与审计规范

本文档用于统一团队在 **OpenVitamin Enhanced**（本仓库 / Standalone 分发目录可为 `openvitamin_enhanced_docker`）上的安全最小基线、配置要求、审计要求与变更流程。

---

## 1. 目标与适用范围

目标：

- 防止未授权访问与越权操作
- 防止跨租户数据访问
- 提供可追踪、可审计、可回放的安全证据
- 在高危配置下阻断启动，避免“带病上线”

适用范围：

- 后端网关（`backend/`）
- 配置与中间件
- Workflow / System / Audit 控制面接口
- CI 安全回归链路

---

## 2. 强制安全基线（MUST）

### 2.1 生产环境必须满足

- `DEBUG=false`
- `RBAC_ENABLED=true`
- `RBAC_ENFORCEMENT=true`
- `TENANT_ENFORCEMENT_ENABLED=true`
- `TENANT_API_KEY_BINDING_ENABLED=true`
- `TENANT_API_KEY_TENANTS_JSON` 非空且有效
- `RBAC_DEFAULT_ROLE=viewer`（避免匿名默认写权限）
- `API_KEY_SCOPES_JSON` 已配置且至少覆盖关键控制面 scope
- `CORS_ALLOWED_ORIGINS` 非空（显式白名单）
- `FILE_READ_ALLOWED_ROOTS` 不得为 `/`
- `TOOL_NET_HTTP_ENABLED=false`（默认）
- 若 `TOOL_NET_HTTP_ENABLED=true`，则 `TOOL_NET_HTTP_ALLOWED_HOSTS` 必须非空
- `TOOL_NET_HTTP_ALLOW_PRIVATE_TARGETS=false`
- `AGENT_ALLOW_DANGEROUS_SKILLS=false`
- `SECURITY_GUARDRAILS_STRICT=true`（默认建议）

### 2.2 启动阻断规则

在 `DEBUG=false` 时，命中以下任一项必须阻断启动：

1. `FILE_READ_ALLOWED_ROOTS="/"`  
2. `CORS_ALLOWED_ORIGINS=""`  
3. `TOOL_NET_HTTP_ENABLED=true` 且 `TOOL_NET_HTTP_ALLOWED_HOSTS=""`

说明：

- 该阻断由生产护栏逻辑执行（Fail-Fast）
- 仅在抢修应急、审批通过时允许临时设置 `SECURITY_GUARDRAILS_STRICT=false`

---

## 3. 认证、鉴权与授权规范

### 3.1 API Key 规范

- 所有控制面请求必须附带 `X-Api-Key`
- 不得在日志、返回体、错误消息中明文回显 API Key
- Key 应按环境与职责拆分（admin/operator/viewer）

### 3.2 RBAC 规范

- `viewer` 禁止写控制面（POST/PUT/PATCH/DELETE）
- `api/system` 全路由按敏感控制面处理，要求管理员身份
- 审计查询仅允许管理员

### 3.3 Tenant 规范

- 请求必须包含 `X-Tenant-Id`
- API Key 必须绑定允许租户列表
- 任何跨租户访问应返回 `403` 或 `404`（按策略）
- Workflow 访问必须经过入口校验 + 数据层 tenant-aware 查询双重控制
- 受保护控制面（如 `/api/system/*`）必须显式携带租户头，未携带应拒绝

### 3.4 CSRF 规范

- 所有写接口必须经过双提交 Cookie 校验（header token 与 cookie token 相等）
- 缺失或不一致返回 `403`
- 前端必须在启动时预热 token，并在写请求自动注入

---

## 4. 审计与追踪规范（MUST）

### 4.1 审计日志字段最低要求

- 时间戳（UTC）
- `tenant_id`
- `user_id` / 角色
- HTTP 方法、路径、状态码
- `request_id`、`trace_id`
- 客户端来源（脱敏后）

### 4.2 审计存储与访问

- 审计日志必须可按 `tenant_id` 过滤
- 审计查询接口必须受 RBAC 限制
- 审计链路异常不得影响主请求成功返回（失败应降级并记录）

### 4.3 追踪头规范

- 每个请求必须具备 `X-Request-Id` 与 `X-Trace-Id`
- 来自客户端的 ID 必须经过安全净化（字符白名单 + 长度限制）
- 严禁将污染 header 原样写回响应头

---

## 5. 限流与防滥用规范

- 必须启用基础限流（API Key/IP 维度）
- 限流响应不得返回敏感身份原文（仅可返回类型）
- 健康检查路径可豁免限流
- 高频轮询接口必须评估轮询间隔与缓存策略
- 上传接口必须具备：
  - 单文件大小限制
  - 总上传大小限制
  - 并发限制（超限返回 `429`）
  - 流式写入，避免一次性读入内存

---

## 6. 配置变更与审批流程

高风险配置项（变更需审批）：

- `SECURITY_GUARDRAILS_STRICT`
- `RBAC_*`
- `TENANT_*`
- `FILE_READ_ALLOWED_ROOTS`
- `TOOL_NET_HTTP_ENABLED` / `TOOL_NET_HTTP_ALLOWED_HOSTS`
- `CORS_ALLOWED_ORIGINS`

审批最小要求：

1. 变更目的与风险评估
2. 回滚方案
3. 生效窗口
4. 负责人（研发 + 运维/安全）

---

## 7. 安全回归与发布门禁

### 7.1 本地门禁

在 `backend` 目录执行：

```bash
python scripts/security_regression.py \
  --base http://127.0.0.1:8000 \
  --api-key "admin-key" \
  --tenant-id default \
  --json-output /tmp/security-regression.json \
  --junit-output /tmp/security-regression.xml \
  --suite-name security_regression_local
```

必须通过：

- 退出码 `0`
- 输出 `Summary: x/x checks passed`

### 7.2 CI 门禁

工作流：`.github/workflows/tenant-security-regression.yml`

要求：

- PR 必须绿灯
- JUnit 报告 artifact 必须可用
- 并发取消策略开启（防重复跑）

---

## 8. 应急降级与恢复规范

允许临时降级项（仅故障抢修）：

- `SECURITY_GUARDRAILS_STRICT=false`

应急后 24 小时内必须完成：

1. 恢复为 `true`
2. 复跑安全回归
3. 输出事故复盘与防再发措施

---

## 9. 最小审计留痕模板（建议）

- 变更人：
- 变更时间：
- 变更项：
- 影响范围：
- 审批人：
- 回滚方案：
- 验证结果：

---

## 10. 自查清单（每周/每次发布）

- [ ] 生产配置符合第 2 节强制基线
- [ ] RBAC 与 Tenant 绑定策略有效
- [ ] 审计日志可查询且可按 tenant 过滤
- [ ] 请求追踪头完整且已净化
- [ ] 限流响应无敏感信息泄露
- [ ] 安全回归脚本与 CI 全绿
- [ ] 应急降级项均已恢复
