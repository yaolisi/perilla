# perilla — 5 分钟快速上手

**本地优先、网关中心化**：前端只做控制台，所有模型与工具调用统一经过 FastAPI 网关。

[English README](README_EN.md)

---

## 目录（按读者分层）

- [1) 5 分钟快速启动](#1-5-分钟快速启动)
- [2) 新手路径（上手-使用-调试）](#2-新手路径上手-使用-调试)
- [3) 研发路径（开发-测试-发布）](#3-研发路径开发-测试-发布)
- [4) 运维路径（安全-发布-故障）](#4-运维路径安全-发布-故障)
- [5) 详细文档入口（下沉到 docs/）](#5-详细文档入口下沉到-docs)
- [6) 常见命令速查](#6-常见命令速查)

---

## 1) 5 分钟快速启动

### 环境要求

- Python 3.11+
- Node.js 18+
- Conda（推荐）

### 启动（Conda）

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

### 健康检查

```bash
curl -s http://127.0.0.1:8000/api/health | jq .
curl -s http://127.0.0.1:8000/api/health/ready | jq .
```

---

## 2) 新手路径（上手-使用-调试）

1. 10 分钟上手：`tutorials/tutorial-quickstart.md`
2. 实操版（30~60 分钟）：`tutorials/tutorial-beginner-playbook.md`
3. 调试手册：`tutorials/tutorial-debug-playbook.md`
4. 完整教程索引：`tutorials/tutorial-index.md`

推荐先跑一遍核心页面：

- `/models` -> `/chat` -> `/images` -> `/agents` -> `/workflow`

---

## 3) 研发路径（开发-测试-发布）

### 开发与架构

- 开发指南：`docs/DEVELOPMENT_GUIDE.md`
- 总体架构：`docs/architecture/ARCHITECTURE.md`
- Agent 架构：`docs/architecture/AGENT_ARCHITECTURE.md`

### MCP 相关（锚点直达）

- 中文详细：[`docs/GETTING_STARTED_ZH.md#4-mcp-集成与配置`](docs/GETTING_STARTED_ZH.md#4-mcp-%E9%9B%86%E6%88%90%E4%B8%8E%E9%85%8D%E7%BD%AE)
- 英文详细：[`docs/GETTING_STARTED_EN.md#4-mcp-integration-and-configuration`](docs/GETTING_STARTED_EN.md#4-mcp-integration-and-configuration)

---

## 4) 运维路径（安全-发布-故障）

- 部署文档：`docs/DEPLOYMENT.md`
- 安全基线：`tutorials/tutorial-security-baseline.md`
- 发布清单：`tutorials/tutorial-ops-checklist.md`
- 故障手册：`tutorials/tutorial-incident-runbook.md`

生产建议：

- `DEBUG=false`
- `SECURITY_GUARDRAILS_STRICT=true`

---

## 5) 详细文档入口（下沉到 docs/）

为保持 README 可快速阅读，详细内容已下沉：

- 中文详细总览：`docs/GETTING_STARTED_ZH.md`
- 英文详细总览：`docs/GETTING_STARTED_EN.md`

重点锚点：

- 中文命令：[`#5-常用验证命令`](docs/GETTING_STARTED_ZH.md#5-常用验证命令)
- 中文 FAQ：[`#6-故障排查-faq`](docs/GETTING_STARTED_ZH.md#6-故障排查-faq)
- 中文发布清单：[`#7-生产发布最小清单`](docs/GETTING_STARTED_ZH.md#7-生产发布最小清单)

### 命名与迁移边界（目录名 / Redis）

- **仓库目录名 vs 包名**：本地克隆目录可能仍为历史路径 `openvitamin_enhanced_docker`；根目录 `package.json` 的 `name` 为 `perilla-enhanced-docker`，运行时品牌以配置与 UI（`settings.app_name` 等）为准。**不要求**仅为对齐而重命名磁盘目录；若你自行改名，请同步更新脚本、CI、文档中的路径引用。

- **Redis 键 vs Pub/Sub 频道**：启动时若开启迁移（`settings` 中 `redis_legacy_openvitamin_prefix_migrate_on_startup`），仅对 Redis **键（KEY）** 执行 `SCAN`+`RENAME`，将历史前缀 `openvitamin:*` 迁到当前 `inference_cache_prefix` / `event_bus_channel_prefix` / `kb_vector_snapshot_redis_prefix` 等。**Pub/Sub 频道名不是键**，不在此次迁移范围内；事件总线频道由当前配置重新订阅/发布即可。

- **Prometheus**：`metrics_legacy_openvitamin_names_enabled` 为真时，进程内除 `perilla_*` 外会并行注册旧名 `openvitamin_*`，便于过渡期仪表盘；关闭后仅导出 `perilla_*`。

---

## 6) 常见命令速查

```bash
make pr-check-fast
make pr-check
scripts/status.sh
scripts/logs.sh
scripts/healthcheck.sh
```

EventBus 定向：

```bash
PYTHONPATH=backend pytest -q \
  backend/tests/test_event_bus_smoke_summary_contract.py \
  backend/tests/test_event_bus_smoke_result_contract.py
```

---

## 联系方式

- 微信：fengzhizi715，virus_gene
- 邮箱：fengzhizi715@126.com，yaolisi@hotmail.com

---

## 贡献与许可证

- 贡献指南：`CONTRIBUTING.md`
- 计划采用：Apache License 2.0
