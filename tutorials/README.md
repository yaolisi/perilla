# Tutorials 目录说明（新手优先）

本 Standalone 包把教程与专题集中在 **`tutorials/`**。  
若你只想找「从哪一页开始」，直接看 **[tutorial-index.md](tutorial-index.md)**。

---

## 新手建议阅读顺序（约 30～60 分钟）

1. **[tutorial-quickstart.md](tutorial-quickstart.md)** — 约 10 分钟：启动、拿到 CSRF、跑一次健康检查。
2. **[tutorial.md](tutorial.md)** — 主教程：环境、`.env`、租户/RBAC、`security_regression.py`、排障。
3. **[tutorial-security-baseline.md](tutorial-security-baseline.md)** — 团队对齐：生产 MUST 项、门禁与变更审批。
4. `tutorial.md` 的 **§9.5 / §17.10 / §17.11 / §20.16~§20.17** — 自治编排新增能力（幂等、持久化队列、HITL 审批）验证。
5. `tutorial.md` 的 **§9.6 / §17.12 / §17.13** — 前端交互与性能增强（大列表分页、画布大图优化、可诊断错误提示）。

有经验的同学可跳过 1，从 `tutorial.md` 第 5 节「配置 `.env`」切入。

---

## 按场景跳转（常见问题）

- **刚开始，不知道从哪下手**：`tutorial-quickstart.md` → `tutorial.md`
- **403**（写接口被拒、管理员接口失败）：`tutorial.md` → **§17 常见错误** → §17.2 / §17.6（权限、CSRF）；确认 `API_KEY_SCOPES_JSON` 与 RBAC
- **404**（创建过资源但查不到）：`tutorial.md` → **§10 多租户**、§17.3；多半是 `X-Tenant-Id` 与创建时不一致
- **429**（请求太频繁或上传并发过高）：`tutorial.md` → §17.4、§17.9（限流与 Agent 上传并发）
- **409**（幂等冲突 / 重复执行冲突）：`tutorial.md` → §17.10（Idempotency-Key 场景）
- **400**（`tenant id required for protected path`）：`tutorial.md` → §17.8
- **Workflow 执行暂停在 `PAUSED`**：`tutorial.md` → §17.11（HITL 审批节点）
- **知识库文档很多，页面变慢**：`tutorial.md` → §17.12（>50 自动分页）
- **Workflow 节点很多，拖动画布卡顿**：`tutorial.md` → §17.13（>50 节点渲染优化）
- **模型调用失败但原因不清晰**：`tutorial.md` → §17.14（可诊断错误提示）
- **本地跑安全回归（JSON/JUnit）**：`tutorial.md` → **§15**；命令示例见 `tutorial-index.md` → **§6**
- **Execution Kernel 集成测试卡住或超时**：`tutorial.md` → **§15.5**（`EXEC_KERNEL_INTEGRATION_DIAG`、`EXEC_KERNEL_START_INSTANCE_TIMEOUT_SEC`）
- **发版前 5 分钟**：`tutorial-ops-checklist.md`
- **线上告警、大量错误**：`tutorial-incident-runbook.md`

以上在 **`tutorial.md`** 中可用全文搜索小节标题（如 `### 17.2`）快速定位。

---

## 专题与安全提示

- **[tutorial-index.md](tutorial-index.md)** — 教程总索引、按角色命令、Windows 对照
- **[security-review-hints.md](security-review-hints.md)** — 全面安全与逻辑相关性检查结论（中文，部署/评审对照）
- **[security-review-hints-en.md](security-review-hints-en.md)** — Same review, English summary

---

## 文档维护约定（简述）

安全、租户、鉴权等行为变更后，优先同步：**`tutorial.md`**、**`tutorial-security-baseline.md`**、**`tutorial-ops-checklist.md`**。详见 `tutorial-index.md` §7。
