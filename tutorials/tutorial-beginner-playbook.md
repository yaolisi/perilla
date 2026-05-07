# perilla 新手上手与使用手册（实操版）

适用对象：第一次接触本项目的研发、测试、实施同学。  
目标：在 30~60 分钟内完成 **环境启动 -> 核心功能体验 -> 基础回归验证**。

---

## 1. 学习路径（推荐顺序）

1. 10 分钟启动：`tutorial-quickstart.md`
2. 本文（实操版）：按步骤体验 Chat / Models / Images / Agents / Workflow
3. 完整参数与高级能力：`tutorial.md`（**Skill / MCP** 新手详解见主教程 **§8.4、§8.5**，极简摘要见 `tutorial-quickstart.md` **「Skill 与 MCP（可选）」**）
4. 发版前核对：`tutorial-ops-checklist.md`
5. 故障处置：`tutorial-debug-playbook.md` + `tutorial-incident-runbook.md`

---

## 2. 启动后先确认什么

在项目根目录执行：

```bash
curl -s http://127.0.0.1:8000/api/health | jq .
curl -s http://127.0.0.1:8000/api/health/ready | jq .
```

预期：状态正常、HTTP 200。  
若失败，先看 `scripts/status.sh` 与 `scripts/logs.sh` 输出。

若**仅**打开前端却出现 **Failed to fetch**，或开发者工具里 **401**（如 **`/api/system/config`**、知识库列表）：先确认**网关与 Vite 均已启动**（**[tutorial.md](tutorial.md) §6.3**），再查 **[tutorial-debug-playbook.md](tutorial-debug-playbook.md) §2.0** 与主教程 **§17.9、§17.10**；本地默认 **`DEBUG=true`** 时，通常**不必**先在 **Settings → Backend** 填 **Admin API Key** 才能加载侧栏，除非环境接近生产或配置了 **`RBAC_ADMIN_API_KEYS` / API Key scope**。

---

## 3. 5 个核心页面体验路径

按以下顺序体验，能最快形成全局认知：

1. `/models`：确认模型可见与状态正常
2. `/chat`：发起基础对话，请求是否稳定返回
3. `/images`：触发一次文生图任务并查看历史
4. `/agents`：创建/编辑一个工具型 Agent 并运行
5. `/workflow`：执行一个最小流程，观察节点状态变化  

可选扩展（与 Skill/MCP 相关）：在 **`/settings/mcp`** 按 **[tutorial.md §8.5](tutorial.md)** 导入工具为技能后，到 **`/skills`** 与 Agent / 工作流 **Skill** 节点验证（步骤细节见 **§8.4**）。

建议每一步都记录“预期结果/实际结果/耗时”。

---

## 4. 常见使用动作（新人最常做）

## 4.1 修改系统配置并验证刷新

1. 进入 `/settings` 修改一项配置并保存  
2. 回到 Agent/Sidebar/Model 等页面观察版本或配置展示是否更新  
3. 若未更新，先看 `tutorial-debug-playbook.md` 中“配置更新不生效”章节

## 4.2 新增 MCP Server 并验证可用

**详细图文与权限说明（管理员 Key、Probe、导入为 Skill、工作流节点命名为 Skill 等）见主教程 [tutorial.md §8.5 MCP](tutorial.md) 与 [§8.4 Skill](tutorial.md)；极简清单见 [tutorial-quickstart.md](tutorial-quickstart.md)「Skill 与 MCP（可选）」。索引汇总：[tutorial-index.md §1.1](tutorial-index.md)。**

1. 确认 **Settings → Backend** 中 **`X-Api-Key` 为管理员**，否则 `/api/mcp/*` 会 **401/403**（见 `tutorial.md` §8.2 / §8.5）。  
2. 进入 **`/settings/mcp`**：**Probe**（stdio 或 http）→ **添加 MCP Server** → 在列表中展开该 Server → **列出 Tools / 导入为技能**（按钮文案以界面为准）。  
3. 打开 **`/skills`**，确认出现导入项；在 **Agent** 勾选该技能，或在 **Workflow** 画布拖入 **Tool → Skill** 节点并在右侧选择对应工具。  
4. 若仍不可见或调用失败，先看 §8.5 自检清单；可选执行后端 MCP 相关测试：

```bash
PYTHONPATH=backend pytest -q \
  backend/tests/test_mcp_protocol.py \
  backend/tests/test_mcp_http_client_lifecycle.py
```

---

## 5. 新手必跑检查

**提交前快检**

```bash
make pr-check-fast
```

**发布前全检**

```bash
make pr-check
```

**安全回归（推荐）**

```bash
backend/scripts/test_tenant_security_regression.sh
scripts/acceptance/run_security_regression.sh
```

---

## 6. 结果判定标准（给新人一个“完成定义”）

满足以下条件可认为“上手完成”：

- 能独立启动前后端并通过健康检查
- 能完成 5 个核心页面的基础体验
- 能描述 MCP 配置入口（`/settings/mcp`）、导入为 Skill 的路径，以及在工作流 **Skill** 节点 / Agent 中的用法（对照 **tutorial.md §8.4～§8.5**）
- 能执行 `pr-check-fast` 并理解失败时去哪里看日志

---

## 7. 下一步建议

- 进入 **`tutorial.md`** 学习租户、RBAC、Workflow 编排和高级调试；其中 **Skill / MCP** 完整新手步骤为 **§8.4、§8.5**（与本文 §4.2 对应）。  
- 需要极简备忘时打开 **`tutorial-quickstart.md`** 的 **「Skill 与 MCP（可选）」**；章节约束见 **`tutorial-index.md` §1.1**。  
- 发布值班前，阅读 **`tutorial-ops-checklist.md`** 和 **`tutorial-incident-runbook.md`**。
