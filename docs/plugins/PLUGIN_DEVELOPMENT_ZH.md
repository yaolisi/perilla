# 插件（Plugin）开发指南

面向需要在推理网关中扩展 **预处理 / 后处理 / 工具型能力** 的开发者。插件遵循 `AGENTS.md` 中的插件生命周期与权限声明约定。

## 1. 插件在系统中的位置

- 网关接收 Chat / Agent 请求后，按 `stage`（如 `pre`）加载 capability 插件。
- 插件在 **`UnifiedModelAgent` / 推理链路之前或之后** 修改结构化输入输出（例如注入 RAG 上下文）。
- 前端 **不直连模型**；插件逻辑运行在 FastAPI 后端，与用户请求同属一条审计边界。

## 2. 最小插件清单

每个插件需要同时具备：

| 要素 | 说明 |
|------|------|
| `plugin.json` | 声明名称、版本、`entry`、类型、`stage`、JSON Schema |
| Python 类 | 继承 `Plugin`，实现 `execute()` |
| 注册 | 放入 `core/plugins/builtin/<name>/` 或由注册表加载的路径 |

### 2.1 `plugin.json` 字段（与内置 RAG 对齐）

参考：`backend/core/plugins/builtin/rag/plugin.json`

- **name / version / description**：面向运维与市场的可读元数据。
- **entry**：`模块路径:类名`，例如 `core.plugins.builtin.rag.plugin:RAGPlugin`。
- **type**：`system` \| `model` \| `capability`（能力扩展一般用 `capability`）。
- **stage**：`pre` \| `post` \| `tool` \| `router`，决定在流水线哪一段执行。
- **supported_modes**：如 `["chat", "agent"]`，与网关路由一致。
- **permissions**：若需要访问网络、文件系统等，在此声明（空数组表示仅使用网关已有能力）。
- **input_schema / output_schema**：JSON Schema，用于校验与文档生成；应与代码中读取字段一致。

### 2.2 Python 类骨架

参考：`backend/core/plugins/builtin/rag/plugin.py`

```python
from typing import Any, Dict

from core.plugins.base import Plugin
from core.plugins.context import PluginContext


class EchoPrefixPlugin(Plugin):
    name = "echo_prefix"
    version = "0.1.0"
    description = "在首条 user 消息前添加固定前缀（示例）"
    type = "capability"
    stage = "pre"

    supported_modes = ["chat", "agent"]
    permissions = []

    input_schema = {
        "type": "object",
        "properties": {
            "messages": {"type": "array"},
            "prefix": {"type": "string", "default": "[demo] "},
        },
        "required": ["messages"],
    }
    output_schema = {
        "type": "object",
        "properties": {"messages": {"type": "array"}},
        "required": ["messages"],
    }

    async def execute(self, input: Dict[str, Any], context: PluginContext) -> Dict[str, Any]:
        prefix = str(input.get("prefix") or "")
        messages = list(input.get("messages") or [])
        for i, m in enumerate(messages):
            if isinstance(m, dict) and m.get("role") == "user":
                c = m.get("content")
                if isinstance(c, str):
                    messages[i] = {**m, "content": prefix + c}
                break
        return {"messages": messages}
```

要点：

- **`execute` 必须是异步**，返回值字典须符合 `output_schema`。
- **不要**在插件内直接调用外部 HTTP 模型端点绕过网关；若需 LLM，应通过既有推理客户端 / Agent 能力（与项目安全策略一致）。
- 需要持久化或向量检索时，使用项目提供的 ORM 与 `VectorSearchProvider` 抽象，避免裸连数据库（见 `AGENTS.md` 数据层约定）。

## 3. 调试建议

- 单测可 mock `PluginContext`，对 `execute()` 做输入输出快照比对。
- 联调时在网关日志中确认插件阶段耗时与错误栈；复杂流水线建议配合已有 Workflow 文档排查节点顺序。

## 4. 相关阅读

- 插件基类：`backend/core/plugins/base.py`
- 工作流节点（编排侧）：`docs/workflow/WORKFLOW_NODE_CONFIG_GUIDE.md`
- 架构总览：`docs/architecture/ARCHITECTURE.md`
