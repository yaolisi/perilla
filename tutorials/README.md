# perilla 教程目录

面向 **Standalone** 仓库（本目录随代码分发）。不知从何读起时，先看 **[tutorial-index.md](tutorial-index.md)**。

---

## 建议阅读顺序（约 30～60 分钟）

| 顺序 | 文档 | 说明 |
|------|------|------|
| 1 | [tutorial-quickstart.md](tutorial-quickstart.md) | 约 10 分钟：启动、健康检查、CSRF、安全回归脚本 |
| 2 | [tutorial-beginner-playbook.md](tutorial-beginner-playbook.md) | 30~60 分钟实操：核心页面体验、MCP 配置、完成定义 |
| 3 | [tutorial.md](tutorial.md) | 主教程：环境、`.env`、租户/RBAC、测试与排障 |
| 4 | [tutorial-debug-playbook.md](tutorial-debug-playbook.md) | 高频问题排查、命令清单、回滚触发条件 |
| 5 | [tutorial-security-baseline.md](tutorial-security-baseline.md) | 生产 MUST、阻断规则、变更审批 |

有经验者可跳过步骤 1~2，从主教程「配置 `.env`」切入。

---

## 按问题跳转

| 现象或任务 | 打开 |
|------------|------|
| 刚上手 | [tutorial-quickstart.md](tutorial-quickstart.md) → [tutorial-beginner-playbook.md](tutorial-beginner-playbook.md) |
| 写接口 **403**（含 CSRF） | [tutorial.md](tutorial.md) → **常见错误** → 403 / CSRF 小节 |
| **404**（资源刚创建却查不到） | [tutorial.md](tutorial.md) → **多租户**；核对 `X-Tenant-Id` |
| **429** | 限流与 Agent 上传并发；见主教程对应小节 |
| **409**（幂等冲突） | 主教程「Idempotency-Key」 |
| **400** `tenant id required` | 主教程 **§10.4 租户强制路径**（含 chat/sessions/memory 等，不单 system） |
| Workflow 停在 **PAUSED** | `approval` 节点与审批 API；见主教程 |
| 知识库文档多、列表卡 | 文档数大于阈值时分页；见主教程 |
| Workflow 节点多、画布卡 | 大图渲染优化说明；见主教程 |
| 模型报错文案不清晰 | 前端错误映射 + 后端日志关键字；见主教程 |
| 本地跑安全回归 | [tutorial-beginner-playbook.md](tutorial-beginner-playbook.md) 与 [tutorial.md](tutorial.md) **测试与回归** |
| Execution Kernel 集成测试卡住 | 主教程 **Execution Kernel 集成测试**；环境变量诊断 |
| 发版前快速核对 | [tutorial-ops-checklist.md](tutorial-ops-checklist.md) |
| MCP 配置已保存但不可用 | [tutorial-debug-playbook.md](tutorial-debug-playbook.md) |
| 线上告警 / 大量错误 | [tutorial-debug-playbook.md](tutorial-debug-playbook.md) → [tutorial-incident-runbook.md](tutorial-incident-runbook.md) |

在 [tutorial.md](tutorial.md) 内可用编辑器搜索小节标题（例如「403」「CSRF」「Execution Kernel」）定位。

---

## 专题与评审材料

| 文档 | 用途 |
|------|------|
| [tutorial-index.md](tutorial-index.md) | 总索引、按角色命令、Windows/PowerShell 对照 |
| [tutorial-beginner-playbook.md](tutorial-beginner-playbook.md) | 新人实操路径（上手与使用） |
| [tutorial-debug-playbook.md](tutorial-debug-playbook.md) | 调试路径（定位与回滚） |
| [security-review-hints.md](security-review-hints.md) | 部署与架构评审提示（中文） |
| [security-review-hints-en.md](security-review-hints-en.md) | 同上（英文摘要） |

---

## 文档维护约定

当 **安全、租户、鉴权** 等行为变更时，优先同步：

- [tutorial.md](tutorial.md)
- [tutorial-security-baseline.md](tutorial-security-baseline.md)
- [tutorial-ops-checklist.md](tutorial-ops-checklist.md)

重大故障复盘后更新 [tutorial-incident-runbook.md](tutorial-incident-runbook.md)。细则见 [tutorial-index.md](tutorial-index.md) 文末维护约定。
