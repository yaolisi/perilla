# Compose 单机 / 预发生产验收清单

面向 **以 Docker Compose 为主** 的部署与预发验证；与仓库合并门禁、脚本入口对齐。

---

## 1. 每次发布前（工程门禁）

在仓库根目录执行：

| 步骤 | 命令 |
|------|------|
| 合并门禁契约测试 | `bash scripts/merge-gate-contract-tests.sh -q` |
| Helm 模板与合并门禁（若团队仍以 Chart 对齐线上/K8s） | `make helm-deploy-contract-check` |
| 完整 PR 级检查（含前端构建等） | `make pr-check` 或 `npm run ci` |

---

## 2. 环境与 Compose 配置

| 步骤 | 命令 / 说明 |
|------|-------------|
| 环境诊断 | `npm run doctor` 或 `make doctor`（需 Docker / Compose 时重点看 compose 校验） |
| 生产覆盖文件语法 | `docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml config` |
| GPU 等叠加（若使用） | 在以上命令中追加 `-f docker-compose.gpu.yml` |
| 环境变量 | 从 `.env.example` 复制并审阅；生产向 Secret/键名可与 `deploy/k8s/secret-env.example.yaml` 对照，避免与 `DEBUG=false` 安全门禁冲突 |

---

## 3. 运行中验证

| 步骤 | 命令 / 说明 |
|------|-------------|
| 健康检查脚本 | `npm run healthcheck` 或 `make healthcheck`（`scripts/healthcheck.sh`） |
| 生产安全护栏 | `npm run security-guardrails` 或 `make security-guardrails` |
| HTTP 探活 | 对实际对外地址检查存活/就绪路径（以当前 OpenAPI/契约为准；常见为 `/health`、就绪相关端点） |

---

## 4. 依赖与故障意识（按实际启用勾选）

| 项 | 说明 |
|----|------|
| PostgreSQL | 生产应使用 `DATABASE_URL`（PostgreSQL 族）；与连接池/超时等环境变量在 `DEBUG=false` 下满足门禁。 |
| Redis | 若启用推理缓存、限流或 ready 探测中的 Redis，需配置正确 URL，并知悉断连时的行为。 |
| 事件总线 | 若启用 Kafka 等，需与 `ready` 与运维预期一致。 |
| 可观测性 | 指标/日志能到达现有采集或查看方式；生产建议结构化日志（`LOG_FORMAT=json` 等）。 |
| 数据与卷 | 对持久化卷/数据库做至少一次恢复思路或演练记录。 |

---

## 5. 上线与回滚（最小闭环）

1. 按依赖顺序执行：数据库迁移（若由独立步骤或 Job 处理）再启动或滚动应用服务。  
2. 再次执行第 3 节中的健康检查与安全护栏。  
3. 回滚：使用上一镜像 tag 或回退 `docker-compose` 覆盖与 `.env` 组合；记录变更与回滚命令。

---

## 6. 与「生产级别」声明的关系

- **工程侧**：上述第 1 节与 CI/`Makefile`/`package.json` 契约对齐，降低配置与部署漂移。  
- **环境侧**：第 2–5 节须在**目标运行环境**完成并留下记录，才能视为上线就绪。
