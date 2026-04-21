# OpenVitamin Enhanced 教程索引（统一入口）

本页用于帮助团队按场景快速找到对应文档。  
建议将本页作为内部知识库入口链接。

新手若不知道先看哪一页，可先读同目录 **[README.md](README.md)**（阅读顺序、403/404/429 跳转）。

> **仓库根目录**：当以 **Standalone Docker 完整工程**（目录名通常为 `openvitamin_enhanced_docker`）分发时，下文所有命令与相对路径均以该目录为基准（包含 `backend/`、`frontend/`、`scripts/` 等）。

---

## 1. 新成员上手（先读）

- `tutorial-quickstart.md`
  - 10 分钟极简上手（启动、CSRF 校验、安全回归）

- `tutorial-quickstart-en.md`
  - 10-minute English quickstart for global/cross-language teams

- `tutorial.md`
  - 完整使用教程（环境、启动、核心功能、安全配置、测试、排障）
  - 含自治编排新增章节：幂等请求、持久化执行队列、HITL 审批闸门
  - 含前端增强章节：工作流编辑器搜索/对齐优化、知识库大列表分页、可诊断错误提示

适用：

- 首次接触项目的研发/测试/运维
- 需要从 0 到 1 完整搭建与理解系统的人

---

## 2. 发版前 5 分钟检查

- `tutorial-ops-checklist.md`
  - 运维值班版超短执行清单（阻断项、回归、CI、冒烟、签核）

适用：

- 发版前快速判断“是否可发布”
- 值班同学快速执行标准化检查

---

## 3. 故障告警后 3 分钟处置

- `tutorial-incident-runbook.md`
  - 值班故障处理流程卡片（分级、止血、定位、恢复、复盘）

适用：

- 线上告警
- 大量 403/404/429/5xx 或启动失败

---

## 4. 安全与审计规范对齐

- `README.md` — 本目录（`tutorials/`）专题索引；含 security-review 提示入口
- `security-review-hints.md` — 全面审查结论提示（中文，与 MUST 基线互补）
- `security-review-hints-en.md` — 英文摘要
- `tutorial-security-baseline.md`
  - 安全基线与审计规范版（MUST 基线、阻断规则、审批流程、门禁要求）

- `tutorial-glossary-zh-en.md`
  - 中英术语对照（安全、租户、CI、回归）

- `tutorial-glossary-product.md`
  - 产品术语版（面向非技术同学）

- `tutorial-glossary-engineering.md`
  - 工程术语版（面向研发/测试/运维）

适用：

- 安全评审
- 发布门禁标准定义
- 运维/安全治理制度沉淀

---

## 5. 推荐阅读顺序

1. `tutorial-quickstart.md`
2. `tutorial-quickstart-en.md`（如需英文）
3. `tutorial.md`
4. `security-review-hints.md`（公网/共享部署前：威胁模型与 RBAC 提示）
5. `tutorial-security-baseline.md`
6. `tutorial-glossary-zh-en.md`
7. `tutorial-glossary-product.md`
8. `tutorial-glossary-engineering.md`
9. `tutorial-ops-checklist.md`
10. `tutorial-incident-runbook.md`

---

## 5.1 术语阅读路线图（按角色）

### 产品 / 运营 / 项目

1. `tutorial-glossary-product.md`  
2. `tutorial-glossary-zh-en.md`（需要跨语言协作时）  
3. `tutorial-security-baseline.md`（了解发布门禁边界）

### 研发（前后端）

1. `tutorial-glossary-engineering.md`  
2. `tutorial-glossary-zh-en.md`  
3. `tutorial.md`（实现与调试全流程）

### 测试 / QA

1. `tutorial-quickstart.md`（快速跑通）  
2. `tutorial-glossary-engineering.md`（定位术语）  
3. `tutorial-ops-checklist.md`（发布前核对）

### 运维 / SRE / 值班

1. `tutorial-ops-checklist.md`  
2. `tutorial-incident-runbook.md`  
3. `tutorial-glossary-engineering.md`（追踪、审计、回归语义）

---

## 5.2 角色快捷命令区（可直接复制）

> 执行前默认你已在项目根目录 `openvitamin_enhanced_docker`（或同等仓库根目录）。

### 产品 / 运营 / 项目（Windows，验证系统可用）

```bash
curl -s http://127.0.0.1:8000/api/health | jq .
curl -s http://127.0.0.1:8000/api/health/ready | jq .
```

### 研发（Windows，本地安全回归）

```bash
backend/scripts/test_tenant_security_regression.sh
scripts/acceptance/run_security_regression.sh
```

### 测试 / QA（Windows，快速复核）

```bash
SECURITY_SLOW_THRESHOLD_SECONDS=20 scripts/acceptance/run_security_regression.sh
```

### 运维 / SRE / 值班（Windows，发布前最小检查）

```bash
scripts/acceptance/run_security_regression.sh
curl -sI http://127.0.0.1:8000/api/health | rg -i "X-Trace-Id|X-Request-Id"
```

---

## 5.3 Windows PowerShell 快捷命令（对应 5.2）

> 执行前默认你已在项目根目录 `openvitamin_enhanced_docker`（或同等仓库根目录），并安装了 `curl`、`jq`（可选）与 Python/Node。

### 产品 / 运营 / 项目（验证系统可用）

```powershell
curl.exe -s http://127.0.0.1:8000/api/health
curl.exe -s http://127.0.0.1:8000/api/health/ready
```

### 研发（本地安全回归）

```powershell
bash backend/scripts/test_tenant_security_regression.sh
bash scripts/acceptance/run_security_regression.sh
```

### 测试 / QA（快速复核）

```powershell
$env:SECURITY_SLOW_THRESHOLD_SECONDS="20"
bash scripts/acceptance/run_security_regression.sh
Remove-Item Env:SECURITY_SLOW_THRESHOLD_SECONDS
```

### 运维 / SRE / 值班（发布前最小检查）

```powershell
bash scripts/acceptance/run_security_regression.sh
curl.exe -I -s http://127.0.0.1:8000/api/health | Select-String "X-Trace-Id|X-Request-Id"
```

---

## 6. 快速命令入口

在 `openvitamin_enhanced_docker`（或同等仓库根目录）下执行：

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

生成 JUnit 报告：

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

说明与背景见 **`tutorial.md` → §15.5**（为何 `start_instance` 可能长时间不返回、如何用诊断环境变量）。

快速入口（默认只跑轻量项，秒级结束）：

```bash
PYTHONPATH=backend python3 backend/scripts/test_execution_kernel_integration.py
```

重型入口（Scheduler + 独立临时 SQLite）：

```bash
PYTHONPATH=backend python3 backend/scripts/test_execution_kernel_integration_heavy.py
```

卡住或超时排障（快照约每 5 秒 + 限制 `start_instance` 等待）：

```bash
EXEC_KERNEL_RUN_HEAVY_INTEGRATION=1 \
EXEC_KERNEL_INTEGRATION_DIAG=1 \
EXEC_KERNEL_START_INSTANCE_TIMEOUT_SEC=90 \
PYTHONPATH=backend python3 backend/scripts/test_execution_kernel_integration.py
```

独立 Kernel 回归（与安全鉴权联动时，可按脚本说明配置 `RBAC_TEST_ADMIN_API_KEY`、`RBAC_TEST_TENANT_ID`）：

```bash
PYTHONPATH=backend python3 backend/scripts/test_execution_kernel_regression.py
```

---

## 7. 文档维护约定（建议）

- 代码行为变更（安全、租户、鉴权）后，同步更新以下文档：
  - `tutorial.md`
  - `tutorial-security-baseline.md`
  - `tutorial-ops-checklist.md`
- 故障复盘后，更新：
  - `tutorial-incident-runbook.md`

---

## 8. 当前版本重点能力（摘要）

- Workflow 多租户双保险（入口校验 + 存储层 tenant-aware）
- API Key 与 tenant 绑定校验
- `api/system` 关键写接口管理员权限
- 请求追踪头净化与限流返回去敏
- 生产安全护栏（自动收敛 + 高危配置阻断 + strict 开关）
- tenant/security 双回归脚本 + CI 自动门禁 + Step Summary
- 前端 Workflow 编辑器搜索与大图渲染优化（节点 > 50）
- 知识库文档列表自动分页（文档 > 50）
- 前端统一错误提示映射（OOM/权重损坏/超时/网络/权限）

---

## 9. 前端测试与构建（新增）

- 单测：`cd frontend && npm run test:unit`
- E2E：`cd frontend && npm run test:e2e`（首次需 `npx cypress install`）
- 开发构建配置：`vite.config.dev.ts`
- 生产构建配置：`vite.config.prod.ts`
- 前端专项文档：
  - `docs/frontend/COMPONENTS.md`
  - `docs/frontend/API.md`
  - `docs/frontend/USAGE.md`
