# perilla 上手教程（从环境到上线）

面向 **Standalone** 仓库新手：覆盖安装、启动、租户与 RBAC、CSRF/XSS、Workflow 与 Agent、回归测试与常见错误。**所有模型与控制面调用经 FastAPI 网关**；请勿绕过网关直连推理引擎。

本教程帮助你完成：**环境安装 → 前后端启动 → 功能验证 → 安全配置 → 回归与上线前自检**。  
迷路时先看 **[README.md](README.md)**（阅读顺序与按 HTTP 状态码跳转）。

**相关文档**

| 文档 | 用途 |
|------|------|
| [README.md](README.md) | 教程目录导航、403/404/429 等问题索引 |
| [tutorial-quickstart.md](tutorial-quickstart.md) | 约 10 分钟极简上手 |
| [tutorial-index.md](tutorial-index.md) | 索引、命令、PowerShell 对照 |
| [tutorial-ops-checklist.md](tutorial-ops-checklist.md) | 发版前短清单 |
| [tutorial-incident-runbook.md](tutorial-incident-runbook.md) | 线上故障卡片 |
| [tutorial-security-baseline.md](tutorial-security-baseline.md) | 安全 MUST 与门禁 |
| [tutorial-glossary-zh-en.md](tutorial-glossary-zh-en.md) / [product](tutorial-glossary-product.md) / [engineering](tutorial-glossary-engineering.md) | 术语表 |

---

## 1. 先理解：这个项目是做什么的

**perilla** 是本地优先的 AI 平台，可概括为：

- **前端控制台**：可视化操作界面（Vue）
- **后端网关**：统一接入模型、工作流、审计、安全治理（FastAPI）
- **能力模块**：Agent、Tool、Skill、Workflow、Image、RAG 等

它不是“单一聊天应用”，而是“可治理的 AI 能力平台”。

当前仓库默认已包含以下生产化能力：

- 多租户隔离（入口强制、API Key–租户绑定、Workflow/会话/知识库/记忆/聊天/VLM/Agent 会话等数据面 **tenant_id** 过滤；MCP 与 Skills 等控制面按中间件租户解析）
- RBAC 鉴权
- API Key 与租户绑定
- 审计与请求追踪
- 限流与防滥用
- 生产护栏（高危配置可阻断启动）

---

## 2. 准备环境（新手必做）

### 2.1 必备软件

- Python `3.11+`
- Node.js `18+`
- Conda（推荐）
- Git

建议先验证：

```bash
python --version
node --version
conda --version
git --version
```

### 2.2 创建 Python 虚拟环境（推荐 Conda）

```bash
conda create -n ai-inference-platform python=3.11 -y
conda activate ai-inference-platform
```

如果你不使用 Conda，也可以用 `venv`，但项目默认流程更偏 Conda。

---

## 3. 获取代码并进入目录

```bash
cd "你的工作目录"
# Standalone 完整分发目录通常为 perilla（或你克隆的本仓库根目录）
cd perilla
```

确认关键目录存在：

- `backend/`
- `frontend/`
- `backend/scripts/`
- `backend/tests/`

---

## 4. 安装依赖（前后端）

### 4.1 安装后端依赖

```bash
cd backend
pip install -r requirements.txt
cd ..
```

说明：

- 当前 `backend/requirements.txt` 会按平台引用子依赖（当前路径默认是 macOS 入口）
- 若安装很慢，建议配置镜像源

### 4.2 安装前端依赖

```bash
cd frontend
npm install
cd ..
```

---

## 5. 配置 `.env`（非常重要）

你可以在 `backend/.env`（或项目根 `.env`）配置运行参数。  
新手建议先从“开发安全模式”开始，再逐步切生产模式。

### 5.1 开发环境建议（便于调试）

```dotenv
DEBUG=true
RBAC_ENABLED=true
RBAC_ENFORCEMENT=true
TENANT_ENFORCEMENT_ENABLED=true
TENANT_API_KEY_BINDING_ENABLED=true
TENANT_API_KEY_TENANTS_JSON={"admin-key":["*"],"dev-key":["tenant-dev"]}
RBAC_ADMIN_API_KEYS=admin-key
RBAC_OPERATOR_API_KEYS=dev-key
SECURITY_GUARDRAILS_STRICT=true
```

### 5.2 生产环境建议（最小安全基线，建议直接复制）

```dotenv
DEBUG=false

RBAC_ENABLED=true
RBAC_ENFORCEMENT=true
RBAC_ADMIN_API_KEYS=admin-key-1
RBAC_OPERATOR_API_KEYS=op-key-1,op-key-2
RBAC_VIEWER_API_KEYS=view-key-1
RBAC_DEFAULT_ROLE=viewer

TENANT_ENFORCEMENT_ENABLED=true
TENANT_HEADER_NAME=X-Tenant-Id
TENANT_API_KEY_BINDING_ENABLED=true
TENANT_API_KEY_TENANTS_JSON={"admin-key-1":["*"],"op-key-1":["tenant-a"],"op-key-2":["tenant-b"]}
API_KEY_SCOPES_JSON={"admin-key-1":["admin","model:write","workflow:write","audit:read"]}

API_RATE_LIMIT_ENABLED=true
API_RATE_LIMIT_REQUESTS=120
API_RATE_LIMIT_WINDOW_SECONDS=60

AUDIT_LOG_ENABLED=true
AUDIT_LOG_PATH_PREFIXES=/api/v1/workflows,/api/system

CORS_ALLOWED_ORIGINS=https://console.example.com
FILE_READ_ALLOWED_ROOTS=/data,/models

TOOL_NET_HTTP_ENABLED=false
TOOL_NET_HTTP_ALLOWED_HOSTS=api.openai.com,*.internal.example.com
TOOL_NET_HTTP_ALLOW_PRIVATE_TARGETS=false
TOOL_NET_WEB_ENABLED=false

AGENT_ALLOW_DANGEROUS_SKILLS=false
AGENT_UPLOAD_MAX_CONCURRENCY=4

SECURITY_GUARDRAILS_STRICT=true
```

### 5.3 新手最易踩坑（必须看）

1. `DEBUG=false` 时，`CSRF_COOKIE_SECURE` 默认会变为 `true`。  
   如果你用 `http://127.0.0.1` 直接调写接口，需要手工回传 `Cookie: csrf_token=...` 与 `X-CSRF-Token`。
2. `/api/system/*` 现在要求：
   - admin API Key
   - 显式 `X-Tenant-Id`
3. 写接口（POST/PUT/PATCH/DELETE）必须通过 CSRF 校验，否则 403。

---

## 6. 启动项目（两种方式）

### 6.1 一键启动（推荐新手）

项目根目录：

- macOS/Linux：`./run-all.sh`
- Windows：`run-all.bat`

### 6.2 手动启动（便于定位问题）

后端：

```bash
cd backend
python main.py
```

前端（新终端）：

```bash
cd frontend
npm run dev
```

默认后端端口一般是 `8000`。

---

## 7. 启动后第一轮自检（新手必须做）

### 7.1 API 探针检查

后端启动后检查：

- `GET /api/health`
- `GET /api/health/live`
- `GET /api/health/ready`

只要其中任何一个持续失败，就不要继续做业务验证，先看日志。

### 7.2 看日志重点

重点看是否出现：

- 数据库初始化失败
- 依赖导入失败
- 安全护栏阻断：`Unsafe production security configuration. Refuse to start.`

---

## 8. 前端界面快速认识

首次登录后，建议按这个顺序体验：

1. **General / Backend Settings**：看系统配置是否生效  
2. **Workflow**：创建一个最小流程并执行  
3. **Models / Images**：验证模型侧能力（按你的环境）  
4. **Audit / Logs（若开放）**：确认审计与追踪信息

---

## 9. 第一个 Workflow（手把手）

### 9.1 准备请求头

你至少需要：

- `X-Api-Key`
- `X-Tenant-Id`

例如：

- `X-Api-Key: dev-key`
- `X-Tenant-Id: tenant-dev`

### 9.2 创建流程

调用：

- `POST /api/v1/workflows`

要点：

- `namespace` 应与 `X-Tenant-Id` 一致（服务端会强制对齐）
- 名称在同 namespace 内需唯一

### 9.3 创建版本并执行

- 创建版本：`POST /api/v1/workflows/{workflow_id}/versions`
- 发起执行：`POST /api/v1/workflows/{workflow_id}/executions`
- 查执行状态：`GET /api/v1/workflows/{workflow_id}/executions/{execution_id}/status`
- 调试视图：`GET /api/v1/workflows/{workflow_id}/executions/{execution_id}/debug`

### 9.4 新手最常见误区

- 403：API Key 权限不足
- 404：租户不匹配（这是安全策略，不一定是数据不存在）
- 429：触发限流

### 9.5 自治编排新增能力（本版本）

在已有租户/RBAC/CSRF 基线之外，本版本工作流与 Agent 路径新增四项关键能力：

1. **插件权限强校验**：插件执行前按声明权限判定，权限不足直接拒绝。  
2. **Agent run 幂等**：`POST /api/v1/agents/{agent_id}/run` 支持 `Idempotency-Key`，避免重试导致重复执行。  
3. **持久化执行队列**：工作流执行队列持久化到数据库，支持 lease 与重启恢复。  
4. **HITL 审批闸门**：存在 `approval` 节点时，执行可进入 `PAUSED` 等待人工批准。

### 9.6 前端交互与性能增强（本版本）

为提升大规模使用场景下的体验，前端新增如下能力：

1. **Workflow 编辑器选择器搜索**：模型/Agent/工具选择支持关键字过滤。  
2. **知识库大列表分页**：文档数 > 50 时自动分页，避免一次性渲染过多行。  
3. **Workflow 大图渲染优化**：节点数 > 50 时启用可视区域渲染优化。  
4. **错误提示可诊断**：模型调用失败时优先显示具体可排查原因（如 OOM、权重损坏、超时等）。

---

## 10. 多租户与权限（必须理解）

### 10.1 三层安全关系

1. **RBAC 角色**：admin/operator/viewer  
2. **API Key-租户绑定**：一个 key 可以访问哪些 tenant  
3. **资源租户隔离**：Workflow、会话、知识库、长短期记忆、治理审计等存储/查询层 **tenant-aware**（具体模块以代码为准）

### 10.2 为什么会出现“看得见创建，看不见查询”

通常是请求头变化导致：

- 创建时 `X-Tenant-Id=tenant-a`
- 查询时 `X-Tenant-Id=tenant-b`

系统会按策略返回 `404`。

### 10.3 快速排查顺序

1. 看请求头 `X-Api-Key` / `X-Tenant-Id`
2. 看 `TENANT_API_KEY_TENANTS_JSON` 是否绑定
3. 看 resource namespace 是否一致

### 10.4 租户强制路径（须显式 `X-Tenant-Id`）

当 **`TENANT_ENFORCEMENT_ENABLED`** 与 **`TENANT_API_KEY_BINDING_ENABLED`** 开启时，命中下列 **URL 前缀**之一即视为受保护路径：请求必须携带 **`TENANT_HEADER_NAME`**（默认 `X-Tenant-Id`），否则可能返回 **400**（如 `tenant id required for protected path`）。**单一事实来源**为后端：

`backend/middleware/tenant_paths.py` → `is_tenant_enforcement_protected_path`

当前前缀包括：`/api/v1/workflows`、`/api/v1/audit`、`/api/system`、`/v1/chat`、`/api/sessions`、`/api/memory`、`/api/knowledge-bases`、`/api/agent-sessions`、`/v1/vlm`（若升级版本后行为变化，以该文件为准）。

### 10.5 租户解析：`resolve_api_tenant_id` 与 `get_effective_tenant_id`

部分路由使用 **`resolve_api_tenant_id`**：仅采用中间件写入的 `request.state.tenant_id`（及默认租户），**不**用请求头覆盖 state，避免头注入绕过。  
另有一些场景使用 **`get_effective_tenant_id`**：在 state 未设置时可回落读取租户头，再回落默认租户（见 `backend/core/utils/tenant_request.py`）。集成第三方客户端时，不要假设「任意路径都可仅靠改头换租户」：须与 Key 绑定及中间件行为一致。

---

## 11. 系统配置接口怎么安全使用

关键接口：

- `POST /api/system/config`
- `POST /api/system/engine/reload`
- `POST /api/system/feature-flags`
- `POST /api/system/kernel/*`

注意：

- 这些写接口已要求管理员权限
- 如果你是 operator/viewer，请求会被拒绝（403）
- **凡命中租户强制前缀**（见 **§10.4**）须显式带 `X-Tenant-Id`，不仅是 `/api/system/*`；未携带可能返回 400

---

## 12. 审计、追踪、限流（可观测性）

### 12.1 请求追踪

每次请求应看到：

- `X-Request-Id`
- `X-Trace-Id`
- `X-Response-Time-Ms`

网关已对 `request_id` 做净化，避免 header 污染。

### 12.2 审计日志

审计日志可记录：

- 租户、用户、角色
- 方法、路径、状态码
- request_id / trace_id

并支持按租户过滤查询。

### 12.3 限流

核心配置：

- `API_RATE_LIMIT_ENABLED`
- `API_RATE_LIMIT_REQUESTS`
- `API_RATE_LIMIT_WINDOW_SECONDS`

限流返回已去敏，不泄露 API Key。

---

## 13. Web 安全增强（本次重点）

这一节是新手最容易忽略、但上线最容易出事故的部分。你可以直接把它理解成：

- **XSS**：防止页面渲染恶意脚本
- **CSRF**：防止“你已登录时被别的网站偷偷代你发写请求”

### 13.1 前端 XSS 防护已做什么

本项目已完成以下防护链：

1. `frontend/src/utils/markdown.ts` 中 `markdown-it` 已设置 `html: false`  
   - 用户输入的原生 HTML（例如 `<script>...</script>`）不会被当成可执行 HTML 渲染
2. markdown 渲染结果统一经过 `sanitizeHtml(...)` 净化  
   - 由 `frontend/src/utils/security.ts`（DOMPurify）执行白名单过滤
3. Mermaid SVG 渲染也经过净化，且 `securityLevel: 'strict'`  
   - 防止图形渲染链路被注入恶意节点/属性

### 13.2 后端 CSRF 防护已做什么

后端新增了双提交 Cookie 机制（double-submit cookie）：

- 中间件：`backend/middleware/csrf_protection.py`
- 关键行为：
  - `GET/HEAD/OPTIONS/TRACE` 等安全方法会下发 `csrf_token` Cookie 与 `X-CSRF-Token` 响应头
  - `POST/PUT/PATCH/DELETE` 必须提供 `X-CSRF-Token`，且与 Cookie 中 token 一致
  - 不一致或缺失返回 `403`

### 13.3 配置项（后端）

`backend/config/settings.py` 已支持：

- `CSRF_ENABLED`
- `CSRF_HEADER_NAME`（默认 `X-CSRF-Token`）
- `CSRF_COOKIE_NAME`（默认 `csrf_token`）
- `CSRF_COOKIE_PATH`
- `CSRF_COOKIE_SAMESITE`
- `CSRF_COOKIE_SECURE`
- `CSRF_COOKIE_MAX_AGE_SECONDS`

### 13.4 新手常见误区

- 误区 1：只在前端加了 token，后端没校验  
  - 结果：形同虚设
- 误区 2：跨域部署仍用 `CORS_ALLOWED_ORIGINS=*`  
  - 结果：Cookie/凭证策略混乱，浏览器行为不可控
- 误区 3：脚本调用写接口不带 CSRF header  
  - 结果：稳定 403

---

## 14. 生产安全护栏（必读）

### 14.1 自动收敛

当 `DEBUG=false` 时，系统会自动收敛关键开关：

- `RBAC_ENABLED=true`
- `RBAC_ENFORCEMENT=true`
- `TENANT_ENFORCEMENT_ENABLED=true`
- `TENANT_API_KEY_BINDING_ENABLED=true`

### 14.2 启动阻断（Fail-Fast）

命中以下风险会拒绝启动：

- `FILE_READ_ALLOWED_ROOTS="/"`  
- `CORS_ALLOWED_ORIGINS=""`  
- `TOOL_NET_HTTP_ENABLED=true` 且 `TOOL_NET_HTTP_ALLOWED_HOSTS=""`

### 14.3 严格模式开关

- `SECURITY_GUARDRAILS_STRICT=true`：违规直接阻断（默认推荐）
- `SECURITY_GUARDRAILS_STRICT=false`：仅告警继续（仅抢修临时使用）

---

## 15. 测试与回归（上线前必须跑）

你现在有两条回归主线（不要混淆）：

1. **tenant 安全回归**（租户隔离为主）
2. **security 安全回归**（RBAC/Audit/Trace/CSRF/XSS）

### 15.1 tenant 安全回归（后端脚本）

在项目根目录执行：

```bash
backend/scripts/test_tenant_security_regression.sh
```

预期：

- 退出码 `0`
- 输出包含 `regression suite passed`
- 生成摘要（默认）：`backend/test-reports/tenant-security-summary.md`

如需报告文件：

```bash
JUNIT_XML_PATH=test-reports/tenant-security-regression.xml backend/scripts/test_tenant_security_regression.sh
```

### 15.2 security 安全回归（推荐新脚本）

在项目根目录执行：

```bash
python backend/scripts/security_regression.py \
  --base http://127.0.0.1:8000 \
  --api-key "你的-admin-key" \
  --tenant-id default
```

常用参数：

- `--json-output /tmp/security-regression.json`：导出结构化结果
- `--junit-output /tmp/security-regression.xml`：导出 JUnit（CI 用）
- `--suite-name security_regression_staging`：区分环境
- `--quiet`：只输出 summary
- `--fail-fast`：首个失败立即退出

### 15.3 security 安全回归（acceptance 聚合脚本，兼容保留）

在项目根目录执行：

```bash
scripts/acceptance/run_security_regression.sh
```

该脚本会串行执行：

- `scripts/acceptance/run_batch1_rbac.sh`
- `scripts/acceptance/run_batch2_audit.sh`
- `scripts/acceptance/run_batch3_trace.sh`
- `scripts/acceptance/run_batch5_web_security.sh`

并生成摘要：

- `test-reports/security-regression-summary.md`

### 15.4 慢批次阈值告警（本地）

可选设置阈值（秒）：

```bash
SECURITY_SLOW_THRESHOLD_SECONDS=20 scripts/acceptance/run_security_regression.sh
TENANT_SECURITY_SLOW_THRESHOLD_SECONDS=20 backend/scripts/test_tenant_security_regression.sh
```

当超过阈值，摘要会出现 `⚠️` 和 Slow Batches 区块。

### 15.5 Execution Kernel 集成测试（可选 / 重型）

用于本地验证 **Plan 编译**、**节点执行器注册**、`ExecutionKernelAdapter` 初始化等；默认脚本**只跑轻量项**（秒级结束），避免重型 Scheduler + SQLite 组合在你机器上长时间阻塞或触发锁竞争。

**快速入口（日常推荐）：**

```bash
PYTHONPATH=backend python3 backend/scripts/test_execution_kernel_integration.py
```

预期：约 **3 项**通过，退出码 `0`。

**重型入口（额外跑 Scheduler + 独立临时库）：**

```bash
PYTHONPATH=backend python3 backend/scripts/test_execution_kernel_integration_heavy.py
```

与在主脚本前设置 `EXEC_KERNEL_RUN_HEAVY_INTEGRATION=1` 等价。

**排障：卡住、无输出或迟迟不结束**

要知道：`Scheduler.start_instance()` 会**一直等到整张图跑完**才返回；若调度或数据库侧阻塞，看起来像「挂住」。

可配合：

- `EXEC_KERNEL_INTEGRATION_DIAG=1`：约每 **5 秒**打印一次快照（图实例状态、各节点 pending/running 分布、调度器在跑任务数等）。
- `EXEC_KERNEL_START_INSTANCE_TIMEOUT_SEC`：限制 `start_instance` 最长等待秒数（默认 **`90`**）；超时后会尝试取消实例并抛出带说明的错误，而不是无限等下去。

示例（重型 + 诊断 + 超时）：

```bash
EXEC_KERNEL_RUN_HEAVY_INTEGRATION=1 \
EXEC_KERNEL_INTEGRATION_DIAG=1 \
EXEC_KERNEL_START_INSTANCE_TIMEOUT_SEC=90 \
PYTHONPATH=backend python3 backend/scripts/test_execution_kernel_integration.py
```

此外，Execution Kernel 还有独立回归脚本 `backend/scripts/test_execution_kernel_regression.py`；若启用了敏感路由鉴权，可按脚本内说明配置 `RBAC_TEST_ADMIN_API_KEY`、`RBAC_TEST_TENANT_ID` 等，避免系统 API 冒烟用例被跳过。

---

## 16. CI 流水线说明（你当前已接好）

工作流：

- `.github/workflows/tenant-security-regression.yml`
- `.github/workflows/security-regression.yml`

能力：

- PR / push（含路径过滤 + docs 变更忽略）
- 并发去重（新任务取消旧任务）
- `workflow_dispatch` 手动触发
- 结果双输出：Step Summary + Artifact
- 手动触发可设置 `slow_threshold_seconds`
- 输入校验：必须是正整数（非法输入会 fail-fast 并在 Summary 给出示例）

### 16.1 两条工作流如何分工

- `tenant-security-regression.yml`  
  - 聚焦：租户隔离
  - 主入口脚本：`backend/scripts/test_tenant_security_regression.sh`
- `security-regression.yml`  
  - 聚焦：RBAC/Audit/Trace/CSRF/XSS
  - 主入口脚本：`scripts/acceptance/run_security_regression.sh`

---

## 16.2 Agent 并行编排与记忆（新能力）

当你使用 `plan_based` 智能体时，可以通过 agent 配置开启图执行并行与记忆增强：

- `execution_strategy=parallel_kernel`：启用 Agent Graph + Execution Kernel 并行调度
- `max_parallel_nodes=<N>`：限制单次执行并发节点数（建议先 2~4）
- `execution_strategy=serial`：强制串行 **PlanBasedExecutor**（灰度、排障或与 Kernel 解耦）
- 未设置 `execution_strategy` 时：按 `use_execution_kernel`（Agent 级）与全局 `USE_EXECUTION_KERNEL` 推导（与运行时 `_resolve_execution_strategy` 一致）
- Kernel 执行失败时：运行时会**自动降级**为串行 `PlanBasedExecutor`，单次对话仍尽量完成（错误写入日志与指标）

**HTTP API（创建/更新 Agent）** 已支持同名字段（管理员接口 `PUT/POST /api/agents` 的 JSON body）：

- `execution_strategy`：`"serial"` | `"parallel_kernel"` | `null`（null 表示交给推导逻辑）
- `max_parallel_nodes`：整数或 `null`（null 表示使用内核默认并发）

也可仅在 `model_params` 里写 `execution_strategy` / `max_parallel_nodes`；**运行时优先读顶字段 `AgentDefinition.execution_strategy`，为空时才读 `model_params`**（见 `v2/runtime.py`）。若在**顶字段与 `model_params` 两处同时写了不同取值**，创建/更新接口会返回 **400**（避免 silent shadow）。

事件驱动编排与调试：

- Kernel 执行会写入事件流（可用 `/api/events/instance/{instance_id}` 回放）
- 已支持按会话聚合查询：`/api/events/agent-session/{session_id}`

记忆增强行为：

- 执行前自动注入长期记忆（受 memory 配置开关控制）
- 执行后自动提取并持久化记忆（失败不阻断主链路）

灰度建议：

1. 先给少量 agent 开 `parallel_kernel`
2. 观察事件流中的失败链路与回退次数
3. 再逐步提升 `max_parallel_nodes`

---

## 17. 常见错误与解决方案（新手高频）

### 17.1 启动失败：Unsafe production security configuration

处理：

1. `FILE_READ_ALLOWED_ROOTS` 不要是 `/`
2. `CORS_ALLOWED_ORIGINS` 不要为空
3. 若开启 HTTP 工具，配置 `TOOL_NET_HTTP_ALLOWED_HOSTS`

### 17.2 403（权限问题）

处理：

1. 检查 API Key 是否存在
2. 检查 RBAC 角色映射
3. 检查是否调用了 admin-only 接口

### 17.3 404（跨租户）

处理：

1. 检查 `X-Tenant-Id`
2. 检查 API Key 的 tenant 绑定
3. 检查 workflow namespace

### 17.4 429（限流）

处理：

1. 提高限流阈值（谨慎）
2. 降低轮询频率
3. 合并批量请求

### 17.5 全量 pytest 因三方依赖失败

可能出现 `numpy/sklearn/transformers` 二进制兼容问题。  
优先执行项目稳定回归脚本，不要被无关依赖阻断主线验证。

### 17.6 写接口 403：CSRF token validation failed

处理顺序：

1. 先请求一次 `GET /api/health`，确保拿到 `csrf_token` Cookie
2. 写请求带 `X-CSRF-Token` 且值等于 Cookie 中 token
3. 检查反向代理是否剥离了 `X-CSRF-Token` 头

### 17.7 前端渲染异常怀疑 XSS 清洗导致

处理顺序：

1. 检查是否依赖了原生 HTML 渲染（现在 `html: false`）
2. 检查内容是否被 DOMPurify 合法过滤（脚本/危险属性会被去掉）
3. 对需要保留的展示能力，走白名单扩展，不要临时禁用净化

### 17.8 返回 400：`tenant id required for protected path`

适用于所有 **租户强制路径**（见 **§10.4**，含 `/api/system/*`、`/v1/chat`、`/api/sessions` 等），不单是 system 接口。

处理顺序：

1. 确认请求头里显式带了 `X-Tenant-Id`（名称与 `TENANT_HEADER_NAME` 一致）
2. 确认 key 与 tenant 绑定关系允许该租户
3. 确认前端 Security Context / `localStorage` 中租户已保存并与请求一致

### 17.9 Agent 上传报错 413 / 429

- `413`：文件超单文件/总量限制（默认单文件 20MB、总量 100MB）
- `429`：并发上传超过 `AGENT_UPLOAD_MAX_CONCURRENCY`

处理：

1. 分片或压缩上传文件
2. 降低前端并发上传数量
3. 按需调整服务端阈值（谨慎）

### 17.10 409（Idempotency-Key 冲突）

典型场景：

- 同一个 `Idempotency-Key` 被复用到**不同请求体**；
- 前一次同 key 请求仍处于 processing，中途再次提交。

处理顺序：

1. 确认同一业务动作是否稳定复用同一个 key；
2. 若请求体变化，必须更换新的 `Idempotency-Key`；
3. 若是重试，保持 key 与请求体一致，并等待前一次完成后再查询结果。

### 17.11 Workflow 状态停在 `PAUSED`

典型场景：

- 工作流版本中包含 `approval` 节点；
- 审批任务尚未通过，执行被门控暂停。

处理顺序：

1. 查询执行对应审批任务列表；
2. 由有权限的操作者调用 approve/reject；
3. 确认通过后执行转回 `PENDING`/继续运行，或拒绝后转 `FAILED`。

### 17.12 知识库文档很多时列表卡顿

说明：

- 当前版本在文档数超过 50 时会自动分页（每页 20）。

排查顺序：

1. 确认文档总数是否超过分页阈值；
2. 使用分页按钮切换，避免一次加载过多行；
3. 若仍卡顿，检查浏览器扩展或 DevTools 性能开销。

### 17.13 Workflow 节点很多时画布拖拽卡顿

说明：

- 当前版本在节点数超过 50 时会启用可视区域渲染优化，并保留网格吸附与拖拽后自动对齐。

排查顺序：

1. 确认节点数量是否达到大图阈值；
2. 优先缩放到局部区域编辑，减少同时可视节点；
3. 检查是否有大量浏览器标签页占用 GPU/内存。

### 17.14 模型调用失败但提示不清晰

当前前端会将常见错误映射为可诊断文案，重点包括：

- 显存不足（OOM）
- 模型权重文件损坏
- 请求超时
- 网络/连接异常
- 权限不足或鉴权失效

若仍无法定位，请结合后端日志关键字（OOM/timeout/connection/permission）进一步确认。

---

## 18. 新手上线前最终检查（建议打印执行）

1. 后端/前端可启动  
2. 健康探针全部通过  
3. 一个 workflow 从创建到执行全流程通过  
4. 错租户访问被拒绝（404/403）  
5. system 写接口非 admin 被拒绝  
6. 跑完 tenant + security 两条回归  
7. CI 绿灯 + Step Summary 可读 + artifact 可下载  
8. 抽样验证 CSRF（写接口）与 XSS（消息渲染）  
9. 生产 `.env` 安全项复核完成

---

## 19. 你下一步该读什么

完成本教程后，建议继续读：

- `tutorial-ops-checklist.md`：发版前超短清单  
- `tutorial-incident-runbook.md`：线上故障 3 分钟卡片  
- `tutorial-security-baseline.md`：安全与审计规范（制度层）

如果你是团队负责人，建议把 `tutorial-index.md` 设为内部入口首页。

---

## 20. 附录：可直接复制执行的 API 示例（curl）

下面示例默认：

- 后端地址：`http://127.0.0.1:8000`
- 管理员 key：`admin-key`
- 操作员 key：`dev-key`
- 租户：`tenant-dev`

你可以先设置环境变量，避免重复输入：

```bash
export BASE_URL="http://127.0.0.1:8000"
export ADMIN_KEY="admin-key"
export OP_KEY="dev-key"
export TENANT_ID="tenant-dev"
```

### 20.1 健康探针

```bash
curl -s "${BASE_URL}/api/health" | jq .
curl -s "${BASE_URL}/api/health/live" | jq .
curl -s "${BASE_URL}/api/health/ready" | jq .
```

预期：返回 `healthy/alive/ready` 相关字段，HTTP 状态码 `200`。

### 20.2 读取系统配置（只读接口）

```bash
curl -s "${BASE_URL}/api/system/config" | jq .
```

### 20.3 获取 CSRF Token（写请求前）

```bash
# 保存 cookie，并拿到响应头中的 X-CSRF-Token
curl -i -s -c /tmp/ov_cookie.txt "${BASE_URL}/api/health" | tee /tmp/ov_health_headers.txt
export CSRF_TOKEN="$(rg "X-CSRF-Token:" /tmp/ov_health_headers.txt -i | awk '{print $2}' | tr -d '\r')"
echo "${CSRF_TOKEN}"
```

如果你的环境拿不到响应头 token，也可以从 cookie 中提取后回填 header。

### 20.4 更新系统配置（管理员写接口，含 CSRF）

```bash
curl -s -X POST "${BASE_URL}/api/system/config" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: ${ADMIN_KEY}" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -b /tmp/ov_cookie.txt \
  -d '{
    "runtimeAutoReleaseEnabled": true,
    "runtimeReleaseIdleTtlSeconds": 300
  }' | jq .
```

预期：`{"success": true}`。  
如果你用 operator/viewer key，预期 `403`。

### 20.5 创建 Workflow（租户内）

```bash
curl -s -X POST "${BASE_URL}/api/v1/workflows" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: ${OP_KEY}" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -b /tmp/ov_cookie.txt \
  -d '{
    "namespace": "'"${TENANT_ID}"'",
    "name": "hello-workflow",
    "description": "first workflow",
    "tags": ["demo"],
    "metadata": {}
  }' | tee /tmp/wf-create.json | jq .
```

提取 `workflow_id`：

```bash
export WORKFLOW_ID="$(jq -r '.id' /tmp/wf-create.json)"
echo "${WORKFLOW_ID}"
```

### 20.6 查询 Workflow

```bash
curl -s "${BASE_URL}/api/v1/workflows/${WORKFLOW_ID}" \
  -H "X-Api-Key: ${OP_KEY}" \
  -H "X-Tenant-Id: ${TENANT_ID}" | jq .
```

### 20.7 创建版本（最小 DAG 示例）

```bash
curl -s -X POST "${BASE_URL}/api/v1/workflows/${WORKFLOW_ID}/versions" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: ${OP_KEY}" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -b /tmp/ov_cookie.txt \
  -d '{
    "description": "v1",
    "dag": {
      "nodes": [
        {
          "id": "n1",
          "type": "start",
          "label": "start",
          "config": {}
        }
      ],
      "edges": []
    }
  }' | tee /tmp/wf-version.json | jq .
```

提取 `version_id`：

```bash
export VERSION_ID="$(jq -r '.version_id' /tmp/wf-version.json)"
echo "${VERSION_ID}"
```

### 20.8 发起执行

```bash
curl -s -X POST "${BASE_URL}/api/v1/workflows/${WORKFLOW_ID}/executions" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: ${OP_KEY}" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -b /tmp/ov_cookie.txt \
  -d '{
    "workflow_id": "'"${WORKFLOW_ID}"'",
    "version_id": "'"${VERSION_ID}"'",
    "input_data": {}
  }' | tee /tmp/wf-exec.json | jq .
```

提取 `execution_id`：

```bash
export EXECUTION_ID="$(jq -r '.execution_id' /tmp/wf-exec.json)"
echo "${EXECUTION_ID}"
```

### 20.9 查询执行状态

```bash
curl -s "${BASE_URL}/api/v1/workflows/${WORKFLOW_ID}/executions/${EXECUTION_ID}/status" \
  -H "X-Api-Key: ${OP_KEY}" \
  -H "X-Tenant-Id: ${TENANT_ID}" | jq .
```

### 20.10 跨租户访问验证（应失败）

```bash
curl -i -s "${BASE_URL}/api/v1/workflows/${WORKFLOW_ID}" \
  -H "X-Api-Key: ${OP_KEY}" \
  -H "X-Tenant-Id: tenant-other"
```

预期：`403` 或 `404`（取决于防护链路命中位置），总之不应返回资源内容。

### 20.11 管理员权限验证（非管理员调用 system 写接口）

```bash
curl -i -s -X POST "${BASE_URL}/api/system/engine/reload" \
  -H "X-Api-Key: ${OP_KEY}" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -b /tmp/ov_cookie.txt
```

预期：`403`。

### 20.12 审计日志查询（管理员）

```bash
curl -s "${BASE_URL}/api/v1/audit/logs?limit=20&offset=0" \
  -H "X-Api-Key: ${ADMIN_KEY}" \
  -H "X-Tenant-Id: ${TENANT_ID}" | jq .
```

### 20.13 一键安全回归脚本

```bash
cd perilla
python backend/scripts/security_regression.py \
  --base http://127.0.0.1:8000 \
  --api-key "${ADMIN_KEY}" \
  --tenant-id "${TENANT_ID}" \
  --json-output /tmp/security-regression.json \
  --junit-output /tmp/security-regression.xml \
  --suite-name security_regression_local

backend/scripts/test_tenant_security_regression.sh
scripts/acceptance/run_security_regression.sh
```

生成 JUnit 报告：

```bash
cd perilla
JUNIT_XML_PATH=test-reports/tenant-security-regression.xml backend/scripts/test_tenant_security_regression.sh
```

### 20.14 手动触发 CI（可选）

在 GitHub Actions 页面选择：

- `tenant-security-regression` 或 `security-regression`
- 点击 `Run workflow`
- 可选输入：`slow_threshold_seconds`（正整数）

### 20.15 清理临时变量（可选）

```bash
unset BASE_URL ADMIN_KEY OP_KEY TENANT_ID CSRF_TOKEN WORKFLOW_ID VERSION_ID EXECUTION_ID
rm -f /tmp/wf-create.json /tmp/wf-version.json /tmp/wf-exec.json /tmp/ov_cookie.txt /tmp/ov_health_headers.txt
```

### 20.16 Agent Run 幂等请求示例

```bash
export IDEM_KEY="agent-run-$(date +%s)"
curl -s -X POST "${BASE_URL}/api/v1/agents/YOUR_AGENT_ID/run" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: ${OP_KEY}" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H "Idempotency-Key: ${IDEM_KEY}" \
  -b /tmp/ov_cookie.txt \
  -d '{"input":"hello"}' | jq .
```

说明：

- 重试时保持 `Idempotency-Key` 与请求体一致；
- 若同 key 改了请求体，预期返回 `409`。

### 20.17 Workflow 审批任务查询（新格式/兼容格式）

```bash
# 新结构化格式（默认）
curl -s "${BASE_URL}/api/v1/workflows/${WORKFLOW_ID}/executions/${EXECUTION_ID}/approvals" \
  -H "X-Api-Key: ${OP_KEY}" \
  -H "X-Tenant-Id: ${TENANT_ID}" | jq .

# 兼容旧格式（含弃用提示头）
curl -i -s "${BASE_URL}/api/v1/workflows/${WORKFLOW_ID}/executions/${EXECUTION_ID}/approvals?legacy=true" \
  -H "X-Api-Key: ${OP_KEY}" \
  -H "X-Tenant-Id: ${TENANT_ID}"
```
