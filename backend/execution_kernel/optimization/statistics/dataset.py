"""
V2.7: Optimization Layer - Optimization Dataset

聚合节点和 Skill 的统计信息
"""

from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from datetime import UTC, datetime

from execution_kernel.optimization.statistics.models import NodeStatistics, SkillStatistics


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class OptimizationDataset:
    """
    优化数据集
    
    包含节点级别和 Skill 级别的统计信息
    由 StatisticsCollector 生成，供 SnapshotBuilder 使用
    
    Attributes:
        node_stats: 节点统计字典 {node_id: NodeStatistics}
        skill_stats: Skill 统计字典 {skill_name: SkillStatistics}
        created_at: 创建时间
        event_count: 基于的事件数量
        instance_count: 统计的实例数量
        metrics_summary: 可选，由 collect_with_metrics 填充的聚合指标摘要
    """
    node_stats: Dict[str, NodeStatistics] = field(default_factory=dict)
    skill_stats: Dict[str, SkillStatistics] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)
    event_count: int = 0
    instance_count: int = 0
    metrics_summary: Optional[Dict[str, Any]] = None
    
    def get_node_stat(self, node_id: str) -> Optional[NodeStatistics]:
        """获取指定节点的统计信息"""
        return self.node_stats.get(node_id)
    
    def get_skill_stat(self, skill_name: str) -> Optional[SkillStatistics]:
        """获取指定 Skill 的统计信息"""
        return self.skill_stats.get(skill_name)
    
    def get_node_ids(self) -> list:
        """获取所有节点 ID"""
        return list(self.node_stats.keys())
    
    def get_skill_names(self) -> list:
        """获取所有 Skill 名称"""
        return list(self.skill_stats.keys())
    
    def merge(self, other: "OptimizationDataset") -> "OptimizationDataset":
        """
        合并两个数据集
        
        用于增量更新统计信息
        """
        merged_node_stats = dict(self.node_stats)
        merged_skill_stats = dict(self.skill_stats)
        
        # 合并节点统计
        for node_id, node_stat in other.node_stats.items():
            if node_id in merged_node_stats:
                existing = merged_node_stats[node_id]
                merged_node_stats[node_id] = NodeStatistics(
                    node_id=node_id,
                    skill_name=node_stat.skill_name or existing.skill_name,
                    execution_count=existing.execution_count + node_stat.execution_count,
                    success_count=existing.success_count + node_stat.success_count,
                    failure_count=existing.failure_count + node_stat.failure_count,
                    total_latency_ms=existing.total_latency_ms + node_stat.total_latency_ms,
                    retry_success_count=existing.retry_success_count + node_stat.retry_success_count,
                    last_updated=_utc_now(),
                )
            else:
                merged_node_stats[node_id] = node_stat
        
        # 合并 Skill 统计
        for skill_name, skill_stat in other.skill_stats.items():
            if skill_name in merged_skill_stats:
                existing_skill = merged_skill_stats[skill_name]
                merged_skill_stats[skill_name] = SkillStatistics(
                    skill_name=skill_name,
                    execution_count=existing_skill.execution_count + skill_stat.execution_count,
                    success_count=existing_skill.success_count + skill_stat.success_count,
                    failure_count=existing_skill.failure_count + skill_stat.failure_count,
                    total_latency_ms=existing_skill.total_latency_ms + skill_stat.total_latency_ms,
                    retry_success_count=existing_skill.retry_success_count + skill_stat.retry_success_count,
                    node_count=max(existing_skill.node_count, skill_stat.node_count),
                    last_updated=_utc_now(),
                )
            else:
                merged_skill_stats[skill_name] = skill_stat
        
        return OptimizationDataset(
            node_stats=merged_node_stats,
            skill_stats=merged_skill_stats,
            created_at=_utc_now(),
            event_count=self.event_count + other.event_count,
            instance_count=self.instance_count + other.instance_count,
            metrics_summary=None,  # 合并后不保留单次收集的 metrics_summary
        )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        out = {
            "node_stats": {
                node_id: stat.to_dict()
                for node_id, stat in self.node_stats.items()
            },
            "skill_stats": {
                skill_name: stat.to_dict()
                for skill_name, stat in self.skill_stats.items()
            },
            "created_at": self.created_at.isoformat(),
            "event_count": self.event_count,
            "instance_count": self.instance_count,
        }
        if self.metrics_summary is not None:
            out["metrics_summary"] = self.metrics_summary
        return out
