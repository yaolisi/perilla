"""
Workflow Version Repository

WorkflowVersion 和 WorkflowDefinition 的 CRUD 操作。
"""

from typing import List, Optional, Dict, Any, cast
from datetime import UTC, datetime
from sqlalchemy.orm import Session

from core.workflows.models import (
    WorkflowVersion,
    WorkflowDefinition,
    WorkflowVersionState,
    WorkflowDAG
)
from core.data.models.workflow import WorkflowDefinitionORM, WorkflowVersionORM
from log import logger


class WorkflowVersionRepository:
    """工作流版本仓库"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def _deserialize_version_from_orm(self, row: WorkflowVersionORM) -> WorkflowVersion:
        """从 ORM 对象反序列化为 WorkflowVersion"""
        row_any = cast(Any, row)
        data: Dict[str, Any] = {
            "version_id": cast(str, row_any.version_id),
            "workflow_id": cast(str, row_any.workflow_id),
            "definition_id": cast(str, row_any.definition_id),
            "version_number": cast(str, row_any.version_number),
            "checksum": cast(str, row_any.checksum),
            "state": WorkflowVersionState(cast(str, row_any.state)),
            "description": cast(Optional[str], row_any.description),
            "change_notes": cast(Optional[str], row_any.change_notes),
            "created_at": cast(datetime, row_any.created_at),
            "created_by": cast(Optional[str], row_any.created_by),
            "published_at": cast(Optional[datetime], row_any.published_at),
            "published_by": cast(Optional[str], row_any.published_by),
        }
        # 反序列化 DAG
        data["dag"] = WorkflowDAG.model_validate_json(cast(str, row_any.dag_json))
        return WorkflowVersion(**data)
    
    # ==================== Definition Operations ====================
    
    def create_definition(self, definition: WorkflowDefinition) -> WorkflowDefinition:
        """创建定义"""
        orm = WorkflowDefinitionORM(
            definition_id=definition.definition_id,
            workflow_id=definition.workflow_id,
            description=definition.description,
            change_log=definition.change_log,
            created_at=definition.created_at,
            created_by=definition.created_by,
            source_version_id=definition.source_version_id,
        )
        self.db.add(orm)
        self.db.commit()
        
        logger.info(f"[WorkflowVersionRepository] Created definition: {definition.definition_id}")
        return definition
    
    def get_definition_by_id(self, definition_id: str) -> Optional[WorkflowDefinition]:
        """根据 ID 获取定义"""
        row = (
            self.db.query(WorkflowDefinitionORM)
            .filter(WorkflowDefinitionORM.definition_id == definition_id)
            .first()
        )
        if not row:
            return None
        row_any = cast(Any, row)
        return WorkflowDefinition(
            definition_id=cast(str, row_any.definition_id),
            workflow_id=cast(str, row_any.workflow_id),
            description=cast(Optional[str], row_any.description),
            change_log=cast(Optional[str], row_any.change_log),
            created_at=cast(datetime, row_any.created_at),
            created_by=cast(Optional[str], row_any.created_by),
            source_version_id=cast(Optional[str], row_any.source_version_id),
        )
    
    def list_definitions_by_workflow(
        self,
        workflow_id: str,
        limit: int = 100
    ) -> List[WorkflowDefinition]:
        """列出工作流的所有定义"""
        rows = (
            self.db.query(WorkflowDefinitionORM)
            .filter(WorkflowDefinitionORM.workflow_id == workflow_id)
            .order_by(WorkflowDefinitionORM.created_at.desc())
            .limit(limit)
            .all()
        )
        out: List[WorkflowDefinition] = []
        for r in rows:
            row_any = cast(Any, r)
            out.append(
                WorkflowDefinition(
                    definition_id=cast(str, row_any.definition_id),
                    workflow_id=cast(str, row_any.workflow_id),
                    description=cast(Optional[str], row_any.description),
                    change_log=cast(Optional[str], row_any.change_log),
                    created_at=cast(datetime, row_any.created_at),
                    created_by=cast(Optional[str], row_any.created_by),
                    source_version_id=cast(Optional[str], row_any.source_version_id),
                )
            )
        return out
    
    # ==================== Version Operations ====================
    
    def create_version(self, version: WorkflowVersion) -> WorkflowVersion:
        """创建版本"""
        orm = WorkflowVersionORM(
            version_id=version.version_id,
            workflow_id=version.workflow_id,
            definition_id=version.definition_id,
            version_number=version.version_number,
            dag_json=version.dag.model_dump_json(),
            checksum=version.checksum,
            state=version.state.value,
            description=version.description,
            change_notes=version.change_notes,
            created_at=version.created_at,
            created_by=version.created_by,
            published_at=version.published_at,
            published_by=version.published_by,
        )
        self.db.add(orm)
        self.db.commit()
        
        logger.info(f"[WorkflowVersionRepository] Created version: {version.version_id}")
        return version
    
    def get_version_by_id(self, version_id: str) -> Optional[WorkflowVersion]:
        """根据 ID 获取版本"""
        row = (
            self.db.query(WorkflowVersionORM)
            .filter(WorkflowVersionORM.version_id == version_id)
            .first()
        )
        if not row:
            return None
        return self._deserialize_version_from_orm(row)
    
    def get_version_by_number(
        self,
        workflow_id: str,
        version_number: str
    ) -> Optional[WorkflowVersion]:
        """根据版本号获取版本"""
        row = (
            self.db.query(WorkflowVersionORM)
            .filter(
                WorkflowVersionORM.workflow_id == workflow_id,
                WorkflowVersionORM.version_number == version_number,
            )
            .first()
        )
        if not row:
            return None
        return self._deserialize_version_from_orm(row)
    
    def list_versions_by_workflow(
        self,
        workflow_id: str,
        state: Optional[WorkflowVersionState] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[WorkflowVersion]:
        """列出工作流的所有版本"""
        q = self.db.query(WorkflowVersionORM).filter(WorkflowVersionORM.workflow_id == workflow_id)
        if state:
            q = q.filter(WorkflowVersionORM.state == state.value)
        rows = (
            q.order_by(WorkflowVersionORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._deserialize_version_from_orm(r) for r in rows]

    def count_versions_by_workflow(
        self,
        workflow_id: str,
        state: Optional[WorkflowVersionState] = None,
    ) -> int:
        q = self.db.query(WorkflowVersionORM).filter(WorkflowVersionORM.workflow_id == workflow_id)
        if state:
            q = q.filter(WorkflowVersionORM.state == state.value)
        return cast(int, q.count())
    
    def publish_version(
        self,
        version_id: str,
        published_by: Optional[str] = None
    ) -> Optional[WorkflowVersion]:
        """发布版本"""
        row = (
            self.db.query(WorkflowVersionORM)
            .filter(WorkflowVersionORM.version_id == version_id)
            .first()
        )
        if not row:
            return None
        setattr(row, "state", WorkflowVersionState.PUBLISHED.value)
        setattr(row, "published_at", datetime.now(UTC))
        setattr(row, "published_by", published_by)
        self.db.commit()
        
        logger.info(f"[WorkflowVersionRepository] Published version: {version_id}")
        return self.get_version_by_id(version_id)
    
    def deprecate_version(
        self,
        version_id: str,
        _deprecated_by: Optional[str] = None
    ) -> Optional[WorkflowVersion]:
        """弃用版本"""
        row = (
            self.db.query(WorkflowVersionORM)
            .filter(WorkflowVersionORM.version_id == version_id)
            .first()
        )
        if not row:
            return None
        setattr(row, "state", WorkflowVersionState.DEPRECATED.value)
        self.db.commit()
        
        logger.info(f"[WorkflowVersionRepository] Deprecated version: {version_id}")
        return self.get_version_by_id(version_id)
    
    def get_next_version_number(self, workflow_id: str) -> str:
        """获取下一个版本号（简化实现）"""
        row = (
            self.db.query(WorkflowVersionORM)
            .filter(WorkflowVersionORM.workflow_id == workflow_id)
            .order_by(WorkflowVersionORM.created_at.desc())
            .first()
        )
        if not row:
            return "1.0.0"
        current = row.version_number
        try:
            parts = current.split(".")
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
            return f"{major}.{minor}.{patch + 1}"
        except (ValueError, IndexError):
            return "1.0.0"
    
    def get_published_version(self, workflow_id: str) -> Optional[WorkflowVersion]:
        """获取工作流的已发布版本"""
        row = (
            self.db.query(WorkflowVersionORM)
            .filter(
                WorkflowVersionORM.workflow_id == workflow_id,
                WorkflowVersionORM.state == WorkflowVersionState.PUBLISHED.value,
            )
            .order_by(WorkflowVersionORM.published_at.desc())
            .first()
        )
        if not row:
            return None
        return self._deserialize_version_from_orm(row)
    
    def validate_dag_checksum(self, version_id: str) -> bool:
        """验证 DAG 校验和"""
        row = (
            self.db.query(WorkflowVersionORM)
            .filter(WorkflowVersionORM.version_id == version_id)
            .first()
        )
        if not row:
            return False
        import hashlib
        row_any = cast(Any, row)
        computed = hashlib.sha256(cast(str, row_any.dag_json).encode()).hexdigest()
        return cast(bool, computed == cast(str, row_any.checksum))
