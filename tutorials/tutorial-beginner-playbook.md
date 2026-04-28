# perilla 新手上手与使用手册（实操版）

适用对象：第一次接触本项目的研发、测试、实施同学。  
目标：在 30~60 分钟内完成 **环境启动 -> 核心功能体验 -> 基础回归验证**。

---

## 1. 学习路径（推荐顺序）

1. 10 分钟启动：`tutorial-quickstart.md`
2. 本文（实操版）：按步骤体验 Chat / Models / Images / Agents / Workflow
3. 完整参数与高级能力：`tutorial.md`
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

---

## 3. 5 个核心页面体验路径

按以下顺序体验，能最快形成全局认知：

1. `/models`：确认模型可见与状态正常
2. `/chat`：发起基础对话，请求是否稳定返回
3. `/images`：触发一次文生图任务并查看历史
4. `/agents`：创建/编辑一个工具型 Agent 并运行
5. `/workflow`：执行一个最小流程，观察节点状态变化

建议每一步都记录“预期结果/实际结果/耗时”。

---

## 4. 常见使用动作（新人最常做）

## 4.1 修改系统配置并验证刷新

1. 进入 `/settings` 修改一项配置并保存  
2. 回到 Agent/Sidebar/Model 等页面观察版本或配置展示是否更新  
3. 若未更新，先看 `tutorial-debug-playbook.md` 中“配置更新不生效”章节

## 4.2 新增 MCP Server 并验证可用

1. 进入 `/settings/mcp` 新建或编辑配置  
2. 保存后到 Agent 相关页面验证技能/工具是否可见  
3. 如不可见，执行：

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
- 能描述 MCP 配置入口与验证路径
- 能执行 `pr-check-fast` 并理解失败时去哪里看日志

---

## 7. 下一步建议

- 进入 `tutorial.md` 学习租户、RBAC、Workflow 编排和高级调试。
- 发布值班前，阅读 `tutorial-ops-checklist.md` 和 `tutorial-incident-runbook.md`。
