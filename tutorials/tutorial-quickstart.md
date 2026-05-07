# perilla 10 分钟极简上手

目标：第一次接触仓库的人，在约 10 分钟内完成 **启动 → 健康检查 → CSRF 验证 → 安全回归脚本**。

完整内容与排障见 **[README.md](README.md)**、**[tutorial.md](tutorial.md)**。若你负责合入 `main`，合并前建议了解根目录 README「**本地门禁与 CI 对齐**」与 `make pr-check-fast` / `make pr-check`（详见 [GETTING_STARTED_ZH.md](../docs/GETTING_STARTED_ZH.md#5-常用验证命令)）。

---

## 你将完成的事

1. 安装依赖并启动前后端（推荐与仓库脚本一致的 Conda 环境）  
2. 调用健康探针  
3. 验证写请求的 CSRF 链路  
4. （推荐）跑通租户与安全两条回归脚本  

---

## 前置条件

- Python 3.11+、Node.js 18+、Conda（推荐）  
- 已进入**项目根目录**（Standalone 常为克隆目录 `perilla`）

```bash
python --version
node --version
```

---

## 依赖安装（首次）

与根目录 `run-backend.sh` 对齐：环境名 **`ai-inference-platform`**。

```bash
conda create -n ai-inference-platform python=3.11 -y
cd backend
conda run -n ai-inference-platform pip install -r requirements.txt
cd ../frontend && npm install && cd ..
```

若已在激活的环境中，可直接 `pip install` / `npm install`。

---

## 启动服务

**推荐（项目根目录）**

```bash
./run-all.sh
```

**或分开展示**

```bash
./run-backend.sh    # 终端 A
./run-frontend.sh   # 终端 B
```

默认：后端 **`http://127.0.0.1:8000`**，前端 **`http://127.0.0.1:5173`**（与 `vite.config.dev.ts` 一致）。须**同时**跑通两端；仅前端会出现 **Failed to fetch**。开发环境下未设置 `VITE_API_URL` 时，请求经 Vite 代理到本机 8000；详见 **[tutorial.md](tutorial.md) §6.3**、**§17.9**。

---

## 健康检查（必做）

```bash
curl -s http://127.0.0.1:8000/api/health | jq .
curl -s http://127.0.0.1:8000/api/health/live | jq .
curl -s http://127.0.0.1:8000/api/health/ready | jq .
```

预期：HTTP 200，状态字段正常。

---

## CSRF 写请求（必做）

先访问安全方法，写入 cookie 并读取响应头中的 token（需安装 [ripgrep](https://github.com/BurntSushi/ripgrep) `rg`）：

```bash
curl -i -s -c /tmp/ov_cookie.txt http://127.0.0.1:8000/api/health | tee /tmp/ov_headers.txt
export CSRF_TOKEN="$(rg "X-CSRF-Token:" /tmp/ov_headers.txt -i | awk '{print $2}' | tr -d '\r')"
echo "$CSRF_TOKEN"
```

示例写请求（按你环境替换 Key 与租户）：

```bash
curl -s -X POST "http://127.0.0.1:8000/api/system/config" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: admin-key" \
  -H "X-Tenant-Id: tenant-dev" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -b /tmp/ov_cookie.txt \
  -d '{"runtimeAutoReleaseEnabled": true}' | jq .
```

缺少或错误的 `X-CSRF-Token` 应返回 **403**。

---

## 安全回归（强烈推荐）

在项目根目录：

```bash
backend/scripts/test_tenant_security_regression.sh
scripts/acceptance/run_security_regression.sh
```

通过：退出码 0，输出含 `passed` / 成功摘要。

报告位置：

- `backend/test-reports/tenant-security-summary.md`  
- `test-reports/security-regression-summary.md`  

---

## 账号与设置（可选 · 与 tutorial.md §8.2 同步摘要）

控制台无独立账号密码登录；身份依赖浏览器保存的 **API Key** 与 **租户**。完整说明见 **[tutorial.md](tutorial.md)** 第 **8.2** 节。

**入口：** 侧边栏 **Settings**，默认 **`/settings/general`**。

| 页面 | 路由 | 做什么 |
|------|------|--------|
| **General** | `/settings/general` | 离线模式、**界面语言**（`platform-language`）、**主题**（`platform-theme`）、数据目录与默认推理参数等 → **保存** 写入网关侧配置。 |
| **Backend** | `/settings/backend` | **Security Context**：**Admin API Key**（→ `X-Api-Key`，存 `ai_platform_api_key`）、**Tenant ID**（→ `X-Tenant-Id`，存 `ai_platform_tenant_id`）→ **Save Security Context**；**Reload** / **Clear Security Context** 管理本机存储。 |

Key 与租户仅存浏览器本机，清除站点数据后需重填。其它 Settings 子页（备份、Runtime、YOLO、ASR、MCP 等）见主教程 **§8.2 C**。

---

## 本地化大模型（可选 · 与 tutorial.md §8.1 同步摘要）

推理一律经 **FastAPI 网关**；前端只配目录与清单。完整步骤与说明见 **[tutorial.md](tutorial.md)** 第 **8.1** 节。

**1）全局数据目录**

- **Settings → General**：设置 **数据目录**（`dataDirectory`，默认常为 `~/.local-ai/models/`）并保存。

**2）磁盘本机模型（`backend=local`）**

- 在该目录下为每个模型建子文件夹，内含 **`model.json`**；可按类型放在 `llm/`、`vlm/` 等子目录下，或根目录平铺（见主教程）。
- `model.json` 至少含：`model_id`、`name`、`model_type`、`runtime`、权重相对路径 **`path`**。
- **Models** 页点 **扫描**，用 **「仅本地」** 筛选磁盘模型 → **配置** 进入 `/models/<id>/config`（仅 `local` 显示编辑器）；保存即更新网关 manifest。
- UI **浏览目录** 失败时，在后端 `.env` 配置 **`FILE_READ_ALLOWED_ROOTS`** 包含模型所在盘路径（勿用 `/`）。

**3）本机 Ollama / LM Studio**

- 先在本机启动服务（如 `11434` / `1234`）。
- **Models → 添加云端模型**：选 **Ollama** 或 **LM Studio**，**Base URL** 填本机地址并填模型 ID；亦可依赖网关启动后的自动扫描。
- 界面「本地/云端」筛选里，此类会归在 **云端** 一侧（与磁盘 `local` 不同）。

**4）验证**

- **Models** 可见条目 → **Chat** 中选模型试发一条消息；失败时对照前端提示与后端日志（路径、显存、运行时等）。

---

## 云端大模型（可选 · 与 tutorial.md §8.3 同步摘要）

通过 **HTTP API** 接入外部或本机 OpenAI 兼容服务；网关 **`POST /api/models`** 注册。完整步骤见 **[tutorial.md](tutorial.md)** 第 **8.3** 节。

**前置：** **Settings → Backend → Security Context** 中的 **`X-Api-Key` 须为管理员角色**，否则注册返回 **401/403**。

**操作：** **Models** → **添加云端模型** → 选提供商（OpenAI / Gemini / DeepSeek / Kimi / LM Studio / Ollama / Custom）→ 填 **提供商模型 ID**（必填）、显示名、可选系统 ID → **Base URL**、**API Key**（LM Studio / Ollama 可为空）→ **注册**。列表可用 **「仅云端」** 筛选。

**后续：** 列表点 **Configure** 打开侧栏，可改上下文、温度、Base URL、Key 等（**`PATCH /api/models/{id}`**，仍为管理员操作）。

**验证：** **Chat** 中选该模型试聊；失败时查 Key 权限、URL、模型 ID 与后端日志。

---

## Skill 与 MCP（可选 · 与 tutorial.md §8.4～§8.5 同步摘要）

技能（Skill）经网关统一执行；**MCP 不在首页单独入口**，而在 **Settings → MCP** 配置 Server，并把工具 **导入为 Skill** 后使用。完整步骤见 **[tutorial.md](tutorial.md)** 第 **8.4、8.5** 节。

**Skill（你要做的事）**

- 主导航 **`/skills`**：浏览；**`/skills/create`** 自定义技能；**`/skills/:id`** 看详情（MCP 导入的技能会显示连接信息）。  
- **Agent**：创建/编辑时勾选技能（含带 **MCP** 标记的项）→ 保存 → 在执行界面验证。  
- **Workflow**：节点库 **Tool → Skill**（画布上不叫 MCP）→ 右侧选 **`tool_name`**，展开 **Schema·Inputs** 填参数 → 保存版本并执行。

**MCP（你要做的事）**

- 前置：**§8.2** 使用 **管理员 `X-Api-Key`**（`/api/mcp/*` 要求 admin）。  
- **`/settings/mcp`**：**Probe** 验证 stdio 命令或 HTTP Base URL → **添加 MCP Server** → 在列表中 **列出 Tools / 导入为技能**。  
- 导入后到 **`/skills`** 确认；再通过 **Agent** 或工作流 **Skill** 节点调用（**无单独「MCP 节点」**）。

---

## CI 手动触发（可选）

GitHub Actions：`tenant-security-regression`、`security-regression`。  
可选输入：`slow_threshold_seconds`（正整数）。PR 默认约 20s，main/master 约 30s；结果见 Step Summary 与 Artifacts。

---

## 常见失败速查

| 现象 | 处理 |
|------|------|
| **Failed to fetch** / 无法连接后端 | 先启动后端（`8000` 可打开 `/docs`），再开前端；核对 **§6.3**、`VITE_API_URL` 与 **127.0.0.1**；见 **tutorial.md §17.9** |
| **401** 于 `/api/system/config`、`/api/knowledge-bases` 等 | 开发默认下多为鉴权/scope；核对 **`DEBUG`**、**`RBAC_ADMIN_API_KEYS`**、**`API_KEYS_JSON`/`API_KEY_SCOPES_JSON`**，或到 **Settings → Backend** 填管理员 Key；见 **tutorial.md §8.2**、**§17.10** |
| 聊天无助手字（Ollama **R1** 等） | 推理流可能先 **`thinking`** 后 **`content`**；更新后端并重启网关；见 **tutorial.md §17.11** |
| `403 CSRF token validation failed` | 先 `GET /api/health` 拿 cookie 与 header，再发写请求 |
| **400** `tenant id required for protected path` | 路径是否命中租户强制前缀（**`backend/middleware/tenant_paths.py`**）；curl/脚本须显式 `X-Tenant-Id`，见 **tutorial.md §10.4** |
| Workflow **403/404** | 核对 `X-Tenant-Id`、namespace、Key 与租户绑定 |
| **429** | 降低频率或调整限流配置 |
| **409**（Idempotency） | 同 Key 须配同请求体；体变则换 Key |
| 执行 **PAUSED** | 是否存在 `approval` 节点；完成或拒绝审批 |

---

## 接下来读什么

- [tutorial-beginner-playbook.md](tutorial-beginner-playbook.md) — 新手实操版（上手与使用）  
- [tutorial.md](tutorial.md) — 全量教程  
- [tutorial-debug-playbook.md](tutorial-debug-playbook.md) — 调试手册（定位与回滚）  
- [tutorial-index.md](tutorial-index.md) — 索引与命令汇总；**§1.1** 与主教程第 **8.1～8.5** 节（本地 / 账号 / 云端模型 / Skill / MCP）对照  
- [tutorial-ops-checklist.md](tutorial-ops-checklist.md) — 发版清单  
