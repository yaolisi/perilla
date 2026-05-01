# 工作流编排概览（进阶）

本文帮助新用户从「单轮 Chat」过渡到 **多节点工作流**，并指向仓库内已有实操文档。

## 1. 核心概念

| 概念 | 含义 |
|------|------|
| **Workflow** | 有向图：节点表示步骤（LLM、工具、分支、循环等），边表示数据与控制权传递。 |
| **Control Plane** | 负责定义、版本、发布与执行策略；与执行内核（队列、租约、事件）解耦。 |
| **节点类型** | 如 `start`、`input`、`llm`、`agent`、`tool`、`condition`、`loop`、`output` 等。 |

推理仍统一经 **FastAPI 网关**；工作流负责编排何时调用 LLM、何时调用工具或子 Agent。

## 2. 建议阅读顺序

1. **节点怎么配**：`docs/workflow/WORKFLOW_NODE_CONFIG_GUIDE.md`（模板与常用 JSON 片段）。
2. **节点设计与约束**：`docs/workflow/WORKFLOW_NODE_DESIGN.md`。
3. **控制面能力差距 / 验收**（维护演进用）：`docs/workflow/WORKFLOW_CONTROL_PLANE_V3_GAP_ANALYSIS.md`、`WORKFLOW_CONTROL_PLANE_V3_ACCEPTANCE_CHECKLIST.md`。
4. **本地联调用例**：`docs/workflow/WORKFLOW_TEST_CASES_LOCAL.md`。

## 3. 实操原则（摘录）

- 先打通最小链路（`start` → `input` → `llm` → `output`），再增加条件与循环。
- 输入输出字段命名保持一致（如统一 `query` / `topic`），减少映射错误。
- 生产环境优先执行 **已发布** 版本的工作流定义。

## 4. 与插件、Agent 的关系

- **插件**：偏「单次请求上的横切能力」（如 RAG 注入），由插件系统在 Chat/Agent 模式下调度。
- **Workflow 节点**：偏「多步编排与分支」；其中 `llm` / `agent` 节点仍通过网关访问模型与工具。

二者可同时使用：例如在网关入口启用 RAG 插件，在工作流中编排多步推理与工具调用。
