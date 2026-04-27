# OpenVitamin 值班故障处理卡片（约 3 分钟）

告警后快速：**分级 → 止血 → 定位 → 回滚**。适用于网关、Workflow、租户隔离与安全护栏相关问题。

---

## 0. 一句话原则

- 先恢复服务，再追根因。
- 不做未评估的高风险变更。
- 所有应急操作必须可回滚、可审计。

---

## 1. 0~3 分钟：快速分级与止血

### 1.1 判断事故等级

- **P0**：全站不可用 / 大面积 5xx / 启动失败
- **P1**：核心路径异常（workflow 执行、租户访问、大量 403/404 异常）
- **P2**：局部功能受影响（个别模型/租户）

### 1.2 立即采集 4 个关键信息

- 时间窗口（开始时间）
- 影响范围（租户、接口、比例）
- 最近变更（发布、配置、环境）
- 关键请求标识：`X-Request-Id` / `X-Trace-Id`

### 1.3 快速健康探针

- `GET /api/health`
- `GET /api/health/live`
- `GET /api/health/ready`

若探针失败：先按启动/依赖故障处理（见第 4 节）。

---

## 2. 3~10 分钟：核心路径定位

### 2.1 如果大量 403（权限/租户相关）

优先检查：

- `RBAC_ENABLED`、`RBAC_ENFORCEMENT`
- `TENANT_ENFORCEMENT_ENABLED`
- `TENANT_API_KEY_BINDING_ENABLED`
- `TENANT_API_KEY_TENANTS_JSON`
- 请求头：`X-Api-Key`、`X-Tenant-Id`

快速判断：

- 单租户失败：可能是 key-tenant 绑定缺失
- 全租户失败：可能是配置误改或中间件链异常

### 2.2 如果大量 404（workflow 相关）

优先检查：

- workflow 所属 `namespace` 是否与 `X-Tenant-Id` 一致
- 是否出现跨租户访问（策略下可能故意返回 404）
- 是否刚迁移/变更了 tenant 默认值

### 2.3 如果大量 429（限流）

检查：

- `API_RATE_LIMIT_REQUESTS`
- `API_RATE_LIMIT_WINDOW_SECONDS`
- 是否有突发流量或轮询风暴

---

## 3. 快速止血手段（按风险从低到高）

1. 回滚最近配置变更（首选）
2. 回滚最近代码版本（若有发布）
3. 仅在审批后临时降级：
   - `SECURITY_GUARDRAILS_STRICT=false`（仅告警不阻断）

> 注意：临时降级后，必须在故障恢复后恢复为 `true`。

---

## 4. 启动失败专用流程

若日志出现 `Unsafe production security configuration. Refuse to start.`：

依次检查：

- `FILE_READ_ALLOWED_ROOTS` 是否为 `/`
- `CORS_ALLOWED_ORIGINS` 是否为空
- 当 `TOOL_NET_HTTP_ENABLED=true` 时，`TOOL_NET_HTTP_ALLOWED_HOSTS` 是否为空

修正后重启服务。  
若紧急恢复需临时启动，可审批后短暂设置：

- `SECURITY_GUARDRAILS_STRICT=false`

---

## 5. 10~30 分钟：证据固定与验证恢复

### 5.1 固定证据

- 关键日志时间段
- 受影响请求的 `X-Request-Id` / `X-Trace-Id`
- 审计日志（按 tenant 过滤）
- 变更记录（发布版本、配置 diff）

### 5.2 恢复后验证

在项目根目录执行：

```bash
backend/scripts/test_tenant_security_regression.sh
```

验证通过后再宣布恢复完成。

---

## 6. 事后复盘最小模板

- 事故编号：
- 开始时间 / 恢复时间：
- 影响范围：
- 用户影响：
- 直接原因：
- 根因：
- 止血动作：
- 永久修复：
- 防再发项（监控/测试/流程）：

---

## 7. 常用检查清单（值班口袋版）

- [ ] 探针健康（`/api/health`、`/api/health/live`、`/api/health/ready`）
- [ ] 收集 request_id/trace_id
- [ ] 判定 403/404/429/5xx 主类型
- [ ] 核对 RBAC + tenant + key-binding 配置
- [ ] 评估是否需要回滚/降级
- [ ] 恢复后跑 tenant 回归脚本
- [ ] 输出复盘记录
