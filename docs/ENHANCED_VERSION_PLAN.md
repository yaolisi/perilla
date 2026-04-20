# openvitamin_enhanced 分批交付计划

本目录为「增强版」并行副本，在不影响原 `OpenVitamin` 主仓库的前提下迭代治理与可观测能力。

## Batch 1 — RBAC 平台角色

- **内容**：`X-Api-Key`（与限流共用 Header 名，可配置）映射 `admin` / `operator` / `viewer`；可选 `rbac_enforcement` 对 viewer 拦截控制面写请求。
- **配置**：见 `backend/config/settings.py` 中 `rbac_*`。
- **测试**：`tests/test_enhanced_rbac_audit.py`、`tests/test_enhanced_middlewares.py`
- **验收**：`scripts/acceptance/run_batch1_rbac.sh`

## Batch 2 — 审计查询

- **内容**：`audit_logs` 表、`AuditLogMiddleware`（响应后写入）、`GET /api/v1/audit/logs`（**仅 admin**）。
- **配置**：`audit_log_enabled`、`audit_log_path_prefixes`、`audit_log_include_get`。
- **测试**：同 Batch 1 中间件与 RBAC 单测；审计查询依赖运行实例与 DB，以验收脚本手工/集成验证为主。
- **验收**：`scripts/acceptance/run_batch2_audit.sh`

## Batch 3 — Trace 链路

- **内容**：`traceparent` / `X-Trace-Id` 解析，`request.state.trace_id`，响应头 `X-Trace-Id`；`/api/health` 返回 `trace_id`。
- **配置**：`trace_link_enabled`。
- **测试**：`tests/test_enhanced_rbac_audit.py`（traceparent 解析）、`tests/test_enhanced_middlewares.py`（响应头）。
- **验收**：`scripts/acceptance/run_batch3_trace.sh`

## Batch 4 — 工作流调试 API

- **内容**：`GET /api/v1/workflows/{workflow_id}/executions/{execution_id}/debug`：聚合 hydrated execution、内核快照、execution_kernel 近期事件。
- **权限**：与工作流 `read` 一致。
- **测试**：逻辑依赖内核 DB，以运行服务后的验收脚本为主。
- **验收**：`scripts/acceptance/run_batch4_workflow_debug.sh`

## 一键回归（单测）

`scripts/acceptance/run_all_unit_tests.sh`

