"""
Agent V2 执行器定义
支持 LLM / Skill / ToolChain / Internal 执行方式
"""
from abc import ABC, abstractmethod
from typing import Any, Dict
import asyncio

from log import logger
from .models import AgentState, Step, StepStatus, ExecutorType


class BaseExecutor(ABC):
    """执行器基类"""

    @abstractmethod
    async def execute(
        self,
        step: Step,
        state: AgentState,
        context: Dict[str, Any]
    ) -> Step:
        """
        执行步骤
        
        Args:
            step: 要执行的步骤
            state: Agent 状态
            context: 执行上下文（包含 agent, session, workspace 等）
        
        Returns:
            更新后的 Step（包含 outputs 和 status）
        """
        pass


class LLMExecutor(BaseExecutor):
    """LLM 执行器 - 调用大语言模型
    
    V2.8: Now uses InferenceClient for unified model access.
    """

    async def execute(
        self,
        step: Step,
        state: AgentState,
        context: Dict[str, Any]
    ) -> Step:
        """通过 LLM 执行步骤"""
        from core.types import Message
        from core.inference import get_inference_client

        step.status = StepStatus.RUNNING
        
        try:
            # 从 context 获取必要信息
            agent = context.get("agent")
            session = context.get("session")
            
            if not agent or not session:
                raise ValueError("LLMExecutor requires 'agent' and 'session' in context")

            # 构建 messages
            raw_messages = step.inputs.get("messages", [])
            messages = []
            for msg in raw_messages:
                if isinstance(msg, dict):
                    messages.append(Message(**msg))
                else:
                    messages.append(msg)
            
            # 检查是否是静默模式
            if step.inputs.get("_silent"):
                # 静默模式：返回空响应
                step.outputs = {
                    "response": "",
                    "model_id": agent.model_id,
                }
                step.status = StepStatus.COMPLETED
                logger.info(f"[LLMExecutor] Step {step.step_id} completed (silent mode - empty response)")
                return step
            
            # V2.8: Use InferenceClient for unified access
            client = get_inference_client()
            model_params = step.inputs.get("model_params") or {}
            
            response = await client.generate(
                model=agent.model_id,
                messages=messages,
                temperature=step.inputs.get("temperature", agent.temperature),
                max_tokens=model_params.get("max_tokens", 2048),
                stop=model_params.get("stop"),
                metadata={
                    "caller": "LLMExecutor",
                    "step_id": step.step_id,
                    "session_id": getattr(session, "session_id", ""),
                    "trace_id": getattr(session, "trace_id", ""),
                    "agent_id": agent.agent_id,
                },
            )

            step.outputs = {
                "response": response.text,
                "model_id": agent.model_id,
                "latency_ms": response.latency_ms,
            }
            step.status = StepStatus.COMPLETED
            
            logger.info(f"[LLMExecutor] Step {step.step_id} completed (latency: {response.latency_ms:.1f}ms)")
            
        except Exception as e:
            logger.error(f"[LLMExecutor] Step {step.step_id} failed: {e}")
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.outputs = {"error": str(e)}
        
        return step


class SkillExecutor(BaseExecutor):
    """Skill 执行器 - 调用技能（v2 API）"""

    @staticmethod
    async def _run_one_skill(
        skill_id: str,
        skill_inputs: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        from core.skills.registry import SkillRegistry
        from core.skills.executor import SkillExecutor as V2SkillExecutor
        from core.skills.contract import SkillExecutionRequest

        definition = SkillRegistry.get(skill_id)
        if not definition:
            raise ValueError(f"Skill not found: {skill_id}")
        _tid = context.get("tenant_id")
        _tenant = (str(_tid).strip() if _tid else "") or None
        request = SkillExecutionRequest(
            skill_id=skill_id,
            input=skill_inputs,
            version=None,
            trace_id=context.get("trace_id", ""),
            caller_id=context.get("agent_id", ""),
            tenant_id=_tenant,
            metadata={
                "workspace": context.get("workspace", "."),
                "permissions": context.get("permissions", {}),
                "step_id": context.get("step_id", ""),
            },
        )
        response = await V2SkillExecutor.execute(request)
        return {
            "skill_id": skill_id,
            "version": response.version,
            "status": response.status,
            "output": response.output,
            "metrics": response.metrics,
            "error": response.error,
        }

    async def execute(
        self,
        step: Step,
        state: AgentState,
        context: Dict[str, Any]
    ) -> Step:
        """通过 Skill 执行步骤 - 使用 v2 统一执行入口"""
        step.status = StepStatus.RUNNING
        
        try:
            parallel_calls = step.inputs.get("parallel_calls")
            if isinstance(parallel_calls, list) and parallel_calls:
                max_parallel = int(context.get("max_parallel_steps", 4))
                sem = asyncio.Semaphore(max(1, max_parallel))

                async def _bounded_call(call_item: Dict[str, Any]) -> Dict[str, Any]:
                    skill_id = str(call_item.get("skill_id") or "").strip()
                    if not skill_id:
                        raise ValueError("parallel_calls item missing skill_id")
                    inputs = call_item.get("inputs", {})
                    async with sem:
                        return await self._run_one_skill(
                            skill_id=skill_id,
                            skill_inputs=inputs if isinstance(inputs, dict) else {},
                            context={**context, "step_id": step.step_id},
                        )

                tasks = []
                for item in parallel_calls:
                    if isinstance(item, dict):
                        tasks.append(_bounded_call(item))
                if not tasks:
                    raise ValueError("parallel_calls is empty or invalid")
                results = await asyncio.gather(*tasks, return_exceptions=True)
                normalized_results = []
                has_error = False
                for item in results:
                    if isinstance(item, Exception):
                        has_error = True
                        normalized_results.append({"status": "error", "error": {"message": str(item)}})
                    else:
                        if item.get("status") != "success":
                            has_error = True
                        normalized_results.append(item)
                step.outputs = {
                    "mode": "parallel_calls",
                    "results": normalized_results,
                    "max_parallel_steps": max(1, max_parallel),
                }
                if has_error:
                    step.status = StepStatus.FAILED
                    step.error = "One or more parallel skill calls failed"
                    step.outputs["error"] = {"message": step.error}
                else:
                    step.status = StepStatus.COMPLETED
                logger.info(f"[SkillExecutor] Step {step.step_id} parallel_calls completed: count={len(tasks)}")
            else:
                skill_id = step.inputs.get("skill_id")
                if not skill_id:
                    raise ValueError("SkillExecutor requires 'skill_id' in step.inputs")
                skill_inputs = step.inputs.get("inputs", {})
                response = await self._run_one_skill(
                    skill_id=skill_id,
                    skill_inputs=skill_inputs if isinstance(skill_inputs, dict) else {},
                    context={**context, "step_id": step.step_id},
                )
                step.outputs = {
                    "skill_id": response.get("skill_id"),
                    "version": response.get("version"),
                    "status": response.get("status"),
                    "output": response.get("output"),
                    "metrics": response.get("metrics"),
                }
                if response.get("status") == "success":
                    step.status = StepStatus.COMPLETED
                    logger.info(f"[SkillExecutor] Step {step.step_id} completed (skill: {skill_id})")
                else:
                    step.status = StepStatus.FAILED
                    err = response.get("error")
                    step.error = err.get("message", "Execution failed") if isinstance(err, dict) else "Execution failed"
                    step.outputs["error"] = response.get("error")
                    logger.warning(f"[SkillExecutor] Step {step.step_id} failed (skill: {skill_id}): {step.error}")

            if step.status == StepStatus.COMPLETED:
                step.status = StepStatus.COMPLETED
            
        except Exception as e:
            logger.error(f"[SkillExecutor] Step {step.step_id} failed: {e}")
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.outputs = {"error": str(e)}
        
        return step


class ToolChainExecutor(BaseExecutor):
    """ToolChain 执行器 - 按顺序执行多个原子操作"""

    async def execute(
        self,
        step: Step,
        state: AgentState,
        context: Dict[str, Any]
    ) -> Step:
        """通过 ToolChain 执行步骤"""
        step.status = StepStatus.RUNNING
        
        try:
            chain_id = step.inputs.get("chain_id")
            if not chain_id:
                raise ValueError("ToolChainExecutor requires 'chain_id' in step.inputs")

            # TODO: 未来实现 - 从注册中心加载 ToolChain
            # chain = ToolChainRegistry.get(chain_id)
            # results = await chain.execute(step.inputs.get("inputs", {}), context)
            
            step.outputs = {
                "chain_id": chain_id,
                "message": "ToolChain execution not implemented yet",
            }
            step.status = StepStatus.COMPLETED
            
            logger.info(f"[ToolChainExecutor] Step {step.step_id} completed (chain: {chain_id})")
            
        except Exception as e:
            logger.error(f"[ToolChainExecutor] Step {step.step_id} failed: {e}")
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.outputs = {"error": str(e)}
        
        return step


class InternalExecutor(BaseExecutor):
    """Internal 执行器 - 执行内部操作（如 composite 步骤的子计划调度）"""

    async def execute(
        self,
        step: Step,
        state: AgentState,
        context: Dict[str, Any]
    ) -> Step:
        """Internal 执行器 - 主要用于调度 sub_plan"""
        step.status = StepStatus.RUNNING
        
        try:
            # Internal 执行器主要用于 composite 步骤
            # 实际的 sub_plan 执行由 PlanBasedExecutor 递归处理
            step.outputs = {
                "message": "Internal executor - sub_plan should be handled by PlanBasedExecutor",
            }
            step.status = StepStatus.COMPLETED
            
            logger.info(f"[InternalExecutor] Step {step.step_id} completed")
            
        except Exception as e:
            logger.error(f"[InternalExecutor] Step {step.step_id} failed: {e}")
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.outputs = {"error": str(e)}
        
        return step


# ============== Executor Factory ==============
class ExecutorFactory:
    """执行器工厂"""

    _executors: Dict[ExecutorType, BaseExecutor] = {}

    @classmethod
    def get_executor(cls, executor_type: ExecutorType) -> BaseExecutor:
        """获取执行器实例"""
        if executor_type not in cls._executors:
            cls._executors[executor_type] = cls._create_executor(executor_type)
        return cls._executors[executor_type]

    @classmethod
    def _create_executor(cls, executor_type: ExecutorType) -> BaseExecutor:
        """创建执行器实例"""
        executors = {
            ExecutorType.LLM: LLMExecutor,
            ExecutorType.SKILL: SkillExecutor,
            ExecutorType.TOOLCHAIN: ToolChainExecutor,
            ExecutorType.INTERNAL: InternalExecutor,
        }
        
        executor_class = executors.get(executor_type)
        if not executor_class:
            raise ValueError(f"Unknown executor type: {executor_type}")
        
        return executor_class()
