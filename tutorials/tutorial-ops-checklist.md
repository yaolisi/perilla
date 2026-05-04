# perilla 运维值班短清单

适用：研发 / 测试 / 运维在 **约 3～5 分钟** 内判断是否可以发布或需要回滚。

---

## A. 60 秒阻断项（任一不满足即停止发布）

- [ ] `DEBUG=false`（生产模式）
- [ ] `SECURITY_GUARDRAILS_STRICT=true`
- [ ] `RBAC_ENABLED=true` 且 `RBAC_ENFORCEMENT=true`
- [ ] `TENANT_ENFORCEMENT_ENABLED=true`
- [ ] `TENANT_API_KEY_BINDING_ENABLED=true`
- [ ] `TENANT_API_KEY_TENANTS_JSON` 已配置且非空
- [ ] `FILE_READ_ALLOWED_ROOTS` 不是 `/`
- [ ] `CORS_ALLOWED_ORIGINS` 已明确配置（非空）
- [ ] 若 `TOOL_NET_HTTP_ENABLED=true`，则 `TOOL_NET_HTTP_ALLOWED_HOSTS` 非空

> 任一阻断项不满足：**立即停止发布/回滚处理**。

---

## B. 90 秒回归检查（必须通过）

在本仓库根目录执行（或先 `cd backend`）：

```bash
backend/scripts/test_tenant_security_regression.sh
```

通过标准：

- [ ] 命令退出码为 `0`
- [ ] 输出包含 `regression suite passed`
- [ ] 无新增失败用例

可选（生成测试报告）：

```bash
JUNIT_XML_PATH=test-reports/tenant-security-regression.xml backend/scripts/test_tenant_security_regression.sh
```

---

## C. 30 秒 CI 检查（必须通过）

- [ ] **`backend-static-analysis`** 绿色（主后端：依赖策略、lint、no-fallback、tenant、Helm、合并门禁、Compose/监控/K8s/安全护栏等；与本地 `make pr-check` / `bash scripts/production-preflight.sh` 对拍）
- [ ] 变更涉及依赖或 `scripts/scan-dependencies.sh` 时：**`dependency-security-scan`** 绿色
- [ ] 变更涉及前端时：**`frontend-build`** 绿色
- [ ] `tenant-security-regression` workflow 绿色
- [ ] 本次 PR 对应 artifact 已上传（junit report，如适用）
- [ ] 无并发取消导致的“最后一次任务未执行”误判

---

## D. 2 分钟冒烟（建议）

- [ ] `GET /api/health` 正常
- [ ] `GET /api/health/live` 正常
- [ ] `GET /api/health/ready` 正常
- [ ] 用合法 API Key + tenant 访问 workflow 成功
- [ ] 用合法 API Key + 错误 tenant 访问 workflow 返回 `404/403`（符合策略）
- [ ] 对一两条租户强制路径（如 `GET /api/sessions` 或 `GET /api/memory/...`）在**缺少** `X-Tenant-Id` 时应得到 **400**（与 `tenant_paths` 策略一致）
- [ ] `POST /api/system/config` 非 admin 被拒绝（`403`）

---

## E. 1 分钟安全可观测性检查（建议）

- [ ] 请求响应头有 `X-Request-Id`、`X-Trace-Id`
- [ ] 审计日志可按租户过滤
- [ ] 限流响应不泄露 API Key（仅 `identity_type`）

---

## F. 应急开关（仅抢修场景）

仅在故障抢修且经审批后允许：

- `SECURITY_GUARDRAILS_STRICT=false`（从“阻断”降级为“告警”）

应急后必须回滚：

- [ ] 恢复 `SECURITY_GUARDRAILS_STRICT=true`
- [ ] 复跑回归脚本
- [ ] 记录变更与恢复时间

---

## G. 结论记录（值班签核）

- [ ] 允许发布
- [ ] 暂缓发布（原因：________________）
- [ ] 需要安全复核（负责人：________________）

签字：

- 研发：__________
- 测试：__________
- 运维/安全：__________
- 时间：__________
