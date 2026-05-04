# perilla 教程索引（统一入口）

按场景跳转；新手先看同目录 **[README.md](README.md)**（阅读顺序与错误码索引）。

**仓库根目录**：Standalone 分发（例如克隆目录名为 `perilla`）顶层，内含 `backend/`、`frontend/`、`scripts/`。下文命令默认在此目录执行。

---

## 1. 新成员上手

| 文档 | 内容 |
|------|------|
| [tutorial-quickstart.md](tutorial-quickstart.md) | 约 10 分钟：依赖、启动、探针、CSRF、回归脚本 |
| [tutorial-beginner-playbook.md](tutorial-beginner-playbook.md) | 30~60 分钟实操：功能体验、MCP 配置、完成定义 |
| [tutorial-quickstart-en.md](tutorial-quickstart-en.md) | 英文极简版 |
| [tutorial.md](tutorial.md) | 完整教程：环境、配置、功能验证、安全、测试、curl 附录 |

适用：首次搭建的研发 / 测试 / 运维。

---

## 2. 发版前检查

| 文档 | 内容 |
|------|------|
| [tutorial-ops-checklist.md](tutorial-ops-checklist.md) | 阻断项、回归、冒烟、签核 |

---

## 3. 故障处置

| 文档 | 内容 |
|------|------|
| [tutorial-debug-playbook.md](tutorial-debug-playbook.md) | 新手调试手册：高频问题、命令、回滚触发 |
| [tutorial-incident-runbook.md](tutorial-incident-runbook.md) | 分级、止血、定位、恢复、复盘 |

---

## 4. 安全与术语

| 文档 | 内容 |
|------|------|
| [tutorial-security-baseline.md](tutorial-security-baseline.md) | MUST 基线、阻断、审计、门禁 |
| [security-review-hints.md](security-review-hints.md) | 部署 / 评审对照（中文） |
| [security-review-hints-en.md](security-review-hints-en.md) | 英文摘要 |
| [tutorial-glossary-zh-en.md](tutorial-glossary-zh-en.md) | 中英术语（安全、治理） |
| [tutorial-glossary-product.md](tutorial-glossary-product.md) | 产品向术语 |
| [tutorial-glossary-engineering.md](tutorial-glossary-engineering.md) | 工程向术语 |

---

## 5. 推荐阅读顺序

1. [tutorial-quickstart.md](tutorial-quickstart.md)
2. [tutorial-beginner-playbook.md](tutorial-beginner-playbook.md)
3. [tutorial-quickstart-en.md](tutorial-quickstart-en.md)（如需英文）
4. [tutorial.md](tutorial.md)
5. [tutorial-debug-playbook.md](tutorial-debug-playbook.md)
6. [security-review-hints.md](security-review-hints.md)（公网或共享部署前）
7. [tutorial-security-baseline.md](tutorial-security-baseline.md)
8. [tutorial-glossary-zh-en.md](tutorial-glossary-zh-en.md)
9. [tutorial-glossary-product.md](tutorial-glossary-product.md)
10. [tutorial-glossary-engineering.md](tutorial-glossary-engineering.md)
11. [tutorial-ops-checklist.md](tutorial-ops-checklist.md)
12. [tutorial-incident-runbook.md](tutorial-incident-runbook.md)

### 5.1 按角色的术语路线

**产品 / 运营 / 项目**：`tutorial-glossary-product.md` → `tutorial-glossary-zh-en.md` → `tutorial-security-baseline.md`（门禁边界）。

**研发**：`tutorial-glossary-engineering.md` → `tutorial-glossary-zh-en.md` → `tutorial.md`。

**测试 / QA**：`tutorial-quickstart.md` → `tutorial-beginner-playbook.md` → `tutorial-glossary-engineering.md` → `tutorial-ops-checklist.md`。

**运维 / SRE**：`tutorial-debug-playbook.md` → `tutorial-ops-checklist.md` → `tutorial-incident-runbook.md` → `tutorial-glossary-engineering.md`。

### 5.2 角色快捷命令（Bash）

以下均在**项目根目录**执行。

**验证存活**

```bash
curl -s http://127.0.0.1:8000/api/health | jq .
curl -s http://127.0.0.1:8000/api/health/ready | jq .
```

**研发：本地安全回归**

```bash
backend/scripts/test_tenant_security_regression.sh
scripts/acceptance/run_security_regression.sh
```

**测试：慢批次阈值示例**

```bash
SECURITY_SLOW_THRESHOLD_SECONDS=20 scripts/acceptance/run_security_regression.sh
```

**运维：发布前最小检查**

```bash
scripts/acceptance/run_security_regression.sh
curl -sI http://127.0.0.1:8000/api/health | rg -i "X-Trace-Id|X-Request-Id"
```

### 5.3 Windows PowerShell 对照

**健康检查**

```powershell
curl.exe -s http://127.0.0.1:8000/api/health
curl.exe -s http://127.0.0.1:8000/api/health/ready
```

**安全回归**

```powershell
bash backend/scripts/test_tenant_security_regression.sh
bash scripts/acceptance/run_security_regression.sh
```

**慢阈值**

```powershell
$env:SECURITY_SLOW_THRESHOLD_SECONDS="20"
bash scripts/acceptance/run_security_regression.sh
Remove-Item Env:SECURITY_SLOW_THRESHOLD_SECONDS
```

**运维最小检查**

```powershell
bash scripts/acceptance/run_security_regression.sh
curl.exe -I -s http://127.0.0.1:8000/api/health | Select-String "X-Trace-Id|X-Request-Id"
```

### 5.4 合并门禁与 Lint（研发）

与 CI `backend-static-analysis` 对齐的摘要见根目录 [README.md](../README.md)「本地门禁与 CI 对齐」。常用命令：

```bash
make install-lint-tools
make merge-gate-contract-tests
bash scripts/production-preflight.sh
```

`make pr-check` / `make pr-check-fast` 已涵盖其中大部分步骤；细颗粒度说明见 [docs/GETTING_STARTED_ZH.md §5](../docs/GETTING_STARTED_ZH.md#5-常用验证命令)（**§5.5**）。

---

## 6. 安全回归与 Kernel 脚本入口

在项目根目录：

```bash
python backend/scripts/security_regression.py \
  --base http://127.0.0.1:8000 \
  --api-key "your-admin-key" \
  --tenant-id default \
  --json-output /tmp/security-regression.json \
  --junit-output /tmp/security-regression.xml \
  --suite-name security_regression_local

backend/scripts/test_tenant_security_regression.sh
scripts/acceptance/run_security_regression.sh
```

JUnit 示例：

```bash
python backend/scripts/security_regression.py \
  --base http://127.0.0.1:8000 \
  --api-key "your-admin-key" \
  --tenant-id default \
  --junit-output test-reports/security-regression.xml \
  --suite-name security_regression_ci

JUNIT_XML_PATH=test-reports/tenant-security-regression.xml backend/scripts/test_tenant_security_regression.sh
```

### 6.1 Execution Kernel 集成测试（可选）

背景与排障见 **[tutorial.md](tutorial.md)** 中「Execution Kernel 集成测试」一节。

轻量（默认）：

```bash
PYTHONPATH=backend python3 backend/scripts/test_execution_kernel_integration.py
```

重型（Scheduler + 临时 SQLite）：

```bash
PYTHONPATH=backend python3 backend/scripts/test_execution_kernel_integration_heavy.py
```

诊断与超时示例：

```bash
EXEC_KERNEL_RUN_HEAVY_INTEGRATION=1 \
EXEC_KERNEL_INTEGRATION_DIAG=1 \
EXEC_KERNEL_START_INSTANCE_TIMEOUT_SEC=90 \
PYTHONPATH=backend python3 backend/scripts/test_execution_kernel_integration.py
```

独立 Kernel 回归：

```bash
PYTHONPATH=backend python3 backend/scripts/test_execution_kernel_regression.py
```

（若启用敏感路由鉴权，按脚本说明配置 `RBAC_TEST_ADMIN_API_KEY`、`RBAC_TEST_TENANT_ID`。）

---

## 7. 文档维护约定

- 安全 / 租户 / 鉴权变更：同步 [tutorial.md](tutorial.md)、[tutorial-security-baseline.md](tutorial-security-baseline.md)、[tutorial-ops-checklist.md](tutorial-ops-checklist.md)。
- 故障复盘：更新 [tutorial-incident-runbook.md](tutorial-incident-runbook.md)。

---

## 8. 当前版本能力摘要（文档层）

- 租户强制路径集合：`backend/middleware/tenant_paths.py`（聊天、会话、记忆、知识库、agent 会话、VLM、workflow、audit、system 等前缀）；须 **`X-Tenant-Id`** + API Key–租户绑定  
- 数据面 tenant-aware：Workflow、会话、知识库、记忆、治理审计等；MCP/Skills 等控制面按中间件租户解析（见 `resolve_api_tenant_id`）  
- API Key 与租户绑定  
- `api/system` 关键写接口管理员权限  
- 追踪头净化与限流响应去敏  
- 生产护栏（自动收敛、高危阻断、`SECURITY_GUARDRAILS_STRICT`）  
- tenant / security 双回归 + CI  
- Workflow 编辑器搜索与大图优化；知识库列表分页；统一错误提示映射  

---

## 9. 前端测试与构建

- 单元测试：`cd frontend && npm run test:unit`  
- E2E：`cd frontend && npm run test:e2e`（首次可能需 `npx cypress install`）  
- Vite：`vite.config.dev.ts`、`vite.config.prod.ts`、`vite.config.shared.ts`  
- 详见 [docs/frontend/COMPONENTS.md](../docs/frontend/COMPONENTS.md)、[API.md](../docs/frontend/API.md)、[USAGE.md](../docs/frontend/USAGE.md)  
