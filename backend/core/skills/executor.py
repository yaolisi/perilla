"""
Skill v2 Executor: 统一执行入口。

设计原则：
- Executor 不负责发现（由 Registry 负责）
- 统一调用，不能直接调用 Skill 内部函数
- 自动捕获异常
- 填充 metrics
- 记录 latency
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Type, cast

import jsonschema  # type: ignore[import-untyped]
from jsonschema import ValidationError as JSONSchemaValidationError  # type: ignore[import-untyped]
from jinja2 import Template, UndefinedError

from log import logger, log_structured
from core.skills.contract import (
    ExecutionMetrics,
    SkillExecutionRequest,
    SkillExecutionResponse,
)
from core.skills.models import SkillDefinition
from core.skills.registry import SkillRegistry


class SkillExecutorError(Exception):
    """Skill 执行错误基类"""
    pass


class SkillNotFoundError(SkillExecutorError):
    """Skill 未找到"""
    pass


class SkillExecutionError(SkillExecutorError):
    """Skill 执行失败"""
    pass


class SchemaValidationError(SkillExecutorError):
    """Schema 校验失败"""
    pass


class SkillExecutor:
    """
    Skill 执行器
    
    所有 Skill 执行必须通过统一入口：
    ```python
    response = SkillExecutor.execute(request)
    ```
    """
    
    # 注册的执行器映射 {skill_id: executor_class}
    # 未来扩展：每个 Skill 可以有自定义的执行器
    _executors: Dict[str, Type["BaseSkillExecutor"]] = {}
    
    @classmethod
    def register_executor(cls, skill_id: str, executor_class: Type["BaseSkillExecutor"]) -> None:
        """注册 Skill 执行器"""
        cls._executors[skill_id] = executor_class
        logger.info(f"[SkillExecutor] Registered executor for {skill_id}")
    
    @classmethod
    async def execute(cls, request: SkillExecutionRequest) -> SkillExecutionResponse:
        """
        统一执行入口
        
        流程：
        1. 验证请求
        2. 查找 Skill 定义
        3. Schema 校验
        4. 执行技能
        5. 捕获异常和指标
        6. 返回响应
        
        Args:
            request: 执行请求
        
        Returns:
            执行响应
        """
        metrics = ExecutionMetrics()
        
        try:
            # 1. 验证请求
            validation_error = request.validate()
            if validation_error:
                return SkillExecutionResponse.failure(
                    error_code="INVALID_REQUEST",
                    error_message=validation_error,
                    trace_id=request.trace_id,
                    metrics=metrics.to_dict()
                )
            
            # 2. 查找 Skill 定义
            definition = cls._find_skill(request.skill_id, request.version)
            if not definition:
                return SkillExecutionResponse.failure(
                    error_code="SKILL_NOT_FOUND",
                    error_message=f"Skill not found: {request.skill_id}@{request.version or 'latest'}",
                    trace_id=request.trace_id,
                    skill_id=request.skill_id,
                    version=request.version or "",
                    metrics=metrics.to_dict()
                )
            
            # 3. Schema 校验
            try:
                cls._validate_input(definition, request.input)
            except SchemaValidationError as e:
                return SkillExecutionResponse.failure(
                    error_code="SCHEMA_VALIDATION_ERROR",
                    error_message=str(e),
                    trace_id=request.trace_id,
                    skill_id=definition.id,
                    version=definition.version,
                    metrics=metrics.to_dict()
                )
            
            # 4. 执行技能
            executor_class = cls._executors.get(definition.id, DefaultSkillExecutor)
            executor = executor_class()
            
            result = await executor.execute(definition, request, metrics)

            # Tool/Composite 等执行器可能以 {"error": "..."} 返回业务失败，
            # 这里统一转为 error 响应，避免被误标记为 success。
            if isinstance(result, dict) and result.get("error"):
                metrics.finalize()
                return SkillExecutionResponse.failure(
                    error_code="EXECUTION_ERROR",
                    error_message=str(result.get("error")),
                    trace_id=request.trace_id,
                    skill_id=definition.id,
                    version=definition.version,
                    metrics=metrics.to_dict(),
                )
            
            # 5. 成功返回
            metrics.finalize()
            try:
                uid = (request.metadata or {}).get("user_id")
                if uid:
                    from core.skills.usage_store import record_skill_use

                    record_skill_use(str(uid), definition.id)
            except Exception:
                pass
            return SkillExecutionResponse.success(
                output=result,
                trace_id=request.trace_id,
                skill_id=definition.id,
                version=definition.version,
                metrics=metrics.to_dict()
            )
            
        except Exception as e:
            # 5. 异常处理
            metrics.finalize()
            logger.exception(f"[SkillExecutor] Execution failed: {e}")
            
            return SkillExecutionResponse.failure(
                error_code="EXECUTION_ERROR",
                error_message=str(e),
                trace_id=request.trace_id,
                skill_id=request.skill_id,
                version=request.version or "",
                metrics=metrics.to_dict()
            )
    
    @staticmethod
    def _find_skill(skill_id: str, version: Optional[str]) -> Optional[SkillDefinition]:
        """查找 Skill 定义"""
        return cast(Optional[SkillDefinition], SkillRegistry.get(skill_id, version))
    
    @staticmethod
    def _validate_input(definition: SkillDefinition, input_data: Dict[str, Any]) -> None:
        """
        Schema 校验
        
        使用 jsonschema 进行完整的 JSON Schema 校验
        """
        if not definition.input_schema:
            return
        
        try:
            jsonschema.validate(instance=input_data, schema=definition.input_schema)
        except JSONSchemaValidationError as e:
            # 构建友好的错误信息
            error_path = "/".join(str(p) for p in e.path) if e.path else "root"
            raise SchemaValidationError(
                f"Schema validation failed at '{error_path}': {e.message}"
            ) from e


class BaseSkillExecutor:
    """Skill 执行器基类"""
    
    async def execute(
        self,
        definition: SkillDefinition,
        request: SkillExecutionRequest,
        metrics: ExecutionMetrics
    ) -> Dict[str, Any]:
        """
        执行 Skill
        
        Args:
            definition: Skill 定义
            request: 执行请求
            metrics: 指标收集器
        
        Returns:
            执行结果（必须符合 output_schema）
        """
        raise NotImplementedError("Subclasses must implement execute()")


class DefaultSkillExecutor(BaseSkillExecutor):
    """
    默认执行器（兼容现有 Skills）
    
    支持以下 Skill 类型：
    - prompt: 渲染模板并返回
    - tool: 调用对应的 Tool
    - composite: 先渲染 prompt，再调用 tool
    - workflow: 执行工作流步骤序列
    """
    
    async def execute(
        self,
        definition: SkillDefinition,
        request: SkillExecutionRequest,
        metrics: ExecutionMetrics
    ) -> Dict[str, Any]:
        """
        执行 Skill
        
        根据 Skill 类型路由到对应的执行逻辑
        """
        logger.info(
            f"[DefaultSkillExecutor] Executing {definition.id}@{definition.version} (type={definition.type})"
        )
        
        skill_type = definition.type
        
        if skill_type == "prompt":
            return await self._execute_prompt(definition, request, metrics)
        elif skill_type == "tool":
            return await self._execute_tool(definition, request, metrics)
        elif skill_type == "composite":
            return await self._execute_composite(definition, request, metrics)
        elif skill_type == "workflow":
            return await self._execute_workflow(definition, request, metrics)
        else:
            # 默认使用 prompt 类型处理
            logger.warning(f"[DefaultSkillExecutor] Unknown skill type '{skill_type}', falling back to prompt")
            return await self._execute_prompt(definition, request, metrics)
    
    async def _execute_prompt(
        self,
        definition: SkillDefinition,
        request: SkillExecutionRequest,
        metrics: ExecutionMetrics
    ) -> Dict[str, Any]:
        """
        执行 Prompt 类型 Skill
        
        渲染 prompt_template 并返回结果
        """
        # 获取 prompt_template
        prompt_template = definition.definition.get("prompt_template", "")
        
        if not prompt_template:
            logger.warning(f"[DefaultSkillExecutor] No prompt_template found for skill {definition.id}")
            return {
                "type": "prompt",
                "output": {
                    "rendered_prompt": f"Skill {definition.id} executed with inputs: {request.input}",
                    "inputs": request.input
                },
                "skill_id": definition.id,
                "version": definition.version
            }
        
        # 渲染模板
        try:
            rendered_prompt = self._render_template(prompt_template, request.input)
            return {
                "type": "prompt",
                "output": {
                    "rendered_prompt": rendered_prompt,
                    "inputs": request.input,
                    "template_used": True
                },
                "skill_id": definition.id,
                "version": definition.version
            }
        except Exception as e:
            logger.error(f"[DefaultSkillExecutor] Template rendering failed: {e}")
            return {
                "type": "prompt",
                "output": {
                    "rendered_prompt": prompt_template,  # 返回原始模板
                    "inputs": request.input,
                    "template_used": False,
                    "render_error": str(e)
                },
                "skill_id": definition.id,
                "version": definition.version
            }
    
    def _render_template(self, template: str, variables: Dict[str, Any]) -> str:
        """
        渲染 Jinja2 模板
        
        支持：
        - {{ variable }} 基本变量替换
        - {{ user.name }} 嵌套属性访问
        - {{ max_depth|default(3) }} 过滤器
        - {{ items|length }} 内置过滤器
        - {% if condition %}...{% endif %} 条件判断
        - {% for item in items %}...{% endfor %} 循环
        
        Args:
            template: Jinja2 模板字符串
            variables: 变量字典
            
        Returns:
            渲染后的字符串
        """
        try:
            # 使用 Jinja2 引擎
            jinja_template = Template(template)
            return cast(str, jinja_template.render(**variables))
        except UndefinedError as e:
            # 变量未定义，返回原始模板并记录警告
            logger.warning(f"[DefaultSkillExecutor] Template variable undefined: {e}")
            return template
        except Exception as e:
            # 其他错误，返回原始模板并记录错误
            logger.error(f"[DefaultSkillExecutor] Template rendering failed: {e}")
            return template
    
    def _build_tool_inputs_from_definition(
        self,
        definition: SkillDefinition,
        request: SkillExecutionRequest,
    ) -> Dict[str, Any]:
        """tool_params / tool_args_mapping / request.input 合并（与内置 Tool 路径一致）。"""
        tool_params = definition.definition.get("tool_params", {})
        tool_args_mapping = definition.definition.get("tool_args_mapping", {})
        tool_input: Dict[str, Any] = {}
        for key, value_template in tool_params.items():
            if isinstance(value_template, str) and "{{" in value_template:
                try:
                    jinja_template = Template(value_template)
                    rendered_value = jinja_template.render(**request.input)
                    try:
                        if rendered_value.isdigit():
                            tool_input[key] = int(rendered_value)
                        elif rendered_value.replace(".", "", 1).isdigit():
                            tool_input[key] = float(rendered_value)
                        elif rendered_value.lower() in ("true", "false"):
                            tool_input[key] = rendered_value.lower() == "true"
                        else:
                            tool_input[key] = rendered_value
                    except (ValueError, AttributeError):
                        tool_input[key] = rendered_value
                except UndefinedError:
                    tool_input[key] = None
            else:
                tool_input[key] = value_template
        for target_key, source_key in tool_args_mapping.items():
            if source_key in request.input:
                tool_input[target_key] = request.input[source_key]
        tool_input.update(request.input)
        logger.debug(f"[DefaultSkillExecutor] Tool input built: {tool_input}")
        return tool_input

    async def _execute_mcp_stdio(
        self,
        definition: SkillDefinition,
        request: SkillExecutionRequest,
        _metrics: ExecutionMetrics,
    ) -> Dict[str, Any]:
        """MCP stdio Server：tools/call（definition.kind=mcp_stdio）。"""
        from core.mcp.client import MCPStdioClient
        from core.mcp.persistence import get_mcp_server, normalize_mcp_tenant_id

        server_id = (definition.definition.get("server_config_id") or "").strip()
        mcp_tool = (definition.definition.get("tool_name") or "").strip()
        if not server_id or not mcp_tool:
            log_structured(
                "Skills",
                "mcp_skill_invoke_blocked",
                level="warning",
                reason="missing_server_or_tool_name",
                skill_id=definition.id,
                trace_id=request.trace_id or "",
                caller_id=request.caller_id or "",
            )
            return {
                "type": "tool",
                "output": None,
                "error": "MCP skill missing server_config_id or tool_name",
                "skill_id": definition.id,
                "version": definition.version,
            }
        request_had_tenant = bool((str(request.tenant_id).strip() if request.tenant_id else ""))
        eff_tid = normalize_mcp_tenant_id(request.tenant_id)
        server = get_mcp_server(server_id, tenant_id=eff_tid)
        if not server:
            log_structured(
                "Skills",
                "mcp_skill_invoke_blocked",
                level="warning",
                reason="mcp_server_not_found",
                tenant_id=eff_tid,
                tenant_scoped=request_had_tenant,
                server_config_id=server_id,
                mcp_tool=mcp_tool,
                skill_id=definition.id,
                trace_id=request.trace_id or "",
                caller_id=request.caller_id or "",
            )
            return {
                "type": "tool",
                "output": None,
                "error": f"MCP server not found: {server_id}",
                "skill_id": definition.id,
                "version": definition.version,
            }
        if not server.get("enabled", True):
            log_structured(
                "Skills",
                "mcp_skill_invoke_blocked",
                level="warning",
                reason="mcp_server_disabled",
                tenant_id=eff_tid,
                tenant_scoped=request_had_tenant,
                server_config_id=server_id,
                skill_id=definition.id,
                trace_id=request.trace_id or "",
                caller_id=request.caller_id or "",
            )
            return {
                "type": "tool",
                "output": None,
                "error": f"MCP server disabled: {server_id}",
                "skill_id": definition.id,
                "version": definition.version,
            }
        transport = (server.get("transport") or "stdio").strip().lower()
        env = server.get("env") or {}
        args = self._build_tool_inputs_from_definition(definition, request)
        if transport == "http":
            from core.mcp.http_client import create_mcp_http_client
            from core.system.runtime_settings import get_mcp_http_emit_server_push_events

            base_url = (server.get("base_url") or "").strip()
            if not base_url:
                log_structured(
                    "Skills",
                    "mcp_skill_invoke_blocked",
                    level="warning",
                    reason="mcp_http_missing_base_url",
                    tenant_id=eff_tid,
                    tenant_scoped=request_had_tenant,
                    server_config_id=server_id,
                    skill_id=definition.id,
                    trace_id=request.trace_id or "",
                    caller_id=request.caller_id or "",
                )
                return {
                    "type": "tool",
                    "output": None,
                    "error": "MCP HTTP server missing base_url",
                    "skill_id": definition.id,
                    "version": definition.version,
                }
            client = await create_mcp_http_client(
                base_url,
                headers=env if env else None,
                request_timeout=120.0,
                emit_server_push_events=get_mcp_http_emit_server_push_events(),
            )
            kind = "mcp_http"
        else:
            command = server.get("command") or []
            if not command:
                log_structured(
                    "Skills",
                    "mcp_skill_invoke_blocked",
                    level="warning",
                    reason="mcp_stdio_command_empty",
                    tenant_id=eff_tid,
                    tenant_scoped=request_had_tenant,
                    server_config_id=server_id,
                    skill_id=definition.id,
                    trace_id=request.trace_id or "",
                    caller_id=request.caller_id or "",
                )
                return {
                    "type": "tool",
                    "output": None,
                    "error": "MCP server command empty",
                    "skill_id": definition.id,
                    "version": definition.version,
                }
            cwd = (server.get("cwd") or "").strip() or None
            client = MCPStdioClient(
                list(command),
                cwd=cwd,
                env=env if env else None,
                request_timeout=120.0,
            )
            kind = "mcp_stdio"
        log_structured(
            "Skills",
            "mcp_skill_invoke_start",
            tenant_id=eff_tid,
            tenant_scoped=request_had_tenant,
            server_config_id=server_id,
            mcp_tool=mcp_tool,
            skill_id=definition.id,
            trace_id=request.trace_id or "",
            caller_id=request.caller_id or "",
            transport=transport,
            kind=kind,
        )
        try:
            if transport != "http":
                await client.connect()
            raw = await client.call_tool(mcp_tool, args)
            log_structured(
                "Skills",
                "mcp_skill_invoke_success",
                tenant_id=eff_tid,
                tenant_scoped=request_had_tenant,
                server_config_id=server_id,
                mcp_tool=mcp_tool,
                skill_id=definition.id,
                trace_id=request.trace_id or "",
                caller_id=request.caller_id or "",
                transport=transport,
                kind=kind,
            )
            return {
                "type": "tool",
                "output": raw,
                "skill_id": definition.id,
                "version": definition.version,
                "tool_name": mcp_tool,
                "kind": kind,
            }
        except Exception as e:
            logger.exception("[DefaultSkillExecutor] MCP tool execution failed: %s", e)
            log_structured(
                "Skills",
                "mcp_skill_invoke_exception",
                level="error",
                tenant_id=eff_tid,
                tenant_scoped=request_had_tenant,
                server_config_id=server_id,
                mcp_tool=mcp_tool,
                skill_id=definition.id,
                trace_id=request.trace_id or "",
                caller_id=request.caller_id or "",
                transport=transport,
                kind=kind,
                error_type=type(e).__name__,
                error_message=str(e)[:500],
            )
            return {
                "type": "tool",
                "output": None,
                "error": str(e),
                "skill_id": definition.id,
                "version": definition.version,
                "tool_name": mcp_tool,
                "kind": kind,
            }
        finally:
            await client.close()

    async def _execute_tool(
        self,
        definition: SkillDefinition,
        request: SkillExecutionRequest,
        metrics: ExecutionMetrics
    ) -> Dict[str, Any]:
        """
        执行 Tool 类型 Skill
        
        调用对应的 Tool 并返回结果
        
        参数构建优先级（从高到低）：
        1. 直接传入的参数（request.input）
        2. tool_args_mapping 映射
        3. tool_params 模板渲染
        4. 默认值（通过 Jinja2 过滤器或 input_schema）
        """
        if definition.definition.get("kind") == "mcp_stdio":
            return await self._execute_mcp_stdio(definition, request, metrics)

        tool_name = definition.definition.get("tool_name")

        if not tool_name:
            return {
                "type": "tool",
                "output": None,
                "error": f"No tool_name specified in skill definition: {definition.id}",
                "skill_id": definition.id,
                "version": definition.version
            }

        # 构建 ToolContext
        from core.tools.context import ToolContext
        _tc_tid = (str(request.tenant_id).strip() if request.tenant_id else "") or None
        tool_ctx = ToolContext(
            agent_id=request.caller_id,
            trace_id=request.trace_id,
            workspace=request.metadata.get("workspace", "."),
            permissions=request.metadata.get("permissions", {}),
            tenant_id=_tc_tid,
        )

        tool_input = self._build_tool_inputs_from_definition(definition, request)

        # 执行 Tool
        from core.tools.registry import ToolRegistry
        try:
            result = await ToolRegistry.execute(tool_name, tool_input, tool_ctx)
            
            if result.success:
                return {
                    "type": "tool",
                    "output": result.data,
                    "skill_id": definition.id,
                    "version": definition.version,
                    "tool_name": tool_name
                }
            else:
                return {
                    "type": "tool",
                    "output": None,
                    "error": result.error,
                    "skill_id": definition.id,
                    "version": definition.version,
                    "tool_name": tool_name
                }
        except Exception as e:
            logger.exception(f"[DefaultSkillExecutor] Tool execution failed: {e}")
            return {
                "type": "tool",
                "output": None,
                "error": str(e),
                "skill_id": definition.id,
                "version": definition.version,
                "tool_name": tool_name
            }
    
    async def _execute_composite(
        self,
        definition: SkillDefinition,
        request: SkillExecutionRequest,
        metrics: ExecutionMetrics
    ) -> Dict[str, Any]:
        """
        执行 Composite 类型 Skill
        
        先渲染 prompt，然后调用 tool
        """
        # 先执行 prompt 部分
        prompt_result = await self._execute_prompt(definition, request, metrics)
        
        # 然后执行 tool 部分
        tool_result = await self._execute_tool(definition, request, metrics)
        
        # composite 的结果：如果 tool 成功，返回 tool 结果；否则返回错误
        if tool_result.get("error"):
            return {
                "type": "composite",
                "output": None,
                "error": tool_result.get("error"),
                "prompt_output": prompt_result.get("output"),
                "tool_output": tool_result.get("output"),
                "skill_id": definition.id,
                "version": definition.version
            }
        
        return {
            "type": "composite",
            "output": tool_result.get("output"),
            "prompt_output": prompt_result.get("output"),
            "tool_output": tool_result.get("output"),
            "skill_id": definition.id,
            "version": definition.version
        }
    
    async def _execute_workflow(
        self,
        definition: SkillDefinition,
        request: SkillExecutionRequest,
        metrics: ExecutionMetrics
    ) -> Dict[str, Any]:
        """
        执行 Workflow 类型 Skill
        
        按顺序执行工作流步骤
        """
        workflow_steps = definition.definition.get("steps", [])
        
        if not workflow_steps:
            return {
                "type": "workflow",
                "output": None,
                "error": "No workflow steps defined",
                "skill_id": definition.id,
                "version": definition.version
            }
        
        results = []
        for step in workflow_steps:
            step_type = step.get("type")
            step_result = {"step": step, "output": None, "error": None}
            
            try:
                if step_type == "prompt":
                    # 创建临时 SkillDefinition 执行 prompt
                    temp_def = SkillDefinition(
                        id=f"{definition.id}.step",
                        name="Workflow Step",
                        version="1.0.0",
                        description="Workflow step",
                        type="prompt",
                        definition={"prompt_template": step.get("prompt_template", "")},
                        input_schema={"type": "object"},
                        output_schema={"type": "object"}
                    )
                    result = await self._execute_prompt(temp_def, request, metrics)
                    step_result["output"] = result.get("output")
                    
                elif step_type == "tool":
                    # 创建临时 SkillDefinition 执行 tool
                    temp_def = SkillDefinition(
                        id=f"{definition.id}.step",
                        name="Workflow Step",
                        version="1.0.0",
                        description="Workflow step",
                        type="tool",
                        definition={
                            "tool_name": step.get("tool_name"),
                            "tool_params": step.get("tool_params", {})
                        },
                        input_schema={"type": "object"},
                        output_schema={"type": "object"}
                    )
                    result = await self._execute_tool(temp_def, request, metrics)
                    step_result["output"] = result.get("output")
                    step_result["error"] = result.get("error")
                    
                else:
                    step_result["error"] = f"Unknown step type: {step_type}"
                    
            except Exception as e:
                step_result["error"] = str(e)
            
            results.append(step_result)
            
            # 如果步骤失败且配置了 stop_on_error，停止工作流
            if step_result["error"] and step.get("stop_on_error", True):
                break
        
        # 检查是否有错误
        errors = [r for r in results if r.get("error")]
        
        return {
            "type": "workflow",
            "output": {
                "steps": results,
                "step_count": len(results),
                "success_count": len([r for r in results if not r.get("error")]),
                "error_count": len(errors)
            },
            "error": errors[0]["error"] if errors else None,
            "skill_id": definition.id,
            "version": definition.version
        }


# ========== 兼容层 ==========
# 保持现有的 SkillRegistry.get() 用法


class LegacySkillExecutor:
    """
    兼容层：支持旧的 Skill 执行 API
    
    旧的调用方式：
    ```python
    executor = SkillExecutor()
    result = await executor.execute(skill, inputs, tool_context)
    ```
    
    新的调用方式：
    ```python
    response = await SkillExecutor.execute(request)
    ```
    """
    
    async def execute(
        self,
        skill: Any,  # Skill v1 对象
        inputs: Dict[str, Any],
        tool_context: Any  # ToolContext
    ) -> Dict[str, Any]:
        """
        兼容旧 API 的执行方法
        
        Args:
            skill: Skill v1 对象 (core.skills.models.Skill)
            inputs: Skill 输入参数
            tool_context: ToolContext 对象
        
        Returns:
            执行结果（与旧 API 兼容的格式）
        """
        # 将 v1 Skill 转换为 v2 SkillDefinition
        if hasattr(skill, 'to_v2'):
            definition = skill.to_v2()
        else:
            # 如果已经是 v2 格式，直接使用
            definition = skill
        
        # 构建 v2 请求
        _tc_tid = getattr(tool_context, "tenant_id", None)
        _tid = (str(_tc_tid).strip() if _tc_tid else "") or None
        request = SkillExecutionRequest(
            skill_id=definition.id,
            input=inputs,
            trace_id=getattr(tool_context, 'trace_id', 'legacy_trace'),
            caller_id=getattr(tool_context, 'agent_id', 'legacy_agent'),
            tenant_id=_tid,
            metadata={
                'workspace': getattr(tool_context, 'workspace', '.'),
                'permissions': getattr(tool_context, 'permissions', {}),
            }
        )
        
        # 调用 v2 执行器
        response = await SkillExecutor.execute(request)
        
        # 将 v2 响应转换为旧格式
        if response.status == "success":
            output_payload = response.output or {}
            return {
                "type": output_payload.get("type", "unknown"),
                "output": output_payload.get("output"),
                "skill_id": response.skill_id,
                "version": response.version,
            }
        else:
            error_payload = response.error or {}
            return {
                "type": "error",
                "output": None,
                "error": error_payload.get("message", "Unknown error"),
                "skill_id": response.skill_id,
                "version": response.version,
            }


def get_skill(skill_id: str, version: Optional[str] = None) -> Optional[SkillDefinition]:
    """
    兼容旧 API：获取 Skill 定义
    
    推荐使用新的统一执行入口：
    ```python
    response = await SkillExecutor.execute(request)
    ```
    """
    return cast(Optional[SkillDefinition], SkillRegistry.get(skill_id, version))


# 保持旧 API 的导入兼容性
# 在 agent_runtime/v2/executors.py 中使用的 SkillExecutor().execute(skill, inputs, tool_context)
# 将被映射到 LegacySkillExecutor().execute(skill, inputs, tool_context)
SkillExecutorLegacy = LegacySkillExecutor
