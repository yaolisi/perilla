# Agent Runtime – AGENTS.md

# 1. 模块定位（非常重要）

agent_runtime 是本地 AI 推理平台的 **Agent 执行引擎**。

> Agent Runtime = 有状态、有循环或计划、有决策能力的 LLM 执行系统

职责包括：
* Agent 的**定义**与**运行**（含持久化与注册）
* **两种执行模式**：Legacy 多步 Loop（v1.5）与 Plan-Based（V2）
* Tool / Skill 调用决策、RAG 注入
* Trace / 可观测性

⚠️ 本模块不是模型推理层，也不是协议适配层；不直接调用 runtimes。

# 2. 与其他模块的关系

## 2.1 层级关系

```
agent_runtime
   ├── legacy: loop.py + executor.py → agents (unified_agent / router) → runtimes
   └── V2:     v2/runtime.py → v2/planner.py, v2/executor_v2 → agents → runtimes
```

## 2.2 边界

| 模块            | 职责                           |
|----------------|--------------------------------|
| agent_runtime  | Agent 行为、状态、Loop/Plan、Trace |
| core/agents    | 单次 ChatCompletion / 模型路由     |
| core/runtimes  | 模型加载与推理                    |
| core/plugins   | Tool / Skill 能力                |
| core/skills    | Skill 定义、注册、执行            |

👉 Agent Runtime 通过 agents 间接调用 runtimes，不直接调 runtimes。

# 3. 核心设计原则

## 3.1 强约束、可解释

* Agent 必须有 step 或 plan 步数上限，每一步可追溯
* 禁止隐式 Tool/Skill 调用；禁止黑盒行为

## 3.2 Agent ≠ Chat

* Agent：有目标、有循环或计划、会调用工具/技能、会失败/重规划
* Chat：输入 → 输出

## 3.3 Tool / Skill / RAG 是能力，不是流程

* Agent（或 Planner）决定是否、何时使用 Tool / Skill / RAG
* 能力层不反向控制 Agent Loop 或 Plan 流程

# 4. 模块结构说明

```
agent_runtime/
├── definition.py       # AgentDefinition（静态定义与注册）
├── session.py          # AgentSession（运行态）
├── context.py          # 执行上下文
├── project_context.py  # 工程上下文（scan/test/build 等共享状态）
├── executor.py         # AgentExecutor（入口，按 execution_mode 分发）
├── loop.py             # AgentLoop（Legacy 多步循环，v1.5）
├── parser.py           # LLM 输出解析（Action: skill_call / tool_call / final）
├── trace.py            # Agent Trace 记录
├── rag.py              # RAG 注入
│
├── v2/                 # Plan-Based 执行（V2）
│   ├── runtime.py      # AgentRuntime：V2 入口，调用 Planner + PlanBasedExecutor
│   ├── models.py       # Plan, Step, StepType, ExecutorType 等
│   ├── planner.py      # Planner：create_plan / create_followup_plan（含 RePlan 分支）
│   ├── executor_v2.py  # PlanBasedExecutor：按序执行 Step，支持 REPLAN
│   ├── executors.py    # LLMExecutor, SkillExecutor 等
│   ├── plan_contract_adapter.py  # Plan Contract → 运行时 Plan 转换
│   └── observability.py # 结构化日志与性能指标
│
└── AGENTS.md
```

与 Plan Contract 协议层（独立模块）的关系：
* `core/plan_contract`：契约模型与校验（无执行逻辑）
* `v2/plan_contract_adapter`：契约解析并转换为 v2 Plan，仅在 RePlan 时由 Planner 使用

# 5. AgentDefinition（静态 Agent）

## 5.1 职责

* 描述 Agent 是什么（名称、描述、模型、提示、能力、执行策略）
* 可持久化、可复制、可模板化

## 5.2 典型字段（当前）

```python
# 标识与展示
agent_id: str
name: str
description: str
slug: Optional[str]

# 推理
model_id: str
system_prompt: str
temperature: float
model_params: Dict[str, Any]   # 如 intent_rules, skill_param_extractors 等

# 能力：Agent 可见的是 Skill（v1.5 起）
enabled_skills: List[str]     # 如 builtin_file.read, builtin_shell.run
tool_ids: List[str]           # 兼容旧配置
rag_ids: List[str]

# 执行控制
max_steps: int
execution_mode: Optional[str]  # "legacy" | "plan_based"

# V2.2 RePlan
max_replan_count: int
on_failure_strategy: str      # "stop" | "continue" | "replan"
replan_prompt: str

# V2.3 Plan Contract（RePlan 时可选）
plan_contract_enabled: bool
plan_contract_strict: bool
plan_contract_sources: List[str]

# V3：Kernel 并行与并发上限（plan_based）
use_execution_kernel: Optional[bool]   # None = 跟随全局 USE_EXECUTION_KERNEL
execution_strategy: Optional[str]      # "serial" | "parallel_kernel" | None（推导）
max_parallel_nodes: Optional[int]       # parallel_kernel 时 Scheduler 并发槽
```

⚠️ AgentDefinition 不包含运行时状态。

# 6. AgentSession（一次运行）

* 每次 Run Agent 对应一个 Session（或复用已有 session_id）
* 含 messages、step、status、workspace_dir、state（如 fix_attempt_count、replan_count）等
* 可追踪、可恢复；Trace 与 Session 关联

# 7. 执行模式

## 7.1 Legacy（v1.5）

* `execution_mode == "legacy"` 或未设置时使用
* **AgentLoop**：构造 Prompt → 调用 LLM → 解析输出（skill_call / tool_call / final）→ 执行 Skill 或结束 → 记录 Trace，循环直到 final 或达到 max_steps
* 能力来源：SkillRegistry（enabled_skills）；Parser 解析 LLM 输出为 AgentAction

## 7.2 Plan-Based（V2）

* `execution_mode == "plan_based"` 时使用
* **Planner** 根据用户输入与上下文生成 **Plan**（steps 序列）
* **PlanBasedExecutor** 按序执行 Step（LLM / Skill / Composite / REPLAN），支持步骤失败后的 **RePlan**
* RePlan 时 `create_followup_plan` 的优先级（在启用且存在时）：
  1. **Plan Contract**（从 execution_context 的配置源取契约并校验、转换）
  2. **replan_direct_skill**（可配置的直接技能计划）
  3. **replan_fix_plan**（测试/命令失败时的固定「读→LLM patch→apply_patch→再测」链）
  4. **create_plan**（LLM 重新规划）
* 权限由 Skill/Tool 声明推导（如 `core.tools.permissions`），不在此模块写死

## 7.3 V3：并行 Kernel、事件流与记忆（plan_based）

* **执行策略**（`AgentDefinition.execution_strategy`，亦可放在 `model_params`）  
  - `parallel_kernel`：`AgentGraphAdapter` 将 Plan 编译为 `GraphDefinition`，由 **Execution Kernel** `Scheduler` 事件驱动调度；`max_parallel_nodes` 映射为 Scheduler 并发上限。  
  - `serial`：始终走 **PlanBasedExecutor** 顺序执行（排障/回退路径）。  
  - 未显式配置时：由 `use_execution_kernel`（Agent 级）与全局 `USE_EXECUTION_KERNEL` 推导默认策略（见 `v2/runtime.py` 中 `_resolve_execution_strategy`）。  
  - 解析顺序：**顶字段优先**，仅当顶字段为空时才读 `model_params`；REST 创建/更新若两处同时给出且不一致会 **400**（`backend/api/agents.py`）。
* **失败回退**：Kernel 执行抛错时，`AgentRuntime` 捕获后自动降级为 `PlanBasedExecutor`（见 `_run_plan_based`），不中断单次 Run 的用户可见流程（错误仍记录日志与指标）。
* **事件流**：Kernel 将节点/图生命周期写入 `execution_event`（`EventStore`）；HTTP 查询 `/api/events/instance/{instance_id}`；按会话聚合 `/api/events/agent-session/{session_id}`（依赖 `GRAPH_STARTED` payload 内 `initial_context.session_id`）。
* **记忆**：Planner 前 **MemoryInjector** 注入历史消息；Run 成功后 **MemoryExtractor** 异步提取持久化（受 `config.settings` 中 memory_* 开关约束；初始化失败则跳过）。

## 7.4 Plan 执行韧性（好用路径：`model_params.plan_execution`）

* **配置位置（推荐）**：`AgentDefinition.model_params.plan_execution`（JSON 对象），由 `v2/runtime.py` 的 `_apply_agent_plan_execution_defaults` 在 `create_plan` 之后合并进 **Plan 上仍为默认空** 的字段；与「系统设置 → 运行时」中的全局项（`agentPlanMaxParallelSteps` 等）叠加时，**步骤级 > Plan 级 > 系统 store > `config.settings`**。  
* **可填键（与前端 `@/utils/planExecutionConfig` 对齐）**：`max_parallel_in_group`（1–64）、`default_timeout_seconds`、`default_max_retries`、`default_retry_interval_seconds`、`default_on_timeout_strategy`（`stop` / `continue` / `replan`）。  
* **Step 上可覆盖**：`parallel_group` / `_parallel_group`（同组并发）、`timeout_seconds`、`max_retries`、`retry_interval_seconds`、`on_timeout_strategy` 等（见 `v2/models.py`）。  
* **不必**在 API 顶字段再复制一套；对外若需强契约，可后续再抽顶字段，与 `plan_execution` 二选一或合并策略由 `api/agents` 统一。

# 8. LLM 输出协议

## 8.1 Legacy（v1.5）

* Parser 解析为：`skill_call`（skill_id + input）或 `tool_call` 或 `final`
* 解析失败按策略终止或记录错误

## 8.2 V2

* Planner 产出结构化 Plan（Step 列表），Step 类型为 LLM / Skill / Composite / REPLAN
* REPLAN 步骤会再次调用 Planner.create_followup_plan 生成后续 Plan 并递归执行

# 9. Tool / Skill 在 Agent Runtime 中的角色

* **Skill** 是 Agent 可见的能力抽象（prompt / tool / composite）；由 SkillRegistry 提供，对应 enabled_skills
* **Tool** 是具体实现，通过 Plugin 注册；Skill 的 type=tool 时由 SkillExecutor 调用 ToolRegistry
* Agent Runtime 只通过统一 Skill/Tool 接口调用，不写死具体能力列表

# 10. RAG 的使用原则

* RAG 通过上下文注入或 Skill 使用；Agent/Planner 决定是否启用
* Trace 必须记录检索相关行为

# 11. Trace 与可观测性

* 每一步 Prompt、LLM 输出、Skill/Tool 调用、耗时与错误均需可记录
* V2 支持结构化日志与运行指标（如 plan 创建耗时、replan 次数、步骤耗时）
* Trace 用于 Debug、审计及后续 Skill/Learning 扩展
* **多 Agent 协作（Phase 0）**：`core/agent_runtime/collaboration.py` 将 `correlation_id` / `orchestrator_agent_id` / `invoked_from` 写入 `AgentSession.state["collaboration"]`；HTTP `POST /api/agents/{id}/run` 可传同名字段；Workflow 在调度启动时把归一化后的 `correlation_id` 写回 `WorkflowExecution.global_context`；首次执行 **Agent 节点** 时把解析出的 `orchestrator_agent_id` 写回同字段。运行中 `global_context` 默认含 `wfex_{execution_id}` 等。Execution Kernel 的 `persisted_context` 会透传以上键，使 `GRAPH_STARTED` 的 `initial_context` 可关联协作链。查询：`GET /api/collaboration/correlation/{correlation_id}`。

# 12. 明确禁止事项

🚫 不要在 Agent Runtime 中：
* 直接调用 runtimes
* 写模型加载逻辑
* 写 UI 逻辑
* 写数据库 ORM（通过现有 data 层或服务）

🚫 不要：
* 在 Loop/Planner 中写死 Tool/Skill 列表（用 definition + 注册表）
* 隐式调用 Tool/Skill
* 跳过 Trace

# 13. 与根目录 AGENTS.md 的关系

* 根目录 **AGENTS.md** 为项目级 Agent/Plugin 规范（User-in-Control、Gateway-Centric、Determinism、Plugin-first 等）
* 本文件为 **agent_runtime 模块** 的定位、结构与约束，需与根目录规范一致，且不重复表述全局原则

# 14. 一句话总结

> Agent Runtime 是「可解释、可演进」的 Agent 执行引擎：支持 Legacy 多步 Loop 与 V2 Plan-Based 两种模式，集成 RePlan、Plan Contract 与可观测性，而不是聊天封装或模型代理。
