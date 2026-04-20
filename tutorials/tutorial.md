# OpenVitamin Enhanced 新手友好详细教程（从 0 到可上线）

> 本文已基于最新安全增强改造更新：包含 **前端 XSS 防护**、**后端 CSRF 防护**、**分层安全回归脚本**、**双工作流 CI（tenant/security）**、**Step Summary + 慢批次阈值告警**。

本教程专门为新手编写，目标是让你即使第一次接触项目，也能按步骤完成：

1. 环境安装  
2. 前后端启动  
3. 核心功能验证  
4. 安全配置落地  
5. 回归测试与上线前检查

如果你是第一次看文档，建议从头到尾照着做一遍。

快速入口：

- `tutorial-quickstart.md`：10 分钟极简上手  
- `tutorial-index.md`：教程导航总入口  
- `tutorial-ops-checklist.md`：发版前 3~5 分钟清单  
- `tutorial-incident-runbook.md`：线上故障 3 分钟处置  
- `tutorial-security-baseline.md`：安全基线与审计规范
- `tutorial-glossary-zh-en.md`：中英术语对照表
- `tutorial-glossary-product.md`：产品术语版
- `tutorial-glossary-engineering.md`：工程术语版

---

## 1. 先理解：这个项目是做什么的

**OpenVitamin Enhanced** 是一个本地优先的 AI 平台，你可以把它理解为：

- **前端控制台**：可视化操作界面（Vue）
- **后端网关**：统一接入模型、工作流、审计、安全治理（FastAPI）
- **能力模块**：Agent、Tool、Skill、Workflow、Image、RAG 等

它不是“单一聊天应用”，而是“可治理的 AI 能力平台”。

你现在这个增强版已经包含了很多生产化能力：

- 多租户隔离（入口 + 存储层双保险）
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
# Standalone 完整分发目录通常为 openvitamin_enhanced_docker（或你克隆的本仓库根目录）
cd openvitamin_enhanced_docker
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

### 5.2 生产环境建议（最小安全基线）

```dotenv
DEBUG=false

RBAC_ENABLED=true
RBAC_ENFORCEMENT=true
RBAC_ADMIN_API_KEYS=admin-key-1
RBAC_OPERATOR_API_KEYS=op-key-1,op-key-2
RBAC_VIEWER_API_KEYS=view-key-1

TENANT_ENFORCEMENT_ENABLED=true
TENANT_HEADER_NAME=X-Tenant-Id
TENANT_API_KEY_BINDING_ENABLED=true
TENANT_API_KEY_TENANTS_JSON={"admin-key-1":["*"],"op-key-1":["tenant-a"],"op-key-2":["tenant-b"]}

API_RATE_LIMIT_ENABLED=true
API_RATE_LIMIT_REQUESTS=120
API_RATE_LIMIT_WINDOW_SECONDS=60

AUDIT_LOG_ENABLED=true
AUDIT_LOG_PATH_PREFIXES=/api/v1/workflows,/api/system

CORS_ALLOWED_ORIGINS=https://console.example.com
FILE_READ_ALLOWED_ROOTS=/data,/models

TOOL_NET_HTTP_ENABLED=true
TOOL_NET_HTTP_ALLOWED_HOSTS=api.openai.com,*.internal.example.com
TOOL_NET_WEB_ENABLED=false

SECURITY_GUARDRAILS_STRICT=true
```

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

- `namespace` 应与 `X-Tenant-Id` 一致（增强版会强制对齐）
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

---

## 10. 多租户与权限（必须理解）

### 10.1 三层安全关系

1. **RBAC 角色**：admin/operator/viewer  
2. **API Key-租户绑定**：一个 key 可以访问哪些 tenant  
3. **资源租户隔离**：Workflow 存储层 tenant-aware 查询

### 10.2 为什么会出现“看得见创建，看不见查询”

通常是请求头变化导致：

- 创建时 `X-Tenant-Id=tenant-a`
- 查询时 `X-Tenant-Id=tenant-b`

系统会按策略返回 `404`。

### 10.3 快速排查顺序

1. 看请求头 `X-Api-Key` / `X-Tenant-Id`
2. 看 `TENANT_API_KEY_TENANTS_JSON` 是否绑定
3. 看 resource namespace 是否一致

---

## 11. 系统配置接口怎么安全使用

关键接口：

- `POST /api/system/config`
- `POST /api/system/engine/reload`
- `POST /api/system/feature-flags`
- `POST /api/system/kernel/*`

注意：

- 这些写接口在增强版已经要求管理员权限
- 如果你是 operator/viewer，请求会被拒绝（403）

---

## 12. 审计、追踪、限流（可观测性）

### 12.1 请求追踪

每次请求应看到：

- `X-Request-Id`
- `X-Trace-Id`
- `X-Response-Time-Ms`

增强版已对 `request_id` 做净化，避免 header 污染。

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

### 13.1 自动收敛

当 `DEBUG=false` 时，系统会自动收敛关键开关：

- `RBAC_ENABLED=true`
- `RBAC_ENFORCEMENT=true`
- `TENANT_ENFORCEMENT_ENABLED=true`
- `TENANT_API_KEY_BINDING_ENABLED=true`

### 13.2 启动阻断（Fail-Fast）

命中以下风险会拒绝启动：

- `FILE_READ_ALLOWED_ROOTS="/"`  
- `CORS_ALLOWED_ORIGINS=""`  
- `TOOL_NET_HTTP_ENABLED=true` 且 `TOOL_NET_HTTP_ALLOWED_HOSTS=""`

### 13.3 严格模式开关

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

### 15.2 security 安全回归（acceptance 聚合脚本）

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

### 15.3 慢批次阈值告警（本地）

可选设置阈值（秒）：

```bash
SECURITY_SLOW_THRESHOLD_SECONDS=20 scripts/acceptance/run_security_regression.sh
TENANT_SECURITY_SLOW_THRESHOLD_SECONDS=20 backend/scripts/test_tenant_security_regression.sh
```

当超过阈值，摘要会出现 `⚠️` 和 Slow Batches 区块。

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

## 17. 常见错误与解决方案（新手高频）

### 16.1 启动失败：Unsafe production security configuration

处理：

1. `FILE_READ_ALLOWED_ROOTS` 不要是 `/`
2. `CORS_ALLOWED_ORIGINS` 不要为空
3. 若开启 HTTP 工具，配置 `TOOL_NET_HTTP_ALLOWED_HOSTS`

### 16.2 403（权限问题）

处理：

1. 检查 API Key 是否存在
2. 检查 RBAC 角色映射
3. 检查是否调用了 admin-only 接口

### 16.3 404（跨租户）

处理：

1. 检查 `X-Tenant-Id`
2. 检查 API Key 的 tenant 绑定
3. 检查 workflow namespace

### 16.4 429（限流）

处理：

1. 提高限流阈值（谨慎）
2. 降低轮询频率
3. 合并批量请求

### 16.5 全量 pytest 因三方依赖失败

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
cd openvitamin_enhanced_docker
backend/scripts/test_tenant_security_regression.sh
scripts/acceptance/run_security_regression.sh
```

生成 JUnit 报告：

```bash
cd openvitamin_enhanced_docker
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
