"""
Workflow Runtime

Workflow 运行时，协调执行流程，集成 governance 和 execution_kernel。
"""

from typing import Optional, Dict, Any, Callable, List, Awaitable, cast, Tuple
from datetime import UTC, datetime, timedelta
import asyncio
import json
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from core.workflows.models import (
    WorkflowExecution,
    WorkflowExecutionState,
    WorkflowExecutionNode,
    WorkflowExecutionNodeState,
    WorkflowVersion,
    WorkflowVersionState,
    WorkflowExecutionCreateRequest,
)
from core.workflows.repository import WorkflowExecutionRepository, WorkflowVersionRepository
from core.workflows.repository import WorkflowApprovalTaskRepository
from core.workflows.governance import ExecutionManager, ExecutionRequest
from core.workflows.runtime.graph_runtime_adapter import GraphRuntimeAdapter
from core.workflows.recommendation import WorkflowToolCompositionRecommender
from core.workflows.runtime.subworkflow import build_child_input, apply_output_mapping
from core.system.settings_store import get_system_settings_store
from core.inference.client.inference_client import InferenceClient
from core.tools.registry import ToolRegistry
from core.tools.context import ToolContext
from core.agent_runtime.definition import get_agent_registry
from core.agent_runtime.executor import get_agent_executor
from core.agent_runtime.session import AgentSession
from core.agent_runtime.collaboration import (
    append_collaboration_message_to_state,
    build_collaboration_message,
    build_workflow_collaboration,
    merge_collaboration_into_state,
)
from core.agent_runtime.v2.runtime import get_agent_runtime
from core.types import Message
from execution_kernel.engine.control_flow import execute_condition_node
from execution_kernel.engine.scheduler import Scheduler
from execution_kernel.engine.state_machine import StateMachine
from execution_kernel.engine.executor import Executor
from execution_kernel.engine.context import GraphContext
from execution_kernel.persistence.db import Database, get_platform_db_path
from execution_kernel.cache.node_cache import NodeCache
from execution_kernel.persistence.repositories import NodeCacheRepository
from execution_kernel.models.graph_definition import NodeDefinition
from execution_kernel.models.node_models import NodeCacheEntry
from execution_kernel.models.graph_instance import NodeCacheDB
from config.settings import settings
from log import logger


class _WorkflowNodeCacheRepository:
    """
    为 WorkflowRuntime 提供 NodeCache 所需的最小仓储适配层。
    NodeCache 当前依赖 async Session 级 repository，这里按调用粒度创建 session。
    """

    def __init__(self, db: Database):
        self._db = db

    async def get(self, node_id: str, input_hash: str) -> Optional[NodeCacheDB]:
        async with self._db.async_session() as session:
            repo = NodeCacheRepository(session)
            return await repo.get(node_id, input_hash)

    async def save(self, entry: NodeCacheEntry) -> NodeCacheDB:
        async with self._db.async_session() as session:
            repo = NodeCacheRepository(session)
            return await repo.save(entry)

    async def delete_expired(self) -> int:
        async with self._db.async_session() as session:
            repo = NodeCacheRepository(session)
            return cast(int, await repo.delete_expired())


class WorkflowRuntime:
    """
    Workflow 运行时
    
    负责 Workflow 的执行协调：
    1. 执行治理检查（并发、配额）
    2. 转换为 execution_kernel 格式
    3. 调用 execution_kernel 执行
    4. 状态同步和结果处理
    """
    AGENT_NODE_MAX_CALL_DEPTH = 2
    AGENT_NODE_DEFAULT_MAX_CALLS = 20
    
    def __init__(
        self,
        db: Session,
        execution_manager: ExecutionManager,
        scheduler: Optional[Scheduler] = None
    ):
        self.db = db
        self.execution_repository = WorkflowExecutionRepository(db)
        self.version_repository = WorkflowVersionRepository(db)
        self.approval_repository = WorkflowApprovalTaskRepository(db)
        self.execution_manager = execution_manager
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._inference_client = InferenceClient()
        
        # 初始化 execution_kernel 组件
        if scheduler:
            self.scheduler = scheduler
        else:
            # 创建默认 scheduler，使用平台统一的 DB 路径
            db_instance = Database()
            state_machine = StateMachine(db=db_instance)
            cache_repo = _WorkflowNodeCacheRepository(db_instance)
            cache = NodeCache(cast(NodeCacheRepository, cache_repo))
            # Workflow 使用基础 node handlers（llm, tool, condition 等）
            node_handlers = self._create_default_node_handlers()
            executor = Executor(state_machine, cache, node_handlers)
            self.scheduler = Scheduler(db_instance, state_machine, executor)
    
    @staticmethod
    def _validate_simple_output_schema(
        output: Dict[str, Any],
        schema: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """轻量 schema 校验（required + properties.type + 嵌套 object/array）。返回结构化错误。"""
        if not isinstance(schema, dict) or not schema:
            return None

        root_rule = dict(schema)
        if "type" not in root_rule:
            root_rule["type"] = "object"
        return WorkflowRuntime._validate_schema_node(output, root_rule, "schema", "output")

    @staticmethod
    def _schema_type_map() -> Dict[str, type[Any] | tuple[type[Any], ...]]:
        return {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "object": dict,
            "array": list,
        }

    @staticmethod
    def _schema_validation_error(
        *,
        message: str,
        schema_path: str,
        output_path: str,
        expected_type: Optional[str] = None,
        actual_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "error_code": "AGENT_OUTPUT_SCHEMA_VALIDATION_ERROR",
            "message": message,
            "schema_path": schema_path,
            "output_path": output_path,
            "expected_type": expected_type,
            "actual_type": actual_type,
        }

    @staticmethod
    def _validate_schema_node(
        value: Any, rule: Dict[str, Any], schema_path: str, output_path: str
    ) -> Optional[Dict[str, Any]]:
        expected = str((rule or {}).get("type") or "").strip()
        type_err = WorkflowRuntime._validate_schema_type_match(
            value=value,
            expected=expected,
            schema_path=schema_path,
            output_path=output_path,
        )
        if type_err:
            return type_err

        object_err = WorkflowRuntime._validate_object_schema_node(
            value=value,
            rule=rule,
            expected=expected,
            schema_path=schema_path,
            output_path=output_path,
        )
        if object_err:
            return object_err
        return WorkflowRuntime._validate_array_schema_node(
            value=value,
            rule=rule,
            expected=expected,
            schema_path=schema_path,
            output_path=output_path,
        )

    @staticmethod
    def _validate_schema_type_match(
        *,
        value: Any,
        expected: str,
        schema_path: str,
        output_path: str,
    ) -> Optional[Dict[str, Any]]:
        if not expected:
            return None
        py_type = WorkflowRuntime._schema_type_map().get(expected)
        actual_type = type(value).__name__
        if not py_type or isinstance(value, py_type):
            return None
        return WorkflowRuntime._schema_validation_error(
            message=f"type mismatch: expected {expected}, got {actual_type}",
            schema_path=schema_path,
            output_path=output_path,
            expected_type=expected,
            actual_type=actual_type,
        )

    @staticmethod
    def _validate_object_schema_node(
        *,
        value: Any,
        rule: Dict[str, Any],
        expected: str,
        schema_path: str,
        output_path: str,
    ) -> Optional[Dict[str, Any]]:
        if expected != "object":
            return None
        required_err = WorkflowRuntime._validate_required_object_keys(
            value=value,
            required=(rule or {}).get("required") or [],
            schema_path=schema_path,
            output_path=output_path,
        )
        if required_err:
            return required_err
        return WorkflowRuntime._validate_object_properties(
            value=value,
            properties=(rule or {}).get("properties") or {},
            schema_path=schema_path,
            output_path=output_path,
        )

    @staticmethod
    def _validate_required_object_keys(
        *,
        value: Any,
        required: List[Any],
        schema_path: str,
        output_path: str,
    ) -> Optional[Dict[str, Any]]:
        for key in required:
            if not isinstance(value, dict) or key not in value:
                return WorkflowRuntime._schema_validation_error(
                    message=f"missing required field: {key}",
                    schema_path=f"{schema_path}.required[{key}]",
                    output_path=f"{output_path}.{key}",
                    expected_type=None,
                    actual_type="missing",
                )
        return None

    @staticmethod
    def _validate_object_properties(
        *,
        value: Any,
        properties: Dict[str, Any],
        schema_path: str,
        output_path: str,
    ) -> Optional[Dict[str, Any]]:
        for key, child_rule in properties.items():
            if not isinstance(value, dict) or key not in value:
                continue
            child_schema_path = f"{schema_path}.properties.{key}"
            child_output_path = f"{output_path}.{key}"
            err = WorkflowRuntime._validate_schema_node(
                value.get(key), child_rule or {}, child_schema_path, child_output_path
            )
            if err:
                return err
        return None

    @staticmethod
    def _validate_array_schema_node(
        *,
        value: Any,
        rule: Dict[str, Any],
        expected: str,
        schema_path: str,
        output_path: str,
    ) -> Optional[Dict[str, Any]]:
        if expected != "array":
            return None
        items_rule = (rule or {}).get("items")
        if not items_rule or not isinstance(value, list):
            return None
        for idx, item in enumerate(value):
            err = WorkflowRuntime._validate_schema_node(
                item,
                items_rule,
                f"{schema_path}.items",
                f"{output_path}[{idx}]",
            )
            if err:
                return err
        return None

    def _create_default_node_handlers(self) -> Dict[str, Callable]:
        """创建默认的节点处理器"""
        return cast(Dict[str, Callable[[NodeDefinition, Dict[str, Any], GraphContext], Awaitable[Dict[str, Any]]]], {
            "tool": self._tool_handler,
            "llm": self._llm_handler,
            "condition": self._condition_handler,
            "loop": self._loop_handler,
            "script": self._script_handler,
        })

    @staticmethod
    def _collect_failed_nodes(node_states: List[WorkflowExecutionNode]) -> List[Dict[str, Any]]:
        failed: List[Dict[str, Any]] = []
        for n in node_states or []:
            s = n.state.value if hasattr(n.state, "value") else str(n.state)
            if s not in {"failed", "timeout"}:
                continue
            failed.append(
                {
                    "node_id": n.node_id,
                    "state": s,
                    "error_message": n.error_message,
                    "error_details": n.error_details if isinstance(n.error_details, dict) else None,
                    "retry_count": int(n.retry_count or 0),
                }
            )
        return failed

    def _build_global_failure_details(
        self,
        execution: WorkflowExecution,
        *,
        error_message: str,
        exception_type: str,
    ) -> Dict[str, Any]:
        global_error_cfg = (
            execution.global_context.get("error_handling")
            if isinstance(execution.global_context, dict)
            else {}
        )
        if not isinstance(global_error_cfg, dict):
            global_error_cfg = {}
        on_failure_cfg = global_error_cfg.get("on_failure")
        if not isinstance(on_failure_cfg, dict):
            on_failure_cfg = {}

        failed_nodes = self._collect_failed_nodes(execution.node_states or [])
        details: Dict[str, Any] = {
            "exception_type": exception_type,
            "message": error_message,
            "failed_nodes": failed_nodes,
        }
        if on_failure_cfg.get("alert"):
            logger.error(
                "[WorkflowRuntime] GLOBAL_FAILURE_ALERT execution_id=%s workflow_id=%s failed_nodes=%s message=%s",
                execution.execution_id,
                execution.workflow_id,
                len(failed_nodes),
                error_message,
            )
            details["alert_triggered"] = True
        if on_failure_cfg.get("rollback"):
            details["rollback_requested"] = True
            details["rollback_note"] = "rollback request captured; executor should handle rollback action."
        return details

    def _ensure_execution_not_cancelled(self, context: GraphContext) -> None:
        global_ctx = getattr(context, "global_data", {}) or {}
        execution_id = str(global_ctx.get("execution_id") or "").strip()
        if not execution_id:
            return
        execution = self.execution_repository.get_by_id(execution_id)
        if execution and execution.state == WorkflowExecutionState.CANCELLED:
            raise RuntimeError(f"WORKFLOW_CANCELLED: execution_id={execution_id}")

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _infer_prompt_from_payload(payload: Any) -> Optional[str]:
        if payload is None:
            return None
        if isinstance(payload, str):
            s = payload.strip()
            return s or None
        if isinstance(payload, (int, float, bool)):
            return str(payload)
        if isinstance(payload, dict):
            return WorkflowRuntime._infer_prompt_from_dict_payload(payload)
        return None

    @staticmethod
    def _infer_prompt_from_dict_payload(payload: Dict[str, Any]) -> Optional[str]:
        preferred_keys = [
            "prompt", "message", "query", "text",
            "question", "task", "instruction", "content",
            "topic", "input",
        ]
        for k in preferred_keys:
            v = payload.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for v in payload.values():
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    async def _tool_handler(
        self, node_def: NodeDefinition, input_data: Dict[str, Any], context: GraphContext
    ) -> Dict[str, Any]:
        self._ensure_execution_not_cancelled(context)
        cfg = node_def.config or {}
        workflow_node_type = str(cfg.get("workflow_node_type") or "").strip().lower()
        if workflow_node_type == "input":
            return self._handle_input_node(cfg, input_data, context)
        if workflow_node_type == "output":
            return self._handle_output_node(cfg, input_data, context)
        if workflow_node_type in {"agent", "manager", "worker", "reflector"}:
            return await self._execute_agent_node(
                node_def=node_def,
                input_data=input_data,
                context=context,
                cfg=cfg,
            )
        if workflow_node_type == "sub_workflow":
            return await self._execute_sub_workflow_node(
                node_def=node_def,
                input_data=input_data,
                context=context,
                cfg=cfg,
            )
        if workflow_node_type == "loop":
            return await self._execute_loop_control_node(
                node_def=node_def,
                input_data=input_data,
                context=context,
                cfg=cfg,
            )
        if workflow_node_type == "parallel":
            return self._execute_parallel_control_node(
                node_def=node_def,
                input_data=input_data,
                context=context,
                cfg=cfg,
            )
        if workflow_node_type == "approval":
            return self._handle_approval_node(node_def, context)
        result = await self._execute_tool_node(cfg, input_data, context)
        self._ensure_execution_not_cancelled(context)
        return result

    async def _loop_handler(
        self, node_def: NodeDefinition, input_data: Dict[str, Any], context: GraphContext
    ) -> Dict[str, Any]:
        cfg = node_def.config or {}
        return await self._execute_loop_control_node(
            node_def=node_def,
            input_data=input_data,
            context=context,
            cfg=cfg,
        )

    async def _script_handler(
        self, node_def: NodeDefinition, input_data: Dict[str, Any], context: GraphContext
    ) -> Dict[str, Any]:
        cfg = node_def.config or {}
        command = cfg.get("command") or (input_data or {}).get("command")
        if not command:
            return {"error": "Script node missing command"}
        cfg = dict(cfg)
        cfg["tool_name"] = cfg.get("tool_name") or "builtin_shell.run"
        return await self._tool_handler(
            node_def=type(node_def)(**{**node_def.model_dump(), "config": cfg}),
            input_data={**(input_data or {}), "command": command},
            context=context,
        )

    async def _llm_handler(
        self, node_def: NodeDefinition, input_data: Dict[str, Any], context: GraphContext
    ) -> Dict[str, Any]:
        self._ensure_execution_not_cancelled(context)
        cfg = node_def.config or {}
        model_id = cfg.get("model_id")
        legacy_model = cfg.get("model")
        model = model_id or legacy_model
        if not model:
            return {"error": "LLM node missing model"}
        if model_id and legacy_model and model_id != legacy_model:
            logger.warning(
                "[WorkflowRuntime] LLM node %s has both model_id=%s and legacy model=%s, using model_id",
                node_def.id,
                model_id,
                legacy_model,
            )
        prompt = cfg.get("prompt") or (input_data or {}).get("prompt")
        if prompt is None:
            prompt = json.dumps(input_data or {}, ensure_ascii=False, sort_keys=True)
        resp = await self._inference_client.generate(
            model=model,
            prompt=str(prompt),
            system_prompt=cfg.get("system_prompt"),
            temperature=float(cfg.get("temperature", 0.7)),
            max_tokens=int(cfg.get("max_tokens", 2048)),
            stop=cfg.get("stop") if isinstance(cfg.get("stop"), list) else None,
            metadata={"source": "workflow_runtime", "node_id": node_def.id},
        )
        self._ensure_execution_not_cancelled(context)
        return cast(Dict[str, Any], resp.to_dict())

    async def _condition_handler(
        self, node_def: NodeDefinition, input_data: Dict[str, Any], context: GraphContext
    ) -> Dict[str, Any]:
        return cast(Dict[str, Any], await execute_condition_node(node_def, input_data, context))

    def _handle_input_node(
        self, cfg: Dict[str, Any], input_data: Dict[str, Any], context: GraphContext
    ) -> Dict[str, Any]:
        global_ctx = getattr(context, "global_data", {}) or {}
        base = global_ctx.get("input_data") if isinstance(global_ctx.get("input_data"), dict) else {}
        out: Dict[str, Any] = dict(base or {})
        fixed_input = cfg.get("fixed_input")
        if isinstance(fixed_input, dict):
            out = {**out, **fixed_input}
        if isinstance(input_data, dict) and input_data:
            out = {**out, **input_data}
        input_key = str(cfg.get("input_key") or "").strip()
        if input_key:
            return {input_key: out.get(input_key)} if input_key in out else {}
        return out

    def _handle_output_node(
        self, cfg: Dict[str, Any], input_data: Dict[str, Any], context: GraphContext
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = dict(input_data or {})
        fixed_input = cfg.get("fixed_input")
        if isinstance(fixed_input, dict):
            out = {**fixed_input, **out}

        allow_output_auto_fallback = bool(cfg.get("allow_auto_fallback", False))
        if allow_output_auto_fallback:
            out = self._apply_output_auto_fallback(out, context)

        output_key = str(cfg.get("output_key") or "").strip()
        expression = cfg.get("expression")
        expression_value = expression if isinstance(expression, str) and expression.strip() else None
        if output_key:
            if expression_value:
                value = context.resolve(expression_value)
                source_mode = "expression"
            else:
                value = out.get(output_key) if output_key in out else out
                source_mode = "passthrough"
            return {
                output_key: value,
                "__workflow_output_source": {
                    "mode": source_mode,
                    "output_key": output_key,
                    "expression": expression_value,
                },
            }
        return {
            **out,
            "__workflow_output_source": {
                "mode": "passthrough",
                "output_key": None,
                "expression": expression_value,
            },
        }

    def _apply_output_auto_fallback(self, out: Dict[str, Any], context: GraphContext) -> Dict[str, Any]:
        current = dict(out)
        if not current:
            first_candidate = self._latest_non_empty_node_output(context)
            if first_candidate is not None:
                current = first_candidate

        semantic_keys = {"query", "text", "prompt", "message", "topic", "input"}
        has_result_like = any(k in current for k in ("response", "result", "output", "content"))
        only_semantic_input = (not has_result_like) and set(current.keys()).issubset(semantic_keys)
        if only_semantic_input:
            second_candidate = self._latest_result_like_node_output(context)
            if second_candidate is not None:
                current = second_candidate
        return current

    @staticmethod
    def _latest_non_empty_node_output(context: GraphContext) -> Optional[Dict[str, Any]]:
        if not hasattr(context, "node_outputs"):
            return None
        try:
            values = list((context.node_outputs or {}).values())
            for candidate in reversed(values):
                if isinstance(candidate, dict) and candidate:
                    return candidate
        except Exception:
            return None
        return None

    @staticmethod
    def _latest_result_like_node_output(context: GraphContext) -> Optional[Dict[str, Any]]:
        if not hasattr(context, "node_outputs"):
            return None
        try:
            values = list((context.node_outputs or {}).values())
            for candidate in reversed(values):
                if not isinstance(candidate, dict) or not candidate:
                    continue
                if str(candidate.get("type") or "").strip().lower() == "agent_result":
                    return candidate
                if any(k in candidate for k in ("response", "result", "output", "content")):
                    return candidate
        except Exception:
            return None
        return None

    def _handle_approval_node(self, node_def: NodeDefinition, context: GraphContext) -> Dict[str, Any]:
        global_ctx = getattr(context, "global_data", {}) or {}
        node_id = str(getattr(node_def, "id", "") or "")
        decisions = global_ctx.get("approval_decisions") or {}
        if str(decisions.get(node_id) or "").lower() == "approved":
            return {"type": "approval_result", "status": "approved", "node_id": node_id}
        raise RuntimeError(f"WORKFLOW_APPROVAL_NOT_GRANTED: node_id={node_id}")

    async def _execute_tool_node(
        self, cfg: Dict[str, Any], input_data: Dict[str, Any], context: GraphContext
    ) -> Dict[str, Any]:
        tool_name = cfg.get("tool_name") or cfg.get("tool_id")
        if not tool_name:
            return {"error": "Tool node missing tool_name/tool_id"}

        global_ctx = getattr(context, "global_data", {}) or {}
        permissions = global_ctx.get("permissions") or {}
        workspace = global_ctx.get("workspace") or "."
        trace_id = global_ctx.get("trace_id")
        agent_id_raw = global_ctx.get("agent_id")
        tool_agent_id = str(agent_id_raw).strip() if agent_id_raw is not None else None
        tool_ctx = ToolContext(
            agent_id=tool_agent_id,
            trace_id=trace_id,
            workspace=workspace,
            permissions=permissions,
        )

        tool_input = dict(input_data or {})
        fixed_input = cfg.get("fixed_input")
        if isinstance(fixed_input, dict):
            tool_input.update(fixed_input)

        result = await ToolRegistry.execute(tool_name, tool_input, tool_ctx)
        if not result.success:
            return {"error": result.error or f"Tool failed: {tool_name}"}
        return result.data if isinstance(result.data, dict) else {"output": result.data}

    async def _execute_loop_control_node(
        self,
        *,
        node_def: NodeDefinition,
        input_data: Dict[str, Any],
        context: GraphContext,
        cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        loop_type = str(cfg.get("loop_type") or "").strip().lower()
        max_iterations = max(1, self._coerce_int(cfg.get("max_iterations"), 100))
        loop_count = self._resolve_loop_count(cfg=cfg, input_data=input_data, context=context)
        if loop_type not in {"for", "while"}:
            loop_type = "for" if loop_count is not None else "while"
        if loop_type == "for" and loop_count is None:
            loop_count = max_iterations
        if loop_type == "for":
            max_iterations = max(1, min(max_iterations, int(loop_count or max_iterations)))

        max_retries = max(0, self._coerce_int(cfg.get("max_retries"), 0))
        retry_interval_seconds = self._coerce_float(cfg.get("retry_interval_seconds"), 1.0)
        if retry_interval_seconds < 0:
            retry_interval_seconds = 0.0
        condition_expression = cfg.get("condition_expression")
        iterator_variable = str(cfg.get("iterator_variable") or "loop_index").strip() or "loop_index"
        body_cfg = cfg.get("loop_body")
        if not isinstance(body_cfg, dict):
            return {"error": "Loop node missing loop_body config"}

        iteration = 0
        last_output: Dict[str, Any] = {}
        exit_reason = "max_iterations"
        loop_input = dict(input_data or {})

        while iteration < max_iterations:
            if loop_type == "while" and condition_expression:
                condition_ok = bool(self._evaluate_boolean_expression(context, loop_input, condition_expression))
                if not condition_ok:
                    exit_reason = "condition_false"
                    break
            if loop_type == "for" and loop_count is not None and iteration >= int(loop_count):
                exit_reason = "loop_count_reached"
                break

            self._inject_loop_iteration_context(
                context=context,
                node_id=str(node_def.id),
                iteration=iteration,
                iterator_variable=iterator_variable,
            )
            merged_body_input = dict(loop_input or {})
            merged_body_input[iterator_variable] = iteration

            last_exc: Optional[Exception] = None
            attempt = 0
            while attempt <= max_retries:
                try:
                    last_output = await self._execute_loop_body(
                        node_def=node_def,
                        body_cfg=body_cfg,
                        input_data=merged_body_input,
                        context=context,
                    )
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt >= max_retries:
                        break
                    await asyncio.sleep(retry_interval_seconds)
                    attempt += 1

            if last_exc is not None:
                raise RuntimeError(
                    f"LOOP_NODE_EXECUTION_FAILED: node={node_def.id}, iteration={iteration}, error={last_exc}"
                ) from last_exc

            iteration += 1
            loop_input = {**loop_input, **(last_output or {})}
            if condition_expression:
                should_continue = bool(
                    self._evaluate_boolean_expression(context, loop_input, condition_expression)
                )
                if loop_type == "for" and not should_continue:
                    exit_reason = "condition_false"
                    break

        return {
            **(last_output if isinstance(last_output, dict) else {}),
            "type": "loop_result",
            "loop_completed": True,
            "iterations": iteration,
            "exit_reason": exit_reason,
            "__workflow_loop_meta": {
                "node_id": str(node_def.id),
                "loop_type": loop_type,
                "max_iterations": max_iterations,
                "loop_count": loop_count,
                "iterator_variable": iterator_variable,
            },
        }

    def _execute_parallel_control_node(
        self,
        *,
        node_def: NodeDefinition,
        input_data: Dict[str, Any],
        context: GraphContext,
        cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        requested = cfg.get("max_parallel")
        max_parallel = max(1, self._coerce_int(requested, 5))
        return {
            **(input_data or {}),
            "type": "parallel_gate",
            "parallel_ready": True,
            "__workflow_parallel_meta": {
                "node_id": str(node_def.id),
                "max_parallel": max_parallel,
            },
        }

    async def _execute_loop_body(
        self,
        *,
        node_def: NodeDefinition,
        body_cfg: Dict[str, Any],
        input_data: Dict[str, Any],
        context: GraphContext,
    ) -> Dict[str, Any]:
        body_type = str(body_cfg.get("type") or "tool").strip().lower()
        if body_type == "tool":
            result = await self._execute_tool_node(body_cfg, input_data, context)
            if isinstance(result, dict) and result.get("error"):
                raise RuntimeError(str(result.get("error")))
            return result if isinstance(result, dict) else {"output": result}
        if body_type in {"agent", "manager", "worker", "reflector"}:
            proxy_def = type(node_def)(**{**node_def.model_dump(), "config": {**body_cfg, "workflow_node_type": body_type}})
            return await self._execute_agent_node(
                node_def=proxy_def,
                input_data=input_data,
                context=context,
                cfg={**body_cfg, "workflow_node_type": body_type},
            )
        raise ValueError(f"LOOP_NODE_CONFIG_ERROR: unsupported loop_body.type '{body_type}'")

    @staticmethod
    def _coerce_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _resolve_loop_count(
        self,
        *,
        cfg: Dict[str, Any],
        input_data: Dict[str, Any],
        context: GraphContext,
    ) -> Optional[int]:
        raw_count = cfg.get("loop_count")
        loop_count_expr = cfg.get("loop_count_expression")
        if isinstance(loop_count_expr, str) and loop_count_expr.strip():
            resolved = context.resolve(loop_count_expr)
            raw_count = resolved
        elif raw_count is None and isinstance(input_data, dict):
            raw_count = input_data.get("loop_count")
        if raw_count is None:
            return None
        count = self._coerce_int(raw_count, 0)
        return max(0, count)

    @staticmethod
    def _inject_loop_iteration_context(
        *,
        context: GraphContext,
        node_id: str,
        iteration: int,
        iterator_variable: str,
    ) -> None:
        data = getattr(context, "_global_data", None)
        if not isinstance(data, dict):
            return
        workflow_vars = data.get("workflow_variables")
        if not isinstance(workflow_vars, dict):
            workflow_vars = {}
            data["workflow_variables"] = workflow_vars
        loop_vars = workflow_vars.get("loop")
        if not isinstance(loop_vars, dict):
            loop_vars = {}
            workflow_vars["loop"] = loop_vars
        loop_vars[node_id] = {
            "iteration": iteration,
            iterator_variable: iteration,
        }

    @staticmethod
    def _evaluate_boolean_expression(
        context: GraphContext,
        input_data: Dict[str, Any],
        expression: Any,
    ) -> bool:
        if not isinstance(expression, str) or not expression.strip():
            return True
        from execution_kernel.engine.control_flow import _evaluate_condition  # local import to avoid cycle risk

        return bool(_evaluate_condition(expression, input_data or {}, context))

    async def _execute_agent_node(
        self,
        *,
        node_def: NodeDefinition,
        input_data: Dict[str, Any],
        context: GraphContext,
        cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        agent_id = str(cfg.get("agent_id") or "").strip()
        if not agent_id:
            raise ValueError("AGENT_NODE_CONFIG_ERROR: missing agent_id")

        registry = get_agent_registry()
        target_agent = registry.get_agent(agent_id)
        if not target_agent:
            raise ValueError(f"AGENT_NODE_NOT_FOUND: {agent_id}")
        run_agent = target_agent.model_copy(deep=True)

        global_ctx = getattr(context, "global_data", {}) or {}
        workspace = global_ctx.get("workspace") or "."
        workflow_execution_id = str(global_ctx.get("execution_id") or "").strip()
        user_id = str(global_ctx.get("user_id") or "default").strip() or "default"

        call_chain = self._validate_agent_node_governance(
            agent_id=agent_id,
            cfg=cfg,
            global_ctx=global_ctx,
            coerce_int=self._coerce_int,
            max_call_depth=self.AGENT_NODE_MAX_CALL_DEPTH,
            default_max_calls=self.AGENT_NODE_DEFAULT_MAX_CALLS,
        )
        orchestrator_filled_here = False
        if not str(global_ctx.get("orchestrator_agent_id") or "").strip():
            global_ctx["orchestrator_agent_id"] = (call_chain[0] if call_chain else agent_id)
            orchestrator_filled_here = True
        if orchestrator_filled_here and workflow_execution_id:
            self._persist_orchestrator_agent_id_to_execution(workflow_execution_id, global_ctx)
        prompt = self._resolve_agent_prompt(
            cfg=cfg,
            input_data=input_data,
            context=context,
            global_ctx=global_ctx,
            infer_prompt_from_payload=self._infer_prompt_from_payload,
        )
        prompt = self._attach_agent_context_suffix(
            prompt=prompt,
            cfg=cfg,
            input_data=input_data,
            global_ctx=global_ctx,
        )
        self._apply_agent_run_overrides(run_agent, cfg, self._coerce_int)
        session = self._build_agent_session(
            run_agent=run_agent,
            prompt=prompt,
            user_id=user_id,
            workspace=workspace,
            workflow_execution_id=workflow_execution_id,
            node_id=str(node_def.id),
            call_chain=call_chain,
            agent_id=agent_id,
            global_ctx=global_ctx,
            node_role=str(cfg.get("workflow_node_type") or "agent").strip().lower(),
        )

        result_session, recovery_meta = await self._run_agent_runtime_with_reflector(
            run_agent=run_agent,
            session=session,
            workspace=workspace,
            cfg=cfg,
            registry=registry,
            primary_agent_id=agent_id,
            global_ctx=global_ctx,
        )
        self._ensure_agent_session_success(result_session, agent_id)
        agent_output = self._build_agent_output(
            result_session,
            agent_id,
            str(node_def.id),
            recovery_meta=recovery_meta,
        )
        self._validate_agent_output_schema(agent_output, cfg, node_def)
        self._ensure_execution_not_cancelled(context)
        return agent_output

    async def _execute_sub_workflow_node(
        self,
        *,
        node_def: NodeDefinition,
        input_data: Dict[str, Any],
        context: GraphContext,
        cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        target_workflow_id = str(cfg.get("target_workflow_id") or "").strip()
        if not target_workflow_id:
            raise ValueError("SUB_WORKFLOW_CONFIG_ERROR: missing target_workflow_id")

        global_ctx = getattr(context, "global_data", {}) or {}
        call_depth = int(global_ctx.get("sub_workflow_call_depth") or 0)
        max_depth = max(1, int(getattr(settings, "workflow_subworkflow_max_depth", 5) or 5))
        if call_depth >= max_depth:
            raise RuntimeError(
                f"SUB_WORKFLOW_DEPTH_EXCEEDED: current={call_depth}, max={max_depth}, node={node_def.id}"
            )

        target_version_id = self._resolve_sub_workflow_version(target_workflow_id, cfg)
        child_input = build_child_input(
            input_mapping=cfg.get("input_mapping") if isinstance(cfg.get("input_mapping"), dict) else {},
            context=context,
            node_input=input_data or {},
        )
        child_global_context = {
            **(global_ctx if isinstance(global_ctx, dict) else {}),
            "parent_execution_id": str(global_ctx.get("execution_id") or "").strip(),
            "parent_node_id": str(node_def.id),
            "parent_workflow_id": str(global_ctx.get("workflow_id") or "").strip(),
            "sub_workflow_call_depth": call_depth + 1,
        }

        from core.workflows.services.workflow_execution_service import WorkflowExecutionService

        execution_service = WorkflowExecutionService(self.db, execution_manager=self.execution_manager)
        child_execution = execution_service.create_execution(
            WorkflowExecutionCreateRequest(
                workflow_id=target_workflow_id,
                version_id=target_version_id,
                input_data=child_input,
                global_context=child_global_context,
                trigger_type="workflow",
            ),
            triggered_by=str(global_ctx.get("user_id") or global_ctx.get("triggered_by") or "workflow_runtime"),
        )

        timeout = cfg.get("wait_timeout_seconds")
        timeout_seconds = float(timeout) if timeout is not None else None
        child_result = await self.execute(
            child_execution,
            wait_for_completion=True,
            wait_timeout_seconds=timeout_seconds,
        )
        if child_result.state != WorkflowExecutionState.COMPLETED:
            strategy = str(cfg.get("on_failure") or "bubble_up").strip().lower()
            if strategy == "fallback":
                fallback_output = cfg.get("fallback_output")
                if isinstance(fallback_output, dict):
                    return fallback_output
                return {"type": "sub_workflow_result", "status": "fallback", "child_execution_id": child_result.execution_id}
            raise RuntimeError(
                f"SUB_WORKFLOW_EXECUTION_FAILED: node={node_def.id}, "
                f"execution_id={child_result.execution_id}, state={child_result.state.value}, "
                f"error={child_result.error_message}"
            )

        mapped_output = apply_output_mapping(
            child_output=child_result.output_data or {},
            output_mapping=cfg.get("output_mapping") if isinstance(cfg.get("output_mapping"), dict) else {},
        )
        return {
            "type": "sub_workflow_result",
            "status": "success",
            "child_workflow_id": target_workflow_id,
            "child_version_id": target_version_id,
            "child_execution_id": child_result.execution_id,
            **mapped_output,
        }

    def _resolve_sub_workflow_version(self, target_workflow_id: str, cfg: Dict[str, Any]) -> str:
        selector = str(cfg.get("version_selector") or cfg.get("target_version_selector") or "fixed").strip().lower()
        if selector not in {"fixed", "latest"}:
            raise ValueError(f"SUB_WORKFLOW_CONFIG_ERROR: unsupported version selector '{selector}'")

        if selector == "latest":
            if (not bool(getattr(settings, "debug", False))) and (
                not bool(getattr(settings, "workflow_allow_latest_subworkflow_in_production", False))
            ):
                raise ValueError(
                    "SUB_WORKFLOW_VERSION_POLICY_ERROR: latest selector is disabled in production"
                )
            version = self.version_repository.get_published_version(target_workflow_id)
            if not version:
                raise ValueError(
                    f"SUB_WORKFLOW_VERSION_NOT_FOUND: no published version for workflow {target_workflow_id}"
                )
            return version.version_id

        target_version_id = str(cfg.get("target_version_id") or "").strip()
        target_version_number = str(cfg.get("target_version") or "").strip()
        if target_version_id:
            version = self.version_repository.get_version_by_id(target_version_id)
            if not version:
                raise ValueError(
                    f"SUB_WORKFLOW_VERSION_NOT_FOUND: version_id={target_version_id}"
                )
            if version.workflow_id != target_workflow_id:
                raise ValueError(
                    "SUB_WORKFLOW_CONFIG_ERROR: target_version_id does not belong to target_workflow_id"
                )
            return version.version_id
        if target_version_number:
            version = self.version_repository.get_version_by_number(target_workflow_id, target_version_number)
            if not version:
                raise ValueError(
                    f"SUB_WORKFLOW_VERSION_NOT_FOUND: workflow_id={target_workflow_id}, version={target_version_number}"
                )
            return version.version_id
        raise ValueError(
            "SUB_WORKFLOW_CONFIG_ERROR: fixed selector requires target_version_id or target_version"
        )

    def _persist_orchestrator_agent_id_to_execution(
        self, workflow_execution_id: str, global_ctx: Dict[str, Any]
    ) -> None:
        """首次确定 orchestrator 时写回 DB，与 API 中 global_context 展示一致。"""
        oid = str(global_ctx.get("orchestrator_agent_id") or "").strip()
        if not workflow_execution_id or not oid:
            return
        try:
            cur = self.execution_repository.get_by_id(workflow_execution_id)
            if cur is None:
                return
            merged = {**(cur.global_context or {}), "orchestrator_agent_id": oid}
            self.execution_repository.update_global_context(workflow_execution_id, merged)
        except Exception as e:
            logger.warning(
                "[WorkflowRuntime] Failed to persist orchestrator_agent_id to global_context: %s",
                e,
            )

    def _apply_agent_run_overrides(
        self, run_agent: Any, cfg: Dict[str, Any], coerce_int: Callable[[Any, int], int]
    ) -> None:
        if cfg.get("max_steps") is not None:
            run_agent.max_steps = max(1, coerce_int(cfg.get("max_steps"), run_agent.max_steps))
        model_override = str(cfg.get("model_override") or "").strip()
        if model_override:
            run_agent.model_id = model_override

    def _build_agent_session(
        self,
        *,
        run_agent: Any,
        prompt: str,
        user_id: str,
        workspace: str,
        workflow_execution_id: str,
        node_id: str,
        call_chain: List[str],
        agent_id: str,
        global_ctx: Dict[str, Any],
        node_role: str,
    ) -> AgentSession:
        node_session_id = (
            f"wf_{workflow_execution_id}_{node_id}"
            if workflow_execution_id else f"wf_{node_id}"
        )
        session = AgentSession(
            session_id=node_session_id,
            agent_id=run_agent.agent_id,
            user_id=user_id,
            messages=[Message(role="user", content=str(prompt))],
            status="idle",
        )
        session.workspace_dir = workspace
        wfc = {
            "workflow_execution_id": workflow_execution_id,
            "source_node_id": node_id,
            "call_depth": len(call_chain) + 1,
            "call_chain": call_chain + [agent_id],
            "node_role": node_role or "agent",
        }
        collab = build_workflow_collaboration(
            global_ctx=global_ctx,
            workflow_execution_id=workflow_execution_id,
            node_id=node_id,
            call_chain=call_chain,
            agent_id=agent_id,
        )
        session.state = merge_collaboration_into_state(
            {
                "workflow_agent_context": wfc,
            },
            collab,
        )
        return session

    @staticmethod
    def _ensure_agent_session_success(result_session: AgentSession, agent_id: str) -> None:
        if result_session.status == "error":
            raise RuntimeError(
                f"AGENT_NODE_RUNTIME_ERROR: {result_session.error_message or f'Agent run failed: {agent_id}'}"
            )

    @staticmethod
    def _extract_assistant_reply(result_session: AgentSession) -> str:
        assistant_reply = ""
        for msg in reversed(result_session.messages):
            if msg.role == "assistant":
                assistant_reply = msg.content if isinstance(msg.content, str) else str(msg.content)
                break
        return assistant_reply

    def _build_agent_output(
        self,
        result_session: AgentSession,
        agent_id: str,
        node_id: str,
        recovery_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        assistant_reply = self._extract_assistant_reply(result_session)
        node_role = self._extract_node_role_from_session(result_session)
        output: Dict[str, Any] = {
            "type": "agent_result",
            "status": "success",
            "agent_id": agent_id,
            "agent_session_id": result_session.session_id,
            "workflow_node_id": node_id,
            "agent_role": node_role,
            "response": assistant_reply,
            "response_preview": assistant_reply[:500],
        }
        collaboration_messages = self._extract_collaboration_messages_from_session(result_session)
        if collaboration_messages:
            output["collaboration_messages"] = collaboration_messages
        if isinstance(recovery_meta, dict) and recovery_meta:
            output["recovery"] = recovery_meta
        return output

    @staticmethod
    def _extract_node_role_from_session(result_session: AgentSession) -> str:
        state = result_session.state if isinstance(result_session.state, dict) else {}
        agent_ctx = state.get("workflow_agent_context") if isinstance(state, dict) else {}
        role = str((agent_ctx or {}).get("node_role") or "").strip().lower()
        return role or "agent"

    @staticmethod
    def _extract_collaboration_messages_from_session(result_session: AgentSession) -> List[Dict[str, Any]]:
        state = result_session.state if isinstance(result_session.state, dict) else {}
        collab = state.get("collaboration") if isinstance(state, dict) else {}
        if not isinstance(collab, dict):
            return []
        messages = collab.get("messages")
        if not isinstance(messages, list):
            return []
        out: List[Dict[str, Any]] = []
        for item in messages:
            if isinstance(item, dict):
                out.append(dict(item))
        return out

    def _validate_agent_output_schema(
        self, agent_output: Dict[str, Any], cfg: Dict[str, Any], node_def: NodeDefinition
    ) -> None:
        schema: Dict[str, Any] = {}
        cfg_output_schema = cfg.get("output_schema")
        if isinstance(cfg_output_schema, dict):
            schema = cast(Dict[str, Any], cfg_output_schema)
        elif isinstance(getattr(node_def, "output_schema", None), dict):
            schema = cast(Dict[str, Any], getattr(node_def, "output_schema"))
        err = self._validate_simple_output_schema(agent_output, schema)
        if err:
            raise ValueError(
                f"AGENT_NODE_OUTPUT_SCHEMA_ERROR: {json.dumps(err, ensure_ascii=False)}"
            )

    def _validate_agent_node_governance(
        self,
        *,
        agent_id: str,
        cfg: Dict[str, Any],
        global_ctx: Dict[str, Any],
        coerce_int: Callable[[Any, int], int],
        max_call_depth: int,
        default_max_calls: int,
    ) -> List[str]:
        call_chain = global_ctx.get("agent_call_chain")
        if not isinstance(call_chain, list):
            call_chain = []
        normalized_chain = [str(x).strip() for x in call_chain if str(x).strip()]
        if agent_id in normalized_chain:
            raise RuntimeError(
                f"AGENT_NODE_RECURSION_GUARD: loop detected in agent_call_chain={normalized_chain + [agent_id]}"
            )
        if len(normalized_chain) >= max_call_depth:
            raise RuntimeError(
                f"AGENT_NODE_RECURSION_GUARD: max depth exceeded ({max_call_depth})"
            )
        max_calls = coerce_int(global_ctx.get("agent_node_max_calls"), default_max_calls)
        if cfg.get("agent_max_calls") is not None:
            max_calls = max(1, coerce_int(cfg.get("agent_max_calls"), max_calls))
        current_calls = coerce_int(global_ctx.get("__agent_node_call_count"), 0)
        if current_calls >= max_calls:
            raise RuntimeError(f"AGENT_NODE_GOVERNANCE_LIMIT: max calls exceeded ({max_calls})")
        global_ctx["__agent_node_call_count"] = current_calls + 1
        return normalized_chain

    def _resolve_agent_prompt(
        self,
        *,
        cfg: Dict[str, Any],
        input_data: Dict[str, Any],
        context: GraphContext,
        global_ctx: Dict[str, Any],
        infer_prompt_from_payload: Callable[[Any], Optional[str]],
    ) -> str:
        effective_input = self._build_effective_agent_input(cfg, input_data, context)
        prompt = self._pick_agent_prompt_candidate(
            cfg=cfg,
            effective_input=effective_input,
            global_ctx=global_ctx,
            infer_prompt_from_payload=infer_prompt_from_payload,
        )
        if prompt is not None:
            return prompt
        self._raise_agent_prompt_missing(effective_input, global_ctx.get("input_data"))
        raise AssertionError("unreachable")

    def _build_effective_agent_input(
        self, cfg: Dict[str, Any], input_data: Dict[str, Any], context: GraphContext
    ) -> Dict[str, Any]:
        effective_input = dict(input_data or {})
        fixed_input = cfg.get("fixed_input")
        if isinstance(fixed_input, dict):
            effective_input = {**fixed_input, **effective_input}
        if bool(cfg.get("allow_auto_input_fallback", False)) and not effective_input and hasattr(context, "node_outputs"):
            try:
                values = list((context.node_outputs or {}).values())
                for candidate in reversed(values):
                    if isinstance(candidate, dict) and candidate:
                        effective_input = dict(candidate)
                        break
            except Exception:
                pass
        return effective_input

    def _pick_agent_prompt_candidate(
        self,
        *,
        cfg: Dict[str, Any],
        effective_input: Dict[str, Any],
        global_ctx: Dict[str, Any],
        infer_prompt_from_payload: Callable[[Any], Optional[str]],
    ) -> Optional[str]:
        prompt = cast(Optional[str], cfg.get("prompt") or effective_input.get("prompt"))
        if prompt is None:
            prompt = cast(
                Optional[str],
                effective_input.get("message") or effective_input.get("query") or effective_input.get("text"),
            )
        if prompt is None:
            prompt = infer_prompt_from_payload(effective_input)
        if prompt is None:
            workflow_input = global_ctx.get("input_data") or {}
            if isinstance(workflow_input, dict):
                prompt = cast(
                    Optional[str],
                    workflow_input.get("prompt")
                    or workflow_input.get("message")
                    or workflow_input.get("query")
                    or workflow_input.get("text"),
                )
            elif workflow_input not in (None, ""):
                prompt = str(workflow_input)
        if prompt is None:
            prompt = infer_prompt_from_payload(global_ctx.get("input_data"))
        if prompt is None:
            prompt = self._fallback_prompt_from_structured_data(
                effective_input=effective_input,
                workflow_input=global_ctx.get("input_data"),
            )
        return prompt

    @staticmethod
    def _fallback_prompt_from_structured_data(
        *, effective_input: Dict[str, Any], workflow_input: Any
    ) -> Optional[str]:
        if effective_input:
            return json.dumps(effective_input, ensure_ascii=False, sort_keys=True)
        workflow_input_dict = workflow_input or {}
        if isinstance(workflow_input_dict, dict) and workflow_input_dict:
            return json.dumps(workflow_input_dict, ensure_ascii=False, sort_keys=True)
        return None

    @staticmethod
    def _raise_agent_prompt_missing(effective_input: Dict[str, Any], workflow_input: Any) -> None:
        dbg_node_keys = sorted([str(k) for k in effective_input.keys()]) if isinstance(effective_input, dict) else []
        dbg_workflow_keys = (
            sorted([str(k) for k in workflow_input.keys()])
            if isinstance(workflow_input, dict)
            else []
        )
        raise ValueError(
            "AGENT_NODE_INPUT_EMPTY: missing prompt/message/query/text in node input and workflow input_data; "
            f"node_input_keys={dbg_node_keys}, workflow_input_keys={dbg_workflow_keys}; "
            "fix_by=provide one of: "
            "1) node.config.prompt, "
            "2) node.config.fixed_input.query|text|message|prompt, "
            "3) execution input_data.query|text|message|prompt"
        )

    def _attach_agent_context_suffix(
        self,
        *,
        prompt: str,
        cfg: Dict[str, Any],
        input_data: Dict[str, Any],
        global_ctx: Dict[str, Any],
    ) -> str:
        pass_context_keys = cfg.get("pass_context_keys")
        if not (isinstance(pass_context_keys, list) and pass_context_keys):
            return prompt

        passed: Dict[str, Any] = {}
        for key in pass_context_keys:
            k = str(key).strip()
            if not k:
                continue
            if isinstance(input_data, dict) and k in input_data:
                passed[k] = input_data.get(k)
            elif k in global_ctx:
                passed[k] = global_ctx.get(k)
        if not passed:
            return prompt
        return f"{prompt}\n\nContext:\n{json.dumps(passed, ensure_ascii=False)}"

    async def _run_agent_runtime_session(
        self,
        *,
        run_agent: Any,
        session: AgentSession,
        workspace: str,
        cfg: Dict[str, Any],
    ) -> AgentSession:
        runtime = get_agent_runtime(get_agent_executor())
        timeout_sec = cfg.get("timeout")
        if timeout_sec is None:
            timeout_sec = cfg.get("agent_timeout_seconds")
        if timeout_sec is not None:
            return await asyncio.wait_for(
                runtime.run(run_agent, session, workspace=workspace),
                timeout=float(timeout_sec),
            )
        return await runtime.run(run_agent, session, workspace=workspace)

    async def _run_agent_runtime_with_reflector(
        self,
        *,
        run_agent: Any,
        session: AgentSession,
        workspace: str,
        cfg: Dict[str, Any],
        registry: Any,
        primary_agent_id: str,
        global_ctx: Dict[str, Any],
    ) -> tuple[AgentSession, Dict[str, Any]]:
        """
        失败恢复策略（Reflector Phase 1）：
        1) 主 Agent 失败后按配置重试
        2) 仍失败时可切换 fallback Agent 执行
        """
        retry_cfg = self._resolve_reflector_retry_config(cfg, global_ctx=global_ctx)
        max_retries = retry_cfg["max_retries"]
        retry_interval_seconds = retry_cfg["retry_interval_seconds"]
        fallback_agent_id = retry_cfg["fallback_agent_id"]
        (
            primary_result,
            session,
            attempts_trace,
            last_error_message,
        ) = await self._run_primary_agent_with_retries(
            run_agent=run_agent,
            session=session,
            workspace=workspace,
            cfg=cfg,
            primary_agent_id=primary_agent_id,
            max_retries=max_retries,
            retry_interval_seconds=retry_interval_seconds,
        )
        if primary_result is not None:
            return primary_result, {
                "recovery_mode": "direct_or_retry",
                "attempts": len(attempts_trace),
                "fallback_used": False,
                "recovery_trace": attempts_trace,
            }

        if not fallback_agent_id:
            raise RuntimeError(self._build_reflector_failure_message(
                primary_agent_id=primary_agent_id,
                fallback_agent_id=None,
                primary_error=last_error_message or f"Agent run failed: {primary_agent_id}",
                fallback_error=None,
                attempts_trace=attempts_trace,
            ))

        fallback_agent = registry.get_agent(fallback_agent_id)
        if not fallback_agent:
            raise RuntimeError(self._build_reflector_failure_message(
                primary_agent_id=primary_agent_id,
                fallback_agent_id=fallback_agent_id,
                primary_error=last_error_message or "unknown",
                fallback_error=f"fallback agent not found: {fallback_agent_id}",
                attempts_trace=attempts_trace,
            ))
        fallback_run_agent = fallback_agent.model_copy(deep=True)
        fallback_session = session.model_copy(deep=True)
        fallback_session.agent_id = fallback_run_agent.agent_id
        fallback_session = self._record_agent_collaboration_event(
            fallback_session,
            receiver=fallback_agent_id,
            status="running",
            stage="fallback",
            attempt=1,
            event="fallback_started",
        )
        fallback_result = await self._run_agent_runtime_session(
            run_agent=fallback_run_agent,
            session=fallback_session,
            workspace=workspace,
            cfg=cfg,
        )
        if fallback_result.status == "error":
            fallback_error = fallback_result.error_message or "fallback run failed"
            fallback_result = self._record_agent_collaboration_event(
                fallback_result,
                receiver=fallback_agent_id,
                status="error",
                stage="fallback",
                attempt=1,
                event="fallback_failed",
                error=fallback_error,
            )
            attempts_trace.append(
                {
                    "attempt": 1,
                    "stage": "fallback",
                    "agent_id": fallback_agent_id,
                    "status": "error",
                    "error": fallback_error,
                }
            )
            raise RuntimeError(self._build_reflector_failure_message(
                primary_agent_id=primary_agent_id,
                fallback_agent_id=fallback_agent_id,
                primary_error=last_error_message or "unknown",
                fallback_error=fallback_error,
                attempts_trace=attempts_trace,
            ))
        fallback_result = self._record_agent_collaboration_event(
            fallback_result,
            receiver=fallback_agent_id,
            status="success",
            stage="fallback",
            attempt=1,
            event="fallback_succeeded",
        )
        attempts_trace.append(
            {
                "attempt": 1,
                "stage": "fallback",
                "agent_id": fallback_agent_id,
                "status": "success",
            }
        )
        return fallback_result, {
            "recovery_mode": "fallback_agent",
            "attempts": max_retries + 1,
            "fallback_used": True,
            "fallback_agent_id": fallback_agent_id,
            "primary_error": last_error_message,
            "recovery_trace": attempts_trace,
        }

    async def _run_primary_agent_with_retries(
        self,
        *,
        run_agent: Any,
        session: AgentSession,
        workspace: str,
        cfg: Dict[str, Any],
        primary_agent_id: str,
        max_retries: int,
        retry_interval_seconds: float,
    ) -> tuple[Optional[AgentSession], AgentSession, List[Dict[str, Any]], Optional[str]]:
        last_error_message: Optional[str] = None
        attempts_trace: List[Dict[str, Any]] = []
        for attempt in range(max_retries + 1):
            session = self._record_agent_collaboration_event(
                session,
                receiver=primary_agent_id,
                status="running",
                stage="primary",
                attempt=attempt + 1,
                event="attempt_started",
            )
            current_session = session.model_copy(deep=True)
            try:
                result = await self._run_agent_runtime_session(
                    run_agent=run_agent,
                    session=current_session,
                    workspace=workspace,
                    cfg=cfg,
                )
            except Exception as exc:
                last_error_message = str(exc)
                attempts_trace.append(
                    {
                        "attempt": attempt + 1,
                        "stage": "primary",
                        "status": "exception",
                        "error": last_error_message,
                    }
                )
                session = self._record_agent_collaboration_event(
                    session,
                    receiver=primary_agent_id,
                    status="error",
                    stage="primary",
                    attempt=attempt + 1,
                    event="attempt_exception",
                    error=last_error_message,
                )
                if attempt < max_retries:
                    session = self._record_agent_collaboration_event(
                        session,
                        receiver=primary_agent_id,
                        status="retry",
                        stage="primary",
                        attempt=attempt + 1,
                        event="retry_scheduled",
                        error=last_error_message,
                    )
                    await asyncio.sleep(retry_interval_seconds)
                    continue
                break
            if result.status != "error":
                attempts_trace.append(
                    {
                        "attempt": attempt + 1,
                        "stage": "primary",
                        "status": "success",
                    }
                )
                result = self._record_agent_collaboration_event(
                    result,
                    receiver=primary_agent_id,
                    status="success",
                    stage="primary",
                    attempt=attempt + 1,
                    event="attempt_succeeded",
                )
                return result, result, attempts_trace, last_error_message
            last_error_message = result.error_message or "agent runtime returned error status"
            attempts_trace.append(
                {
                    "attempt": attempt + 1,
                    "stage": "primary",
                    "status": "error",
                    "error": last_error_message,
                }
            )
            session = self._record_agent_collaboration_event(
                result,
                receiver=primary_agent_id,
                status="error",
                stage="primary",
                attempt=attempt + 1,
                event="attempt_failed",
                error=last_error_message,
            )
            if attempt < max_retries:
                session = self._record_agent_collaboration_event(
                    session,
                    receiver=primary_agent_id,
                    status="retry",
                    stage="primary",
                    attempt=attempt + 1,
                    event="retry_scheduled",
                    error=last_error_message,
                )
                await asyncio.sleep(retry_interval_seconds)
                continue
            break
        return None, session, attempts_trace, last_error_message

    @staticmethod
    def _record_agent_collaboration_event(
        session: AgentSession,
        *,
        receiver: str,
        status: str,
        stage: str,
        attempt: int,
        event: str,
        error: Optional[str] = None,
    ) -> AgentSession:
        state = session.state if isinstance(session.state, dict) else {}
        collab = state.get("collaboration") if isinstance(state, dict) else {}
        collab = collab if isinstance(collab, dict) else {}
        sender = str(collab.get("orchestrator_agent_id") or "workflow_runtime").strip() or "workflow_runtime"
        workflow_ctx = state.get("workflow_agent_context") if isinstance(state, dict) else {}
        workflow_ctx = workflow_ctx if isinstance(workflow_ctx, dict) else {}
        workflow_execution_id = str(workflow_ctx.get("workflow_execution_id") or "").strip()
        source_node_id = str(workflow_ctx.get("source_node_id") or "").strip()
        task_id = f"{workflow_execution_id}:{source_node_id}" if workflow_execution_id and source_node_id else session.session_id
        content: Dict[str, Any] = {
            "event": event,
            "stage": stage,
            "attempt": int(attempt),
            "session_id": session.session_id,
        }
        if error:
            content["error"] = error
        message = build_collaboration_message(
            {
                "sender": sender,
                "receiver": receiver,
                "task_id": task_id,
                "content": content,
                "status": status,
            }
        )
        session.state = append_collaboration_message_to_state(state, message)
        return session

    @staticmethod
    def _build_reflector_failure_message(
        *,
        primary_agent_id: str,
        fallback_agent_id: Optional[str],
        primary_error: str,
        fallback_error: Optional[str],
        attempts_trace: List[Dict[str, Any]],
    ) -> str:
        details = {
            "error_code": "AGENT_NODE_RUNTIME_ERROR",
            "message": primary_error,
            "primary_agent_id": primary_agent_id,
            "fallback_agent_id": fallback_agent_id,
            "fallback_error": fallback_error,
            "recovery_trace": attempts_trace,
        }
        return "AGENT_NODE_RUNTIME_ERROR_DETAILS: " + json.dumps(details, ensure_ascii=False)

    def _resolve_reflector_retry_config(
        self,
        cfg: Dict[str, Any],
        *,
        global_ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        workflow_global = global_ctx.get("workflow_global_config") if isinstance(global_ctx, dict) else {}
        workflow_reflector = {}
        if isinstance(workflow_global, dict):
            reflector_candidate = workflow_global.get("reflector")
            if isinstance(reflector_candidate, dict):
                workflow_reflector = reflector_candidate
        settings_store = get_system_settings_store()
        default_retries = settings_store.get_setting(
            "workflowReflectorMaxRetries",
            getattr(settings, "workflow_reflector_max_retries", 0),
        )
        default_retry_interval = settings_store.get_setting(
            "workflowReflectorRetryIntervalSeconds",
            getattr(settings, "workflow_reflector_retry_interval_seconds", 1.0),
        )
        default_fallback_agent = settings_store.get_setting(
            "workflowReflectorFallbackAgentId",
            getattr(settings, "workflow_reflector_fallback_agent_id", ""),
        )
        max_retries = self._coerce_int(
            cfg.get(
                "reflector_max_retries",
                workflow_reflector.get("max_retries", default_retries),
            ),
            self._coerce_int(default_retries, 0),
        )
        max_retries = max(0, max_retries)
        retry_interval_raw = cfg.get(
            "reflector_retry_interval_seconds",
            workflow_reflector.get("retry_interval_seconds", default_retry_interval),
        )
        try:
            retry_interval_seconds = max(0.0, float(retry_interval_raw))
        except (TypeError, ValueError):
            retry_interval_seconds = 1.0
        fallback_agent_id = str(
            cfg.get(
                "reflector_fallback_agent_id",
                workflow_reflector.get("fallback_agent_id", default_fallback_agent),
            )
            or ""
        ).strip()
        return {
            "max_retries": max_retries,
            "retry_interval_seconds": retry_interval_seconds,
            "fallback_agent_id": fallback_agent_id or None,
        }

    def _resolve_execution_start_state(
        self, execution_id: str
    ) -> Tuple[WorkflowExecution, Optional[WorkflowExecution]]:
        latest = self.execution_repository.get_by_id(execution_id)
        if not latest:
            raise ValueError(f"Execution not found: {execution_id}")
        if latest.is_terminal():
            logger.info(
                f"[WorkflowRuntime] Skip execute for terminal execution: "
                f"{execution_id} state={latest.state.value}"
            )
            return latest, latest
        if latest.state == WorkflowExecutionState.RUNNING and latest.graph_instance_id:
            logger.info(
                f"[WorkflowRuntime] Skip duplicate execute for running execution: "
                f"{execution_id} instance={latest.graph_instance_id}"
            )
            return latest, latest
        return latest, None

    def _load_and_validate_version(self, execution: WorkflowExecution) -> WorkflowVersion:
        version_id = execution.version_id
        version = self.version_repository.get_version_by_id(version_id)
        if not version:
            raise ValueError(f"Version not found: {version_id}")

        trigger_type = str(execution.trigger_type or "manual").lower()
        allow_draft_for_manual_run = trigger_type in {"manual", "api", "debug"}
        if not version.can_execute():
            if not (version.state == WorkflowVersionState.DRAFT and allow_draft_for_manual_run):
                raise ValueError(f"Version cannot be executed: {version.state.value}")

        compatibility_errors = GraphRuntimeAdapter.validate_compatibility(version)
        if compatibility_errors:
            raise ValueError(f"Compatibility check failed: {'; '.join(compatibility_errors)}")
        return version

    async def _request_governance_slot(
        self, execution_id: str, workflow_id: str, version_id: str, version: WorkflowVersion
    ) -> None:
        request = ExecutionRequest(
            execution_id=execution_id,
            workflow_id=workflow_id,
            version_id=version_id,
            estimated_tokens=self._estimate_tokens(version),
        )
        result = await self.execution_manager.wait_for_execution(request)
        if not result.allowed:
            raise RuntimeError(f"Execution not allowed: {result.reason}")

        queued_at_dt = None
        if result.queued_at:
            try:
                queued_at_dt = datetime.fromisoformat(result.queued_at)
            except Exception:
                queued_at_dt = None
        self.execution_repository.update_queue_metrics(
            execution_id,
            queue_position=result.queue_position,
            queued_at=queued_at_dt,
            wait_duration_ms=result.wait_duration_ms,
        )

        await self._wait_distributed_running_slot(workflow_id, execution_id)

    def _start_execution_instance(
        self,
        execution_id: str,
        *,
        on_state_change: Optional[Callable[[WorkflowExecution], None]],
    ) -> tuple[WorkflowExecution, str]:
        running_execution = self.execution_repository.update_state(
            execution_id,
            WorkflowExecutionState.RUNNING
        )
        if running_execution is None:
            raise RuntimeError(f"Failed to mark execution as running: {execution_id}")
        current_execution = running_execution
        if on_state_change:
            on_state_change(current_execution)
        instance_id = current_execution.execution_id
        return current_execution, instance_id

    async def _bootstrap_scheduler_instance(
        self, execution: WorkflowExecution, version: WorkflowVersion, instance_id: str
    ) -> None:
        graph_def = GraphRuntimeAdapter.adapt(version)
        workspace_dir = str(
            Path("data/workflow_workspaces").joinpath(execution.execution_id).resolve()
        )
        Path(workspace_dir).mkdir(parents=True, exist_ok=True)
        base_gc = dict(execution.global_context or {})
        if not str(base_gc.get("correlation_id") or "").strip():
            base_gc["correlation_id"] = f"wfex_{execution.execution_id}"
        global_context = {
            "workflow_id": execution.workflow_id,
            "version_id": execution.version_id,
            "execution_id": execution.execution_id,
            "input_data": execution.input_data or {},
            "workflow_global_config": version.dag.global_config or {},
            "workspace": workspace_dir,
            **base_gc,
        }
        # 将归一化后的 correlation_id 写回 DB，使 GET execution / 前端与调度时 global_context 一致
        persisted_gc = {**(execution.global_context or {}), "correlation_id": global_context["correlation_id"]}
        self.execution_repository.update_global_context(execution.execution_id, persisted_gc)

        self.execution_repository.update_graph_instance_id(
            execution.execution_id,
            instance_id
        )
        await self.scheduler.start_instance(
            graph_def=graph_def,
            instance_id=instance_id,
            global_context=global_context
        )

    async def _await_or_background_execution(
        self,
        *,
        execution: WorkflowExecution,
        execution_id: str,
        instance_id: str,
        wait_for_completion: bool,
        wait_timeout_seconds: Optional[float],
        on_state_change: Optional[Callable[[WorkflowExecution], None]],
    ) -> WorkflowExecution:
        if wait_for_completion:
            final_state = await self.scheduler.wait_for_completion(
                instance_id=instance_id,
                timeout=cast(float, wait_timeout_seconds),
            )
            final_state_value = final_state.value if hasattr(final_state, "value") else str(final_state)
            if wait_timeout_seconds and final_state_value == "running":
                timeout_msg = (
                    f"WORKFLOW_WAIT_TIMEOUT: wait={int(wait_timeout_seconds)}s exceeded, "
                    f"execution still running (execution_id={execution_id})"
                )
                timeout_execution = self.execution_repository.update_state(
                    execution_id,
                    WorkflowExecutionState.RUNNING,
                    error_message=timeout_msg,
                    error_details={
                        "code": "WORKFLOW_WAIT_TIMEOUT",
                        "message": timeout_msg,
                        "wait_timeout_seconds": wait_timeout_seconds,
                        "execution_id": execution_id,
                    },
                )
                if timeout_execution is None:
                    raise RuntimeError(f"Failed to update timeout state: {execution_id}")
                execution = timeout_execution
                logger.warning(f"[WorkflowRuntime] {timeout_msg}")
                if on_state_change:
                    on_state_change(execution)
                return execution
            return await self._handle_completion(
                execution_id,
                instance_id,
                on_state_change
            )

        task = asyncio.create_task(
            self._execute_async(execution_id, instance_id, on_state_change)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return execution
    
    async def execute(
        self,
        execution: WorkflowExecution,
        wait_for_completion: bool = True,
        wait_timeout_seconds: Optional[float] = None,
        on_state_change: Optional[Callable[[WorkflowExecution], None]] = None
    ) -> WorkflowExecution:
        """
        执行 Workflow
        
        Args:
            execution: 执行实例
            wait_for_completion: 是否等待完成
            wait_timeout_seconds: wait_for_completion=True 时的等待超时（秒），None 表示不额外超时
            on_state_change: 状态变更回调
        
        Returns:
            执行实例（最终状态）
        """
        execution_id = execution.execution_id
        workflow_id = execution.workflow_id
        version_id = execution.version_id
        
        try:
            execution, skip_execution = self._resolve_execution_start_state(execution_id)
            if skip_execution is not None:
                return skip_execution
            workflow_id = execution.workflow_id
            version_id = execution.version_id

            version = self._load_and_validate_version(execution)

            # 2.5 审批门控：若存在 approval 节点且未审批，则创建审批任务并暂停执行
            if self._require_approval_before_start(execution, version):
                paused = self.execution_repository.update_state(
                    execution.execution_id,
                    WorkflowExecutionState.PAUSED,
                    error_message="Awaiting approval",
                    error_details={"code": "WORKFLOW_APPROVAL_PENDING"},
                )
                if on_state_change and paused:
                    on_state_change(paused)
                return paused or execution
            
            await self._request_governance_slot(execution_id, workflow_id, version_id, version)
            execution, instance_id = self._start_execution_instance(
                execution_id, on_state_change=on_state_change
            )
            await self._bootstrap_scheduler_instance(execution, version, instance_id)
            return await self._await_or_background_execution(
                execution=execution,
                execution_id=execution_id,
                instance_id=instance_id,
                wait_for_completion=wait_for_completion,
                wait_timeout_seconds=wait_timeout_seconds,
                on_state_change=on_state_change,
            )
            
        except Exception as e:
            logger.error(f"[WorkflowRuntime] Execution failed: {execution_id} - {e}")
            latest_execution = self.execution_repository.get_by_id(execution_id) or execution
            failure_details = self._build_global_failure_details(
                latest_execution,
                error_message=str(e),
                exception_type=type(e).__name__,
            )
            
            # 标记执行失败
            failed_execution = self.execution_repository.update_state(
                execution_id,
                WorkflowExecutionState.FAILED,
                error_message=str(e),
                error_details=failure_details,
            )
            if failed_execution is None:
                latest = self.execution_repository.get_by_id(execution_id)
                if latest is None:
                    raise RuntimeError(f"Execution not found after failure: {execution_id}") from e
                failed_execution = latest
            execution = failed_execution
            
            # 释放治理资源
            self.execution_manager.complete_execution(execution_id, workflow_id)
            
            if on_state_change:
                on_state_change(execution)
            
            return execution

    async def _wait_distributed_running_slot(self, workflow_id: str, execution_id: str) -> None:
        if not bool(getattr(settings, "workflow_distributed_running_limit_enabled", True)):
            return
        limit = max(1, int(getattr(settings, "workflow_distributed_running_limit_per_workflow", 3) or 3))
        timeout_s = float(getattr(settings, "workflow_distributed_running_limit_wait_seconds", 15.0) or 15.0)
        fail_open = bool(getattr(settings, "workflow_distributed_running_limit_fail_open", True))
        stale_seconds = max(60, int(getattr(settings, "workflow_distributed_running_stale_seconds", 1800) or 1800))
        auto_reconcile_stale = bool(getattr(settings, "workflow_distributed_running_auto_reconcile_stale", True))
        deadline = datetime.now(UTC).timestamp() + max(0.0, timeout_s)
        while True:
            now = datetime.now(UTC)
            stale_cutoff = now - timedelta(seconds=stale_seconds)
            running_execs = self.execution_repository.get_running_executions(workflow_id)
            active_running, stale_running = self._partition_running_executions(
                running_execs,
                current_execution_id=execution_id,
                stale_cutoff=stale_cutoff,
            )

            if stale_running and auto_reconcile_stale:
                self._reconcile_stale_running_executions(
                    workflow_id=workflow_id,
                    stale_running=stale_running,
                    stale_seconds=stale_seconds,
                )

            running = len(active_running)
            if running < limit:
                return
            if datetime.now(UTC).timestamp() >= deadline:
                if fail_open:
                    logger.warning(
                        "[WorkflowRuntime] Distributed running limit wait timeout, fail-open continue: "
                        f"workflow_id={workflow_id} execution_id={execution_id} "
                        f"running={running} limit={limit} stale_ignored={len(stale_running)}"
                    )
                    return
                raise RuntimeError(
                    f"DISTRIBUTED_CONCURRENCY_LIMIT_REACHED: workflow_id={workflow_id} "
                    f"running={running} limit={limit} "
                    f"stale_ignored={len(stale_running)}"
                )
            await asyncio.sleep(0.2)

    def _partition_running_executions(
        self,
        running_execs: List[WorkflowExecution],
        *,
        current_execution_id: str,
        stale_cutoff: datetime,
    ) -> tuple[List[WorkflowExecution], List[WorkflowExecution]]:
        active_running: List[WorkflowExecution] = []
        stale_running: List[WorkflowExecution] = []
        for ex in running_execs:
            if ex.execution_id == current_execution_id:
                continue
            started = ex.started_at or ex.created_at
            if started and started < stale_cutoff:
                stale_running.append(ex)
                continue
            active_running.append(ex)
        return active_running, stale_running

    def _reconcile_stale_running_executions(
        self,
        *,
        workflow_id: str,
        stale_running: List[WorkflowExecution],
        stale_seconds: int,
    ) -> None:
        for ex in stale_running:
            try:
                msg = (
                    "AUTO_RECONCILED_STALE_RUNNING: "
                    f"started_at={ex.started_at.isoformat() if ex.started_at else 'unknown'} "
                    f"older_than={stale_seconds}s"
                )
                self.execution_repository.update_state(
                    ex.execution_id,
                    WorkflowExecutionState.FAILED,
                    error_message=msg,
                    error_details={"code": "STALE_RUNNING_RECONCILED"},
                )
                logger.warning(
                    f"[WorkflowRuntime] Reconciled stale running execution: "
                    f"workflow_id={workflow_id} execution_id={ex.execution_id}"
                )
            except Exception as e:
                logger.warning(
                    f"[WorkflowRuntime] Failed to reconcile stale running execution: "
                    f"execution_id={ex.execution_id} error={e}"
                )
    
    async def _execute_async(
        self,
        execution_id: str,
        instance_id: str,
        on_state_change: Optional[Callable[[WorkflowExecution], None]]
    ) -> None:
        """异步执行"""
        try:
            # 等待完成
            await self.scheduler.wait_for_completion(
                instance_id=instance_id,
                timeout=3600
            )
            await self._handle_completion(execution_id, instance_id, on_state_change)
        except Exception as e:
            logger.error(f"[WorkflowRuntime] Async execution failed: {execution_id} - {e}")
            
            execution = self.execution_repository.update_state(
                execution_id,
                WorkflowExecutionState.FAILED,
                error_message=str(e)
            )
            
            if on_state_change and execution is not None:
                on_state_change(execution)
    
    async def _handle_completion(
        self,
        execution_id: str,
        instance_id: str,
        on_state_change: Optional[Callable[[WorkflowExecution], None]]
    ) -> WorkflowExecution:
        """处理执行完成"""
        result = await GraphRuntimeAdapter.extract_execution_result_from_kernel(
            instance_id,
            self.scheduler.db
        )
        final_state = self._map_kernel_state_to_workflow_state(result.get("state", "failed"))
        self._persist_completion_result(execution_id, result)
        execution = self.execution_repository.update_state(
            execution_id,
            final_state
        )
        if execution is None:
            latest = self.execution_repository.get_by_id(execution_id)
            if latest is None:
                raise RuntimeError(f"Execution not found while handling completion: {execution_id}")
            execution = latest
        
        # 释放治理资源
        execution_id_val = execution.execution_id
        workflow_id = execution.workflow_id
        tokens_consumed = result.get("tokens_consumed", 0)
        
        self.execution_manager.complete_execution(
            execution_id_val,
            workflow_id,
            tokens_consumed
        )
        
        if on_state_change:
            on_state_change(execution)

        self._record_runtime_tool_sequence_learning(execution_id, result)
        
        logger.info(f"[WorkflowRuntime] Execution completed: {execution_id} - {final_state.value}")
        
        return execution

    def _record_runtime_tool_sequence_learning(
        self,
        execution_id: str,
        result: Dict[str, Any],
    ) -> None:
        """执行完成后按真实节点执行结果提取工具序列，更新推荐学习数据。"""
        try:
            execution = self.execution_repository.get_by_id(execution_id)
            if not execution:
                return
            version = self.version_repository.get_version_by_id(execution.version_id)
            if not version or not version.dag or not version.dag.nodes:
                return
            tool_name_by_node: Dict[str, str] = {}
            for node in version.dag.nodes:
                cfg = node.config or {}
                if node.type != "tool":
                    continue
                tool_name = str(cfg.get("tool_name") or cfg.get("tool_id") or "").strip()
                if tool_name:
                    tool_name_by_node[node.id] = tool_name
            if not tool_name_by_node:
                return

            node_states = result.get("node_states") if isinstance(result, dict) else []
            if not isinstance(node_states, list):
                return
            successful_tool_states: List[Dict[str, Any]] = []
            for st in node_states:
                if not isinstance(st, dict):
                    continue
                node_id = str(st.get("node_id") or "").strip()
                state = str(st.get("state") or "").strip().lower()
                if node_id not in tool_name_by_node:
                    continue
                if state not in {"success", "completed"}:
                    continue
                successful_tool_states.append(st)
            if not successful_tool_states:
                return
            successful_tool_states.sort(key=lambda x: str(x.get("started_at") or ""))
            tool_sequence = [
                tool_name_by_node[str(st.get("node_id"))]
                for st in successful_tool_states
                if str(st.get("node_id")) in tool_name_by_node
            ]
            if not tool_sequence:
                return
            recommender = WorkflowToolCompositionRecommender()
            recommender.record_runtime_sequence(
                workflow_id=execution.workflow_id,
                user_id=str(execution.triggered_by or "system"),
                tool_sequence=tool_sequence,
            )
        except Exception as e:
            logger.warning(
                "[WorkflowRuntime] Failed to record runtime tool sequence learning: %s",
                e,
            )

    @staticmethod
    def _map_kernel_state_to_workflow_state(kernel_state: Any) -> WorkflowExecutionState:
        state = str(kernel_state or "failed").lower()
        if state == "completed":
            return WorkflowExecutionState.COMPLETED
        if state == "cancelled":
            return WorkflowExecutionState.CANCELLED
        if state == "failed":
            return WorkflowExecutionState.FAILED
        return WorkflowExecutionState.FAILED

    def _persist_completion_result(self, execution_id: str, result: Dict[str, Any]) -> None:
        output_data = self._build_completion_output_data(result)
        if output_data:
            self.execution_repository.update_output(execution_id, output_data)

        normalized_nodes = self._normalize_completion_node_states(result.get("node_states", []))
        if normalized_nodes:
            self.execution_repository.update_node_states(execution_id, normalized_nodes)

    @staticmethod
    def _build_completion_output_data(result: Dict[str, Any]) -> Dict[str, Any]:
        output_data_raw = result.get("output_data", {})
        output_data = output_data_raw if isinstance(output_data_raw, dict) else {}
        agent_summaries = result.get("agent_summaries", [])
        if isinstance(agent_summaries, list) and agent_summaries:
            return {**output_data, "agent_summaries": agent_summaries}
        return output_data

    @staticmethod
    def _normalize_completion_node_states(raw_node_states: Any) -> List[WorkflowExecutionNode]:
        if not isinstance(raw_node_states, list) or not raw_node_states:
            return []
        normalized_nodes: List[WorkflowExecutionNode] = []
        valid_states = {s.value for s in WorkflowExecutionNodeState}
        for item in raw_node_states:
            normalized = WorkflowRuntime._normalize_single_node_state_item(item, valid_states)
            if normalized is not None:
                normalized_nodes.append(normalized)
        return normalized_nodes

    @staticmethod
    def _normalize_single_node_state_item(
        item: Any, valid_states: set[str]
    ) -> Optional[WorkflowExecutionNode]:
        if not isinstance(item, dict):
            return None
        node_id = str(item.get("node_id") or "").strip()
        if not node_id:
            return None
        state_raw = WorkflowRuntime._normalize_node_state_value(item.get("state"), valid_states)
        try:
            return WorkflowExecutionNode(
                node_id=node_id,
                state=WorkflowExecutionNodeState(state_raw),
                input_data=item.get("input_data") or {},
                output_data=item.get("output_data") or {},
                error_message=item.get("error_message"),
                error_details=item.get("error_details"),
                started_at=item.get("started_at"),
                finished_at=item.get("finished_at"),
                retry_count=int(item.get("retry_count") or 0),
            )
        except Exception:
            return None

    @staticmethod
    def _normalize_node_state_value(raw_state: Any, valid_states: set[str]) -> str:
        state_raw = str(raw_state or "pending").lower()
        if state_raw == "retrying":
            state_raw = "running"
        if state_raw not in valid_states:
            return "pending"
        return state_raw
    
    async def cancel(self, execution_id: str) -> bool:
        """取消执行"""
        execution = self.execution_repository.get_by_id(execution_id)
        if not execution:
            return False
        
        if not execution.can_cancel():
            return False
        
        # 取消 governance
        self.execution_manager.cancel_execution(
            execution_id,
            execution.workflow_id
        )

        # 先持久化取消状态，作为跨进程统一取消信号（让后续执行路径可尽快感知）。
        await self._update_state_with_retry(
            execution_id,
            WorkflowExecutionState.CANCELLED,
        )
        
        # 如果有 GraphInstance，取消它
        if execution.graph_instance_id:
            try:
                cancelled = await self.scheduler.cancel_instance(
                    execution.graph_instance_id,
                    reason="cancelled_by_user",
                )
                if not cancelled:
                    logger.warning(
                        f"[WorkflowRuntime] Graph instance not found for cancel: {execution.graph_instance_id}"
                    )
            except Exception as e:
                logger.warning(f"[WorkflowRuntime] Failed to cancel graph instance: {e}")
        
        logger.info(f"[WorkflowRuntime] Cancelled execution: {execution_id}")
        return True

    async def _update_state_with_retry(
        self,
        execution_id: str,
        state: WorkflowExecutionState,
        *,
        retries: int = 6,
        base_delay_seconds: float = 0.1,
    ) -> Optional[WorkflowExecution]:
        last_err: Optional[Exception] = None
        for i in range(retries):
            try:
                return self.execution_repository.update_state(execution_id, state)
            except OperationalError as e:
                last_err = e
                msg = str(e).lower()
                if "database is locked" not in msg:
                    raise
                delay = base_delay_seconds * (2 ** i)
                logger.warning(
                    f"[WorkflowRuntime] update_state retry due to DB lock: "
                    f"execution_id={execution_id} state={state.value} attempt={i + 1}/{retries} delay={delay:.2f}s"
                )
                await asyncio.sleep(delay)
        if last_err:
            raise last_err
        return None
    
    def get_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """获取执行状态"""
        execution = self.execution_repository.get_by_id(execution_id)
        if not execution:
            return None
        
        # 获取 governance 状态
        governance_status = self.execution_manager.get_workflow_status(
            execution.workflow_id
        )
        
        return {
            "execution": execution.model_dump(),
            "governance": governance_status
        }
    
    def _estimate_tokens(self, version: WorkflowVersion) -> int:
        """估计 Token 消耗"""
        # 简化估计：每个节点约 1000 tokens
        return len(version.dag.nodes) * 1000

    def _require_approval_before_start(self, execution: WorkflowExecution, version: WorkflowVersion) -> bool:
        global_ctx = dict(execution.global_context or {})
        decisions = global_ctx.get("approval_decisions") or {}
        if not isinstance(decisions, dict):
            decisions = {}
        requested_by = str(execution.triggered_by or "system")

        unapproved_nodes = self._collect_unapproved_approval_nodes(version, decisions)
        if not unapproved_nodes:
            return False

        pending_created = False
        for node_id, cfg in unapproved_nodes:
            if self._create_pending_approval_task_if_missing(execution, node_id, cfg, requested_by):
                pending_created = True

        has_pending = len(self.approval_repository.list_pending_by_execution(execution.execution_id)) > 0
        return pending_created or has_pending

    def _collect_unapproved_approval_nodes(
        self, version: WorkflowVersion, decisions: Dict[str, Any]
    ) -> List[tuple[str, Dict[str, Any]]]:
        nodes: List[tuple[str, Dict[str, Any]]] = []
        for node in version.dag.nodes:
            cfg = node.config or {}
            if self._is_unapproved_approval_node(node, cfg, decisions):
                nodes.append((node.id, cfg))
        return nodes

    @staticmethod
    def _is_unapproved_approval_node(node: Any, cfg: Dict[str, Any], decisions: Dict[str, Any]) -> bool:
        node_type = str(cfg.get("workflow_node_type") or node.type or "").strip().lower()
        if node_type != "approval":
            return False
        return str(decisions.get(node.id) or "").lower() != "approved"

    def _create_pending_approval_task_if_missing(
        self,
        execution: WorkflowExecution,
        node_id: str,
        cfg: Dict[str, Any],
        requested_by: str,
    ) -> bool:
        existing = self.approval_repository.get_pending_by_execution_node(execution.execution_id, node_id)
        if existing:
            return False
        self.approval_repository.create_task(
            execution_id=execution.execution_id,
            workflow_id=execution.workflow_id,
            node_id=node_id,
            title=str(cfg.get("title") or f"Approve node {node_id}")[:256],
            reason=str(cfg.get("reason") or "Workflow requires approval before execution"),
            payload={"node_config": cfg},
            requested_by=requested_by,
            expires_in_seconds=cfg.get("expires_in_seconds"),
        )
        return True
    
    def _count_tokens(self, _result: Dict[str, Any]) -> int:
        """计算实际 Token 消耗"""
        # 简化计算，实际应该从 execution_kernel 获取
        return 0
