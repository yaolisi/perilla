"""
Skill v1 ORM CRUD.
使用 platform.db 与系统其他数据统一存储。
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, cast

from core.data.base import db_session
from core.data.models.skill import Skill as SkillORM
from log import logger
from core.skills.models import Skill, SkillType


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SkillStore:
    """Skill 存储（使用 SQLAlchemy ORM）"""

    def create(
        self,
        name: str,
        description: str = "",
        category: str = "",
        type: SkillType = "prompt",
        definition: Optional[Dict[str, Any]] = None,
        input_schema: Optional[Dict[str, Any]] = None,
        enabled: bool = True,
        skill_id: Optional[str] = None,
    ) -> Skill:
        """创建 Skill"""
        skill_id = skill_id or f"skill_{uuid.uuid4().hex[:12]}"
        definition = definition or {}
        input_schema = input_schema or {"type": "object", "properties": {}, "required": []}

        with db_session() as db:
            skill_orm = SkillORM(
                id=skill_id,
                name=name,
                description=description,
                category=category,
                type=type,
                definition=json.dumps(definition),
                input_schema=json.dumps(input_schema),
                enabled=1 if enabled else 0,
            )
            db.add(skill_orm)

        out = self.get(skill_id)
        assert out is not None, "skill just inserted"
        return out

    def get(self, skill_id: str) -> Optional[Skill]:
        """获取 Skill"""
        with db_session() as db:
            skill_orm = db.query(SkillORM).filter(SkillORM.id == skill_id).first()
            if skill_orm:
                return self._orm_to_skill(skill_orm)
        return None

    def list_all(self, enabled_only: bool = False) -> List[Skill]:
        """列出所有 Skill"""
        with db_session() as db:
            query = db.query(SkillORM)
            if enabled_only:
                query = query.filter(SkillORM.enabled == 1)
            rows = query.order_by(SkillORM.updated_at.desc()).all()
            return [self._orm_to_skill(r) for r in rows]

    def update(
        self,
        skill_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        type: Optional[SkillType] = None,
        definition: Optional[Dict[str, Any]] = None,
        input_schema: Optional[Dict[str, Any]] = None,
        enabled: Optional[bool] = None,
    ) -> Optional[Skill]:
        """更新 Skill"""
        with db_session() as db:
            skill_orm = db.query(SkillORM).filter(SkillORM.id == skill_id).first()
            if not skill_orm:
                return None
            orm = cast(Any, skill_orm)

            if name is not None:
                orm.name = name
            if description is not None:
                orm.description = description
            if category is not None:
                orm.category = category
            if type is not None:
                orm.type = type
            if definition is not None:
                orm.definition = json.dumps(definition)
            if input_schema is not None:
                orm.input_schema = json.dumps(input_schema)
            if enabled is not None:
                orm.enabled = 1 if enabled else 0

        return self.get(skill_id)

    def delete(self, skill_id: str) -> bool:
        """删除 Skill"""
        with db_session() as db:
            skill_orm = db.query(SkillORM).filter(SkillORM.id == skill_id).first()
            if skill_orm:
                db.delete(skill_orm)
                return True
        return False

    def _orm_to_skill(self, skill_orm: Any) -> Skill:
        """ORM 对象转 Skill"""
        orm = cast(Any, skill_orm)
        return Skill(
            id=str(orm.id),
            name=str(orm.name),
            description=str(orm.description or ""),
            category=str(orm.category or ""),
            type=cast(SkillType, orm.type),
            definition=json.loads(cast(str, orm.definition)) if orm.definition else {},
            input_schema=json.loads(cast(str, orm.input_schema)) if orm.input_schema else {},
            enabled=bool(orm.enabled),
            created_at=cast(datetime, orm.created_at) if orm.created_at else _utc_now(),
            updated_at=cast(datetime, orm.updated_at) if orm.updated_at else _utc_now(),
        )


_store: Optional[SkillStore] = None


def get_skill_store() -> SkillStore:
    """获取 Skill 存储单例"""
    global _store
    if _store is None:
        _store = SkillStore()
    return _store
