"""
Workflow Version Service

WorkflowVersion 和 WorkflowDefinition 的业务逻辑层。
"""

from typing import List, Optional, Dict, Any, Set
from sqlalchemy.orm import Session

from core.workflows.models import (
    WorkflowVersion,
    WorkflowDefinition,
    WorkflowVersionState,
    WorkflowDAG,
    WorkflowNode,
    WorkflowEdge
)
from core.workflows.repository import WorkflowVersionRepository
from core.system.settings_store import get_system_settings_store
from config.settings import settings
from log import logger


class WorkflowVersionService:
    """Workflow 版本业务服务"""
    
    def __init__(self, db: Session):
        self.db = db
        self.repository = WorkflowVersionRepository(db)
    
    def create_definition(
        self,
        workflow_id: str,
        description: Optional[str] = None,
        change_log: Optional[str] = None,
        source_version_id: Optional[str] = None,
        created_by: Optional[str] = None
    ) -> WorkflowDefinition:
        """创建定义"""
        definition = WorkflowDefinition(
            workflow_id=workflow_id,
            description=description,
            change_log=change_log,
            source_version_id=source_version_id,
            created_by=created_by
        )
        
        created = self.repository.create_definition(definition)
        logger.info(f"[WorkflowVersionService] Created definition: {created.definition_id}")
        return created
    
    def get_definition(self, definition_id: str) -> Optional[WorkflowDefinition]:
        """获取定义"""
        return self.repository.get_definition_by_id(definition_id)
    
    def list_definitions(
        self,
        workflow_id: str,
        limit: int = 100
    ) -> List[WorkflowDefinition]:
        """列出定义"""
        return self.repository.list_definitions_by_workflow(workflow_id, limit)
    
    def create_version(
        self,
        workflow_id: str,
        definition_id: str,
        dag: WorkflowDAG,
        version_number: Optional[str] = None,
        description: Optional[str] = None,
        change_notes: Optional[str] = None,
        created_by: Optional[str] = None
    ) -> WorkflowVersion:
        """创建版本"""
        dag = self._normalize_dag(dag)

        # 验证 DAG
        errors = dag.validate_dag()
        if errors:
            raise ValueError(f"DAG validation failed: {'; '.join(errors)}")
        self._validate_workflow_global_config(dag.global_config or {})
        self._validate_sub_workflow_references(workflow_id, dag)
        
        # 生成版本号
        if version_number is None:
            version_number = self.repository.get_next_version_number(workflow_id)
        
        # 计算校验和
        checksum = dag.compute_checksum()
        
        # 创建版本
        version = WorkflowVersion(
            workflow_id=workflow_id,
            definition_id=definition_id,
            version_number=version_number,
            dag=dag,
            checksum=checksum,
            state=WorkflowVersionState.DRAFT,
            description=description,
            change_notes=change_notes,
            created_by=created_by
        )
        
        created = self.repository.create_version(version)
        logger.info(f"[WorkflowVersionService] Created version: {created.version_id} ({version_number})")
        return created

    @staticmethod
    def _normalize_dag(dag: WorkflowDAG) -> WorkflowDAG:
        """配置归一化：收敛历史字段，降低前后端字段漂移风险。"""
        normalized_nodes = [WorkflowVersionService._normalize_node(node) for node in dag.nodes]
        normalized_edges = [WorkflowVersionService._normalize_edge(edge) for edge in dag.edges]

        return WorkflowDAG(
            nodes=normalized_nodes,
            edges=normalized_edges,
            entry_node=dag.entry_node,
            global_config=dag.global_config,
        )

    @staticmethod
    def _normalize_node(node: WorkflowNode) -> WorkflowNode:
        cfg = dict(node.config or {})
        node_type = str(node.type or "").strip().lower()
        workflow_node_type = str(cfg.get("workflow_node_type") or node_type).strip().lower()

        WorkflowVersionService._normalize_llm_config(cfg, workflow_node_type)
        WorkflowVersionService._normalize_agent_config(cfg, workflow_node_type)
        WorkflowVersionService._normalize_tool_config(cfg, workflow_node_type)
        WorkflowVersionService._normalize_sub_workflow_config(cfg, workflow_node_type)

        return WorkflowNode(
            id=node.id,
            type=node.type,
            name=node.name,
            description=node.description,
            config=cfg,
            position=node.position,
        )

    @staticmethod
    def _normalize_llm_config(cfg: Dict[str, Any], workflow_node_type: str) -> None:
        if workflow_node_type != "llm":
            return
        model_id = str(cfg.get("model_id") or "").strip()
        legacy_model = str(cfg.get("model") or "").strip()
        if not model_id and legacy_model:
            cfg["model_id"] = legacy_model
        cfg.pop("model", None)

    @staticmethod
    def _normalize_agent_config(cfg: Dict[str, Any], workflow_node_type: str) -> None:
        if workflow_node_type not in {"agent", "manager", "worker", "reflector"}:
            return
        timeout = cfg.get("timeout")
        legacy_timeout = cfg.get("agent_timeout_seconds")
        if (timeout is None or timeout == "") and (legacy_timeout is not None and legacy_timeout != ""):
            cfg["timeout"] = legacy_timeout
        cfg.pop("agent_timeout_seconds", None)

    @staticmethod
    def _normalize_tool_config(cfg: Dict[str, Any], workflow_node_type: str) -> None:
        if workflow_node_type not in {"tool", "skill"}:
            return
        tool_name = str(cfg.get("tool_name") or "").strip()
        tool_id = str(cfg.get("tool_id") or "").strip()
        if not tool_name and tool_id:
            cfg["tool_name"] = tool_id
        cfg.pop("tool_id", None)

    @staticmethod
    def _normalize_sub_workflow_config(cfg: Dict[str, Any], workflow_node_type: str) -> None:
        if workflow_node_type != "sub_workflow":
            return
        selector = str(
            cfg.get("version_selector") or cfg.get("target_version_selector") or "fixed"
        ).strip().lower()
        if selector not in {"fixed", "latest"}:
            selector = "fixed"
        cfg["target_version_selector"] = selector
        cfg.pop("version_selector", None)

    @staticmethod
    def _normalize_edge(edge: WorkflowEdge) -> WorkflowEdge:
        source_handle = str(edge.source_handle or "").strip().lower() or None
        label = str(edge.label or "").strip().lower() or None

        if not source_handle and label in {
            "true",
            "false",
            "continue",
            "exit",
            "condition_true",
            "condition_false",
            "loop_continue",
            "loop_exit",
        }:
            source_handle = label
        if not label and source_handle in {"true", "false", "continue", "exit"}:
            label = source_handle

        return WorkflowEdge(
            from_node=edge.from_node,
            to_node=edge.to_node,
            source_handle=source_handle,
            target_handle=edge.target_handle,
            condition=edge.condition,
            label=label,
        )
    
    def get_version(self, version_id: str) -> Optional[WorkflowVersion]:
        """获取版本"""
        return self.repository.get_version_by_id(version_id)
    
    def get_version_by_number(
        self,
        workflow_id: str,
        version_number: str
    ) -> Optional[WorkflowVersion]:
        """根据版本号获取版本"""
        return self.repository.get_version_by_number(workflow_id, version_number)
    
    def list_versions(
        self,
        workflow_id: str,
        state: Optional[WorkflowVersionState] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[WorkflowVersion]:
        """列出版本"""
        return self.repository.list_versions_by_workflow(
            workflow_id,
            state=state,
            limit=limit,
            offset=offset
        )

    def count_versions(
        self,
        workflow_id: str,
        state: Optional[WorkflowVersionState] = None,
    ) -> int:
        return self.repository.count_versions_by_workflow(workflow_id, state=state)
    
    def publish_version(
        self,
        version_id: str,
        published_by: str
    ) -> Optional[WorkflowVersion]:
        """发布版本"""
        version = self.repository.get_version_by_id(version_id)
        if not version:
            return None
        
        # 验证 DAG
        errors = version.dag.validate_dag(
            require_condition_branches=True,
            require_loop_branches=True,
        )
        if errors:
            raise ValueError(f"Cannot publish invalid DAG: {'; '.join(errors)}")
        self._validate_workflow_global_config(version.dag.global_config or {})
        self._validate_sub_workflow_references(version.workflow_id, version.dag)
        self._validate_sub_workflow_cycles(version.workflow_id, version.version_id, version.dag)
        impact = self.analyze_subworkflow_impact(
            target_workflow_id=version.workflow_id,
            target_version_id=version.version_id,
            include_only_published=True,
        )
        if bool(getattr(settings, "workflow_block_publish_on_subworkflow_breaking_impact", True)):
            runtime_policy = self._load_runtime_contract_policy()
            block_on_breaking = bool(runtime_policy.get("block_publish_on_breaking", True))
            if not block_on_breaking:
                return self.repository.publish_version(version_id, published_by)
            breaking_count = int((impact.get("risk_summary") or {}).get("breaking") or 0)
            if breaking_count > 0:
                raise ValueError(
                    "Sub-workflow breaking contract change detected: "
                    f"{breaking_count} published parent reference(s) impacted"
                )
        
        # 验证校验和
        if not self.repository.validate_dag_checksum(version_id):
            raise ValueError("DAG checksum validation failed")
        
        published = self.repository.publish_version(version_id, published_by)
        logger.info(f"[WorkflowVersionService] Published version: {version_id}")
        return published

    def _validate_sub_workflow_references(self, current_workflow_id: str, dag: WorkflowDAG) -> None:
        for node in dag.nodes:
            cfg = dict(node.config or {})
            node_type = str(cfg.get("workflow_node_type") or node.type or "").strip().lower()
            if node_type != "sub_workflow":
                continue
            target_workflow_id = str(cfg.get("target_workflow_id") or "").strip()
            if not target_workflow_id:
                raise ValueError(f"Sub-workflow node {node.id} missing target_workflow_id")
            if target_workflow_id == current_workflow_id:
                raise ValueError(f"Sub-workflow node {node.id} cannot reference itself")
            selector = str(cfg.get("target_version_selector") or "fixed").strip().lower()
            if selector not in {"fixed", "latest"}:
                raise ValueError(f"Sub-workflow node {node.id} has invalid target_version_selector={selector}")
            if selector == "latest":
                continue
            target_version_id = str(cfg.get("target_version_id") or "").strip()
            target_version_num = str(cfg.get("target_version") or "").strip()
            if not target_version_id and not target_version_num:
                raise ValueError(
                    f"Sub-workflow node {node.id} with fixed selector requires target_version_id or target_version"
                )
            if target_version_id:
                target_version = self.repository.get_version_by_id(target_version_id)
            else:
                target_version = self.repository.get_version_by_number(target_workflow_id, target_version_num)
            if target_version is None:
                raise ValueError(
                    f"Sub-workflow node {node.id} references missing version "
                    f"(workflow={target_workflow_id}, version_id={target_version_id or '-'}, version={target_version_num or '-'})"
                )
            if target_version.workflow_id != target_workflow_id:
                raise ValueError(
                    f"Sub-workflow node {node.id} target version does not belong to target_workflow_id"
                )

    @staticmethod
    def _validate_workflow_global_config(global_config: Dict[str, Any]) -> None:
        if not isinstance(global_config, dict):
            raise ValueError("workflow global_config must be object")
        reflector_cfg = global_config.get("reflector")
        if reflector_cfg is None:
            return
        if not isinstance(reflector_cfg, dict):
            raise ValueError("workflow global_config.reflector must be object")
        allowed_keys = {"max_retries", "retry_interval_seconds", "fallback_agent_id"}
        unknown_keys = sorted(set(reflector_cfg.keys()) - allowed_keys)
        if unknown_keys:
            raise ValueError(
                "workflow global_config.reflector has unsupported keys: "
                + ",".join(unknown_keys)
            )

        if "max_retries" in reflector_cfg:
            try:
                max_retries = int(reflector_cfg.get("max_retries"))
            except (TypeError, ValueError):
                raise ValueError("workflow global_config.reflector.max_retries must be integer")
            if max_retries < 0 or max_retries > 20:
                raise ValueError("workflow global_config.reflector.max_retries out of range [0,20]")

        if "retry_interval_seconds" in reflector_cfg:
            try:
                retry_interval = float(reflector_cfg.get("retry_interval_seconds"))
            except (TypeError, ValueError):
                raise ValueError(
                    "workflow global_config.reflector.retry_interval_seconds must be number"
                )
            if retry_interval < 0.0 or retry_interval > 60.0:
                raise ValueError(
                    "workflow global_config.reflector.retry_interval_seconds out of range [0,60]"
                )

        if "fallback_agent_id" in reflector_cfg:
            fallback_agent_id = reflector_cfg.get("fallback_agent_id")
            if fallback_agent_id is not None:
                if not isinstance(fallback_agent_id, str):
                    raise ValueError("workflow global_config.reflector.fallback_agent_id must be string")
                if len(fallback_agent_id) > 512:
                    raise ValueError(
                        "workflow global_config.reflector.fallback_agent_id too long (max 512)"
                    )

    def _validate_sub_workflow_cycles(
        self,
        root_workflow_id: str,
        root_version_id: str,
        dag: WorkflowDAG,
    ) -> None:
        stack: List[str] = [f"{root_workflow_id}:{root_version_id}"]
        self._dfs_sub_workflow_cycle(root_workflow_id, root_version_id, dag, stack, seen=set())

    def _dfs_sub_workflow_cycle(
        self,
        workflow_id: str,
        version_id: str,
        dag: WorkflowDAG,
        stack: List[str],
        seen: set[str],
    ) -> None:
        seen_key = f"{workflow_id}:{version_id}"
        if seen_key in seen:
            return
        seen.add(seen_key)
        for node in dag.nodes:
            cfg = dict(node.config or {})
            node_type = str(cfg.get("workflow_node_type") or node.type or "").strip().lower()
            if node_type != "sub_workflow":
                continue
            child_workflow_id = str(cfg.get("target_workflow_id") or "").strip()
            if not child_workflow_id:
                continue
            child_version = self._resolve_child_version_for_cycle_check(child_workflow_id, cfg)
            if child_version is None:
                continue
            child_key = f"{child_version.workflow_id}:{child_version.version_id}"
            if child_key in stack:
                cycle_chain = " -> ".join(stack + [child_key])
                raise ValueError(f"Sub-workflow cycle detected: {cycle_chain}")
            self._dfs_sub_workflow_cycle(
                child_version.workflow_id,
                child_version.version_id,
                child_version.dag,
                stack + [child_key],
                seen,
            )

    def _resolve_child_version_for_cycle_check(
        self, target_workflow_id: str, cfg: Dict[str, Any]
    ) -> Optional[WorkflowVersion]:
        selector = str(cfg.get("target_version_selector") or "fixed").strip().lower()
        if selector == "latest":
            return self.repository.get_published_version(target_workflow_id)
        version_id = str(cfg.get("target_version_id") or "").strip()
        version_number = str(cfg.get("target_version") or "").strip()
        if version_id:
            return self.repository.get_version_by_id(version_id)
        if version_number:
            return self.repository.get_version_by_number(target_workflow_id, version_number)
        return None
    
    def deprecate_version(
        self,
        version_id: str,
        deprecated_by: str
    ) -> Optional[WorkflowVersion]:
        """弃用版本"""
        version = self.repository.get_version_by_id(version_id)
        if not version:
            return None
        
        deprecated = self.repository.deprecate_version(version_id, deprecated_by)
        logger.info(f"[WorkflowVersionService] Deprecated version: {version_id}")
        return deprecated
    
    def get_published_version(self, workflow_id: str) -> Optional[WorkflowVersion]:
        """获取已发布版本"""
        return self.repository.get_published_version(workflow_id)

    def analyze_subworkflow_impact(
        self,
        target_workflow_id: str,
        target_version_id: Optional[str] = None,
        *,
        include_only_published: bool = False,
        baseline_version_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        分析子工作流版本变更的影响面。
        - fixed 引用：仅命中指定 target_version_id（或等价版本号）
        - latest 引用：命中该 workflow 的所有 latest 引用
        """
        target_version = (
            self.repository.get_version_by_id(target_version_id) if target_version_id else None
        )
        target_version_number = target_version.version_number if target_version else None
        baseline_version = self._resolve_baseline_version(
            target_workflow_id=target_workflow_id,
            target_version=target_version,
            baseline_version_id=baseline_version_id,
        )
        contract_diff = self._compute_contract_diff(
            old_contract=self._extract_workflow_contract(baseline_version),
            new_contract=self._extract_workflow_contract(target_version),
        )
        all_versions = self.repository.list_versions(
            state=WorkflowVersionState.PUBLISHED if include_only_published else None,
            limit=5000,
            offset=0,
        )
        impacted: List[Dict[str, Any]] = []
        for version in all_versions:
            for node in version.dag.nodes:
                ref = self._extract_subworkflow_ref(node)
                if ref is None:
                    continue
                if ref["target_workflow_id"] != target_workflow_id:
                    continue
                impact_kind = self._resolve_impact_kind(
                    ref=ref,
                    target_version_id=target_version_id,
                    target_version_number=target_version_number,
                )
                if impact_kind is None:
                    continue
                impacted.append(
                    {
                        "workflow_id": version.workflow_id,
                        "version_id": version.version_id,
                        "version_number": version.version_number,
                        "version_state": version.state.value,
                        "node_id": node.id,
                        "reference_mode": ref["selector"],
                        "reference_version_id": ref["target_version_id"],
                        "reference_version": ref["target_version"],
                        "impact_kind": impact_kind,
                        "risk_level": self._impact_kind_to_risk_level(
                            impact_kind=impact_kind,
                            contract_diff=contract_diff,
                        ),
                        "impact_reason": self._build_impact_reason(
                            impact_kind=impact_kind,
                            contract_diff=contract_diff,
                        ),
                    }
                )
        risk_summary = self._build_impact_risk_summary(impacted)
        return {
            "target_workflow_id": target_workflow_id,
            "target_version_id": target_version_id,
            "target_version_number": target_version_number,
            "baseline_version_id": baseline_version.version_id if baseline_version else None,
            "baseline_version_number": baseline_version.version_number if baseline_version else None,
            "include_only_published": include_only_published,
            "contract_diff": contract_diff,
            "total_impacted": len(impacted),
            "risk_summary": risk_summary,
            "impacted": impacted,
        }

    @staticmethod
    def _extract_subworkflow_ref(node: WorkflowNode) -> Optional[Dict[str, Optional[str]]]:
        cfg = dict(node.config or {})
        node_type = str(cfg.get("workflow_node_type") or node.type or "").strip().lower()
        if node_type != "sub_workflow":
            return None
        return {
            "selector": str(cfg.get("target_version_selector") or "fixed").strip().lower(),
            "target_workflow_id": str(cfg.get("target_workflow_id") or "").strip(),
            "target_version_id": str(cfg.get("target_version_id") or "").strip() or None,
            "target_version": str(cfg.get("target_version") or "").strip() or None,
        }

    @staticmethod
    def _resolve_impact_kind(
        *,
        ref: Dict[str, Optional[str]],
        target_version_id: Optional[str],
        target_version_number: Optional[str],
    ) -> Optional[str]:
        selector = str(ref.get("selector") or "fixed").lower()
        if selector == "latest":
            return "latest_reference"
        if not target_version_id:
            return "workflow_reference"
        if ref.get("target_version_id") == target_version_id:
            return "fixed_version_match"
        if target_version_number and ref.get("target_version") == target_version_number:
            return "fixed_version_number_match"
        return None

    @staticmethod
    def _impact_kind_to_risk_level(impact_kind: str, contract_diff: Dict[str, Any]) -> str:
        has_breaking_contract_change = bool((contract_diff or {}).get("breaking_changes"))
        if has_breaking_contract_change and impact_kind in {
            "fixed_version_match",
            "fixed_version_number_match",
            "latest_reference",
        }:
            return "breaking"
        if impact_kind == "latest_reference":
            return "risky"
        if impact_kind in {"fixed_version_match", "fixed_version_number_match"}:
            return "compatible"
        return "info"

    @staticmethod
    def _build_impact_reason(impact_kind: str, contract_diff: Dict[str, Any]) -> str:
        breaking_changes = list((contract_diff or {}).get("breaking_changes") or [])
        risky_changes = list((contract_diff or {}).get("risky_changes") or [])
        if breaking_changes:
            return "breaking contract changes detected: " + "; ".join(breaking_changes[:3])
        if impact_kind == "latest_reference":
            if risky_changes:
                return "latest reference with risky contract changes: " + "; ".join(risky_changes[:3])
            return "latest reference may be impacted by future version updates"
        if impact_kind in {"fixed_version_match", "fixed_version_number_match"}:
            return "fixed version reference remains compatible"
        return "reference impact requires manual review"

    @staticmethod
    def _build_impact_risk_summary(items: List[Dict[str, Any]]) -> Dict[str, int]:
        summary: Dict[str, int] = {"breaking": 0, "compatible": 0, "risky": 0, "info": 0}
        for item in items:
            level = str(item.get("risk_level") or "info")
            summary[level] = int(summary.get(level, 0)) + 1
        return summary

    def _resolve_baseline_version(
        self,
        *,
        target_workflow_id: str,
        target_version: Optional[WorkflowVersion],
        baseline_version_id: Optional[str],
    ) -> Optional[WorkflowVersion]:
        if baseline_version_id:
            return self.repository.get_version_by_id(baseline_version_id)
        published_versions = self.repository.list_versions_by_workflow(
            workflow_id=target_workflow_id,
            state=WorkflowVersionState.PUBLISHED,
            limit=20,
            offset=0,
        )
        if not published_versions:
            return None
        if target_version is None:
            return published_versions[0]
        for version in published_versions:
            if version.version_id != target_version.version_id:
                return version
        return None

    @staticmethod
    def _extract_workflow_contract(version: Optional[WorkflowVersion]) -> Dict[str, Any]:
        if version is None:
            return {"input_schema": {}, "output_schema": {}}
        global_cfg = dict(version.dag.global_config or {})
        input_schema = global_cfg.get("input_schema") if isinstance(global_cfg.get("input_schema"), dict) else {}
        output_schema = global_cfg.get("output_schema") if isinstance(global_cfg.get("output_schema"), dict) else {}
        return {
            "input_schema": input_schema,
            "output_schema": output_schema,
        }

    @staticmethod
    def _compute_contract_diff(old_contract: Dict[str, Any], new_contract: Dict[str, Any]) -> Dict[str, Any]:
        old_input = dict((old_contract or {}).get("input_schema") or {})
        new_input = dict((new_contract or {}).get("input_schema") or {})
        old_output = dict((old_contract or {}).get("output_schema") or {})
        new_output = dict((new_contract or {}).get("output_schema") or {})

        breaking_changes: List[str] = []
        risky_changes: List[str] = []
        info_changes: List[str] = []
        runtime_policy = WorkflowVersionService._load_runtime_contract_policy()
        exempt_fields = set(runtime_policy.get("exempt_fields") or set())
        required_input_added_breaking = bool(
            runtime_policy.get("required_input_added_breaking", True)
        )
        output_added_risky = bool(runtime_policy.get("output_added_risky", True))

        WorkflowVersionService._append_input_schema_diff(
            old_input=old_input,
            new_input=new_input,
            breaking_changes=breaking_changes,
            risky_changes=risky_changes,
            info_changes=info_changes,
            exempt_fields=exempt_fields,
            required_added_breaking=required_input_added_breaking,
        )
        WorkflowVersionService._append_output_schema_diff(
            old_output=old_output,
            new_output=new_output,
            breaking_changes=breaking_changes,
            risky_changes=risky_changes,
            info_changes=info_changes,
            exempt_fields=exempt_fields,
            output_added_risky=output_added_risky,
        )
        return {
            "breaking_changes": breaking_changes,
            "risky_changes": risky_changes,
            "info_changes": info_changes,
            "exempt_fields": sorted(exempt_fields),
            "policy": {
                "required_input_added_breaking": required_input_added_breaking,
                "output_added_risky": output_added_risky,
                "block_publish_on_breaking": bool(runtime_policy.get("block_publish_on_breaking", True)),
            },
        }

    @staticmethod
    def _parse_contract_field_exemptions() -> Set[str]:
        raw = str(getattr(settings, "workflow_contract_field_exemptions", "") or "")
        return {
            part.strip()
            for part in raw.split(",")
            if part and part.strip()
        }

    @staticmethod
    def _load_runtime_contract_policy() -> Dict[str, Any]:
        """
        合并运行时策略（DB settings 优先，fallback 到环境配置 settings）。
        """
        store = get_system_settings_store()
        required_input_added_breaking = store.get_setting(
            "workflowContractRequiredInputAddedBreaking",
            getattr(settings, "workflow_contract_required_input_added_breaking", True),
        )
        output_added_risky = store.get_setting(
            "workflowContractOutputAddedRisky",
            getattr(settings, "workflow_contract_output_added_risky", True),
        )
        raw_exemptions = store.get_setting(
            "workflowContractFieldExemptions",
            getattr(settings, "workflow_contract_field_exemptions", ""),
        )
        block_publish_on_breaking = store.get_setting(
            "workflowBlockPublishOnSubworkflowBreakingImpact",
            getattr(settings, "workflow_block_publish_on_subworkflow_breaking_impact", True),
        )
        exemptions = {
            part.strip()
            for part in str(raw_exemptions or "").split(",")
            if part and part.strip()
        }
        return {
            "required_input_added_breaking": bool(required_input_added_breaking),
            "output_added_risky": bool(output_added_risky),
            "exempt_fields": exemptions,
            "block_publish_on_breaking": bool(block_publish_on_breaking),
        }

    @staticmethod
    def _append_input_schema_diff(
        old_input: Dict[str, Any],
        new_input: Dict[str, Any],
        breaking_changes: List[str],
        risky_changes: List[str],
        info_changes: List[str],
        exempt_fields: Set[str],
        required_added_breaking: bool,
    ) -> None:
        old_props = dict(old_input.get("properties") or {})
        new_props = dict(new_input.get("properties") or {})
        old_required = {str(x) for x in (old_input.get("required") or [])}
        new_required = {str(x) for x in (new_input.get("required") or [])}

        for field in sorted(old_props.keys() - new_props.keys()):
            if f"input.{field}" in exempt_fields:
                info_changes.append(f"input field removal exempted: {field}")
                continue
            breaking_changes.append(f"input field removed: {field}")
        for field in sorted(new_required - old_required):
            if f"input.{field}" in exempt_fields:
                info_changes.append(f"input required field addition exempted: {field}")
                continue
            if required_added_breaking:
                breaking_changes.append(f"input required field added: {field}")
            else:
                risky_changes.append(f"input required field added: {field}")
        for field in sorted((old_props.keys() & new_props.keys())):
            old_type = str((old_props.get(field) or {}).get("type") or "")
            new_type = str((new_props.get(field) or {}).get("type") or "")
            if old_type and new_type and old_type != new_type:
                if f"input.{field}" in exempt_fields:
                    info_changes.append(
                        f"input field type change exempted: {field} ({old_type}->{new_type})"
                    )
                    continue
                breaking_changes.append(f"input field type changed: {field} ({old_type}->{new_type})")
        for field in sorted(new_props.keys() - old_props.keys()):
            if field in new_required:
                continue
            if f"input.{field}" in exempt_fields:
                info_changes.append(f"input optional field addition exempted: {field}")
                continue
            risky_changes.append(f"input optional field added: {field}")

    @staticmethod
    def _append_output_schema_diff(
        old_output: Dict[str, Any],
        new_output: Dict[str, Any],
        breaking_changes: List[str],
        risky_changes: List[str],
        info_changes: List[str],
        exempt_fields: Set[str],
        output_added_risky: bool,
    ) -> None:
        old_props = dict(old_output.get("properties") or {})
        new_props = dict(new_output.get("properties") or {})
        for field in sorted(old_props.keys() - new_props.keys()):
            if f"output.{field}" in exempt_fields:
                info_changes.append(f"output field removal exempted: {field}")
                continue
            breaking_changes.append(f"output field removed: {field}")
        for field in sorted((old_props.keys() & new_props.keys())):
            old_type = str((old_props.get(field) or {}).get("type") or "")
            new_type = str((new_props.get(field) or {}).get("type") or "")
            if old_type and new_type and old_type != new_type:
                if f"output.{field}" in exempt_fields:
                    info_changes.append(
                        f"output field type change exempted: {field} ({old_type}->{new_type})"
                    )
                    continue
                breaking_changes.append(f"output field type changed: {field} ({old_type}->{new_type})")
        for field in sorted(new_props.keys() - old_props.keys()):
            if f"output.{field}" in exempt_fields:
                info_changes.append(f"output field addition exempted: {field}")
                continue
            if output_added_risky:
                risky_changes.append(f"output field added: {field}")
            else:
                info_changes.append(f"output field added: {field}")
    
    def validate_dag(
        self,
        dag: WorkflowDAG,
        require_condition_branches: bool = False,
        require_loop_branches: bool = False,
    ) -> List[str]:
        """验证 DAG"""
        return dag.validate_dag(
            require_condition_branches=require_condition_branches,
            require_loop_branches=require_loop_branches,
        )
    
    def build_dag(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        entry_node: Optional[str] = None,
        global_config: Optional[Dict[str, Any]] = None
    ) -> WorkflowDAG:
        """构建 DAG"""
        workflow_nodes = [
            WorkflowNode(
                id=node["id"],
                type=node["type"],
                name=node.get("name"),
                description=node.get("description"),
                config=node.get("config", {}),
                position=node.get("position")
            )
            for node in nodes
        ]
        
        workflow_edges = [
            WorkflowEdge(
                from_node=edge["from"],
                to_node=edge["to"],
                source_handle=edge.get("source_handle"),
                target_handle=edge.get("target_handle"),
                condition=edge.get("condition"),
                label=edge.get("label")
            )
            for edge in edges
        ]
        
        return WorkflowDAG(
            nodes=workflow_nodes,
            edges=workflow_edges,
            entry_node=entry_node,
            global_config=global_config or {}
        )
