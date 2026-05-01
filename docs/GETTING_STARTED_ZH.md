# perilla 详细上手与运维指南（中文）

> 本文承接仓库根目录 `README.md` 的详细内容，面向需要深入使用、调试和上线的人。

## 目录

- [1. 能力总览](#1-能力总览)
- [2. 架构与关键路径](#2-架构与关键路径)
- [3. 快速开始（详细版）](#3-快速开始详细版)
- [4. MCP 集成与配置](#4-mcp-集成与配置)
- [5. 常用验证命令](#5-常用验证命令)
- [6. 故障排查 FAQ](#6-故障排查-faq)
- [7. 生产发布最小清单](#7-生产发布最小清单)
- [8. 深入文档导航](#8-深入文档导航)

## 1. 能力总览

- 统一推理：`LLM`、`VLM`、`Embedding`、`ASR`、`Image Generation`
- Agent/Workflow 编排与执行治理
- 知识库/RAG、记忆、审计、备份与系统配置
- 本地优先，前端不直连模型，统一经 FastAPI 网关

## 2. 架构与关键路径

- 网关中心化：`UI -> FastAPI Gateway -> Runtime/Tool/Store`
- Agent 路径：`Planner -> Skill/Tool -> Gateway -> Result`
- Workflow 路径：`Control Plane -> Execution Kernel -> Queue/Lease -> Events`
- 文生图路径：`Image API -> Job Manager -> Runtime Queue -> Store/Files`

详细架构见：

- `docs/architecture/ARCHITECTURE.md`
- `docs/architecture/AGENT_ARCHITECTURE.md`

## 3. 快速开始（详细版）

### 3.1 Conda（开发推荐）

```bash
conda create -n ai-inference-platform python=3.11 -y
cd backend
conda run -n ai-inference-platform pip install -r requirements.txt
cd ../frontend && npm install && cd ..
./run-all.sh
```

默认地址：

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`

### 3.2 Docker（一致环境）

```bash
bash scripts/install.sh
# 或 make bootstrap
```

常用命令：

```bash
scripts/status.sh
scripts/logs.sh
scripts/healthcheck.sh
scripts/doctor.sh
```

## 4. MCP 集成与配置

### 4.1 后端关键文件

- `backend/api/mcp.py`
- `backend/core/mcp/protocol.py`
- `backend/core/mcp/client.py`
- `backend/core/mcp/http_client.py`
- `backend/core/mcp/server_manager.py`
- `backend/core/mcp/service.py`
- `backend/core/data/models/mcp_server.py`

### 4.2 前端关键文件

- `frontend/src/components/settings/SettingsMcpView.vue`
- `frontend/src/views/SettingsMcpView.vue`
- `frontend/src/services/api.ts`

### 4.3 建议配置流程

1. 在 `/settings/mcp` 创建/修改 MCP Server
2. 检查 transport/base_url/鉴权配置
3. 保存后在 Agent 页面验证可见和可调用
4. 跑 MCP 定向测试（见下一节）

## 5. 常用验证命令

### 5.1 快速检查

```bash
make pr-check-fast
```

### 5.2 全量检查

```bash
make pr-check
```

### 5.3 EventBus 定向

```bash
PYTHONPATH=backend pytest -q \
  backend/tests/test_event_bus_smoke_summary_contract.py \
  backend/tests/test_event_bus_smoke_result_contract.py \
  backend/tests/test_event_bus_smoke_gh_trigger_inputs_audit_contract.py \
  backend/tests/test_event_bus_smoke_gh_inputs_snapshot_contract.py
```

### 5.4 MCP 定向

```bash
PYTHONPATH=backend pytest -q \
  backend/tests/test_mcp_protocol.py \
  backend/tests/test_mcp_adapter.py \
  backend/tests/test_mcp_http_client_lifecycle.py
```

## 6. 故障排查 FAQ

### 6.1 401/403

- 核对 `X-Api-Key`、`X-Tenant-Id`、CSRF 头和 cookie
- 检查 `.env` 的 RBAC/租户策略

### 6.2 模型不可见

- 检查 `model.json` 和 runtime 依赖
- 查看后端日志是否 provider 初始化失败

### 6.3 MCP 配置后不可用

- 检查 server enable 状态、base_url 可达性
- 跑 MCP 定向测试定位协议/生命周期问题

### 6.4 EventBus 校验失败

- 当前规则已拒绝 bool 伪整型（`True/False` 不视作合法数值）
- 先看报错是否类型问题，再看业务字段语义

## 7. 生产发布最小清单

- 发布前：`make pr-check` 通过
- 发布时：`DEBUG=false`、`SECURITY_GUARDRAILS_STRICT=true`
- 发布后：T+10/T+30 抽查 MCP、配置刷新、EventBus 校验日志
- 回滚策略：先高风险业务改动，再基础层与工程脚本

## 8. 深入文档导航

- 部署：`docs/DEPLOYMENT.md`
- 开发：`docs/DEVELOPMENT_GUIDE.md`
- API：`docs/api/API_DOCUMENTATION.md`
- 本地模型：`docs/local_model/LOCAL_MODEL_DEPLOYMENT.md`
- 教程索引：`tutorials/tutorial-index.md`
- 插件开发：`docs/plugins/PLUGIN_DEVELOPMENT_ZH.md`
- 工作流编排概览：`docs/workflow/WORKFLOW_ORCHESTRATION_OVERVIEW_ZH.md`
- vLLM / TensorRT-LLM 接入：`docs/inference/VLLM_TENSORRT_BACKEND_ZH.md`
