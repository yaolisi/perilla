"""
Agent Graph Adapter
Bridge Agent V2 plan into graph-first execution configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.agent_runtime.definition import AgentDefinition
from .models import Plan
from core.execution.adapters.plan_compiler import PlanCompiler
from execution_kernel.models.graph_definition import GraphDefinition


@dataclass(frozen=True)
class AgentGraphExecutionConfig:
    parallel_enabled: bool = False
    max_parallel_nodes: Optional[int] = None


class AgentGraphAdapter:
    """
    Build execution graph and runtime config from Agent + Plan.
    """

    def __init__(self) -> None:
        self._compiler = PlanCompiler()

    def resolve_execution_config(self, agent: AgentDefinition) -> AgentGraphExecutionConfig:
        strategy = (getattr(agent, "execution_strategy", None) or "").strip().lower()
        if not strategy and isinstance(getattr(agent, "model_params", None), dict):
            strategy = str(agent.model_params.get("execution_strategy") or "").strip().lower()
        if strategy not in {"serial", "parallel_kernel"}:
            strategy = "parallel_kernel" if bool(getattr(agent, "use_execution_kernel", False)) else "serial"

        max_parallel_nodes = getattr(agent, "max_parallel_nodes", None)
        if max_parallel_nodes is None and isinstance(getattr(agent, "model_params", None), dict):
            raw = agent.model_params.get("max_parallel_nodes")
            if isinstance(raw, int):
                max_parallel_nodes = raw
        if isinstance(max_parallel_nodes, int):
            if max_parallel_nodes < 1:
                max_parallel_nodes = 1
            if max_parallel_nodes > 64:
                max_parallel_nodes = 64
        else:
            max_parallel_nodes = None

        return AgentGraphExecutionConfig(
            parallel_enabled=(strategy == "parallel_kernel"),
            max_parallel_nodes=max_parallel_nodes,
        )

    def build_graph(self, plan: Plan, config: AgentGraphExecutionConfig) -> GraphDefinition:
        graph_plan = plan.model_copy(deep=True)
        graph_plan.context = dict(graph_plan.context or {})
        graph_plan.context["agent_graph_parallel"] = bool(config.parallel_enabled)
        graph = self._compiler.compile(graph_plan)
        return graph
