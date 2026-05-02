"""
AgentSession 存储（ORM 版本）
并发优化：
1. 使用优化的 db_session（带重试机制）
2. 减少事务持有时间
3. 批量操作优化
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy import select, update, delete

from core.data.base import db_session
from core.data.models.session import AgentSession as AgentSessionORM
from log import logger
from core.types import Message
from core.events import get_event_bus

# 与 settings.tenant_default_id / X-Tenant-Id 回落一致
DEFAULT_AGENT_SESSION_TENANT_ID = "default"


class AgentSessionStateJsonMap(BaseModel):
    """AgentSession.state：会话结构化状态（协作块、工具观测等）；OpenAPI 具名 object。"""

    model_config = ConfigDict(extra="allow")


def agent_session_state_as_dict(sess_state: Any) -> Dict[str, Any]:
    """供持久化、协作合并与内核上下文使用的 dict 视图。"""
    if sess_state is None:
        return {}
    if isinstance(sess_state, AgentSessionStateJsonMap):
        return sess_state.model_dump(mode="python")
    if isinstance(sess_state, dict):
        return dict(sess_state)
    return {}


class AgentSession(BaseModel):
    session_id: str
    agent_id: str
    user_id: str = "default"
    tenant_id: str = DEFAULT_AGENT_SESSION_TENANT_ID
    trace_id: str = Field(default_factory=lambda: f"atrace_{uuid.uuid4().hex[:16]}")

    messages: List[Message] = Field(default_factory=list)
    step: int = 0
    status: str = "idle"  # running, finished, error, idle

    error_message: Optional[str] = None
    """上传文件时的工作目录（绝对路径），供后续同会话 run 时 file.read 使用。"""
    workspace_dir: Optional[str] = None
    # Structured state for recent tool observations (avoid parsing message text)
    state: AgentSessionStateJsonMap = Field(default_factory=AgentSessionStateJsonMap)
    
    # V2.6: Execution Kernel instance ID (for event stream replay/debug)
    kernel_instance_id: Optional[str] = None
    
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentSessionStore:
    """智能体运行会话存储（使用 SQLAlchemy ORM）"""

    def save_session(self, session: AgentSession) -> bool:
        """保存会话（UPSERT，优化并发写入）"""
        try:
            now = datetime.now(timezone.utc)
            tid = (getattr(session, "tenant_id", None) or DEFAULT_AGENT_SESSION_TENANT_ID).strip() or DEFAULT_AGENT_SESSION_TENANT_ID
            messages_json = json.dumps([m.model_dump() for m in session.messages])
            state_json = json.dumps(agent_session_state_as_dict(session.state), ensure_ascii=False)
            workspace_dir = getattr(session, "workspace_dir", None) or None

            # 转换 ISO 格式字符串为 datetime 对象
            created_at_dt = datetime.fromisoformat(session.created_at.replace('Z', '+00:00')) if isinstance(session.created_at, str) else session.created_at
            if isinstance(created_at_dt, str):
                created_at_dt = datetime.now(timezone.utc)

            # 使用优化的 db_session（自动重试）
            with db_session(retry_count=3, retry_delay=0.1) as db:
                existing = (
                    db.query(AgentSessionORM)
                    .filter(AgentSessionORM.session_id == session.session_id)
                    .first()
                )
                if existing is not None:
                    ex_tid = (getattr(existing, "tenant_id", None) or DEFAULT_AGENT_SESSION_TENANT_ID).strip() or DEFAULT_AGENT_SESSION_TENANT_ID
                    if existing.user_id != session.user_id or ex_tid != tid:
                        logger.warning(
                            "[AgentSessionStore] Refusing save: session_id=%s owned by other user/tenant",
                            session.session_id,
                        )
                        return False

                stmt = insert(AgentSessionORM).values(
                    session_id=session.session_id,
                    agent_id=session.agent_id,
                    user_id=session.user_id,
                    tenant_id=tid,
                    trace_id=session.trace_id,
                    status=session.status,
                    step=session.step,
                    messages_json=messages_json,
                    state_json=state_json,
                    error_message=session.error_message,
                    workspace_dir=workspace_dir,
                    kernel_instance_id=getattr(session, "kernel_instance_id", None),
                    created_at=created_at_dt,
                    updated_at=now,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["session_id"],
                    set_={
                        "trace_id": stmt.excluded.trace_id,
                        "status": stmt.excluded.status,
                        "step": stmt.excluded.step,
                        "messages_json": stmt.excluded.messages_json,
                        "state_json": stmt.excluded.state_json,
                        "error_message": stmt.excluded.error_message,
                        "workspace_dir": stmt.excluded.workspace_dir,
                        "kernel_instance_id": stmt.excluded.kernel_instance_id,
                        "updated_at": stmt.excluded.updated_at,
                    },
                )
                db.execute(stmt)
            self._emit_status_changed_event(session)
            return True
        except Exception as e:
            logger.error(f"[AgentSessionStore] save_session failed: {e}")
            return False

    def _emit_status_changed_event(self, session: AgentSession) -> None:
        payload = {
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "user_id": session.user_id,
            "tenant_id": getattr(session, "tenant_id", None) or DEFAULT_AGENT_SESSION_TENANT_ID,
            "trace_id": session.trace_id,
            "status": session.status,
            "step": session.step,
        }

        async def _publish() -> None:
            try:
                await get_event_bus().publish(
                    event_type="agent.status.changed",
                    payload=payload,
                    source="agent_session_store",
                )
            except Exception as exc:
                logger.debug("[AgentSessionStore] emit agent.status.changed failed: %s", exc)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_publish())
        except RuntimeError:
            try:
                asyncio.run(_publish())
            except Exception as exc:
                logger.warning("[AgentSessionStore] asyncio.run publish agent.status.changed failed: %s", exc)

    def get_session_principal(self, session_id: str) -> Optional[tuple[str, str]]:
        """若会话存在则返回 (user_id, tenant_id)，否则 None。用于检测 session_id 是否被其他租户占用。"""
        try:
            with db_session(retry_count=2, retry_delay=0.05) as db:
                row = db.query(AgentSessionORM).filter(AgentSessionORM.session_id == session_id).first()
                if row:
                    tid = (getattr(row, "tenant_id", None) or DEFAULT_AGENT_SESSION_TENANT_ID).strip() or DEFAULT_AGENT_SESSION_TENANT_ID
                    return (row.user_id, tid)
        except Exception as e:
            logger.error(f"[AgentSessionStore] get_session_principal failed: {e}")
        return None

    def get_session(
        self,
        session_id: str,
        *,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Optional[AgentSession]:
        """获取会话；若提供 user_id/tenant_id 则一并过滤（租户隔离）。"""
        try:
            # 使用只读事务，减少锁竞争
            with db_session(retry_count=2, retry_delay=0.05) as db:
                q = db.query(AgentSessionORM).filter(AgentSessionORM.session_id == session_id)
                if user_id is not None:
                    q = q.filter(AgentSessionORM.user_id == user_id)
                if tenant_id is not None:
                    q = q.filter(AgentSessionORM.tenant_id == tenant_id)
                session_orm = q.first()
                if session_orm:
                    return self._orm_to_session(session_orm)
        except Exception as e:
            logger.error(f"[AgentSessionStore] get_session failed: {e}")
        return None

    def _orm_to_session(self, session_orm: AgentSessionORM) -> AgentSession:
        """ORM 对象转 AgentSession"""
        messages_data = json.loads(session_orm.messages_json)
        messages = [Message(**m) for m in messages_data]
        state_raw: Dict[str, Any] = {}
        try:
            state_raw = json.loads(session_orm.state_json) if session_orm.state_json else {}
        except Exception:
            state_raw = {}
        if not isinstance(state_raw, dict):
            state_raw = {}
        state = AgentSessionStateJsonMap.model_validate(state_raw)

        orm_tid = getattr(session_orm, "tenant_id", None)
        eff_tid = (str(orm_tid).strip() if orm_tid else "") or DEFAULT_AGENT_SESSION_TENANT_ID

        return AgentSession(
            session_id=session_orm.session_id,
            agent_id=session_orm.agent_id,
            user_id=session_orm.user_id,
            tenant_id=eff_tid,
            trace_id=session_orm.trace_id or f"atrace_{session_orm.session_id}",
            status=session_orm.status,
            step=session_orm.step,
            messages=messages,
            error_message=session_orm.error_message,
            workspace_dir=session_orm.workspace_dir,
            state=state,
            kernel_instance_id=getattr(session_orm, "kernel_instance_id", None),
            created_at=session_orm.created_at.isoformat() if session_orm.created_at else datetime.now(timezone.utc).isoformat(),
            updated_at=session_orm.updated_at.isoformat() if session_orm.updated_at else datetime.now(timezone.utc).isoformat(),
        )

    def delete_message(
        self,
        session_id: str,
        message_index: int,
        *,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> bool:
        """删除会话中的一条消息"""
        try:
            session = self.get_session(session_id, user_id=user_id, tenant_id=tenant_id)
            if not session:
                return False

            if message_index < 0 or message_index >= len(session.messages):
                return False

            session.messages.pop(message_index)
            return self.save_session(session)
        except Exception as e:
            logger.error(f"[AgentSessionStore] delete_message failed: {e}")
            return False

    def delete_session(
        self,
        session_id: str,
        user_id: str = "default",
        tenant_id: str = DEFAULT_AGENT_SESSION_TENANT_ID,
    ) -> bool:
        """删除会话（原子操作）"""
        try:
            tid = (tenant_id or DEFAULT_AGENT_SESSION_TENANT_ID).strip() or DEFAULT_AGENT_SESSION_TENANT_ID
            with db_session(retry_count=3, retry_delay=0.1) as db:
                # 使用 DELETE 语句直接删除，避免先查后删的竞态
                result = db.execute(
                    delete(AgentSessionORM).where(
                        AgentSessionORM.session_id == session_id,
                        AgentSessionORM.user_id == user_id,
                        AgentSessionORM.tenant_id == tid,
                    )
                )
                # 检查是否删除了记录
                deleted_count = result.rowcount
                if deleted_count > 0:
                    logger.info(f"[AgentSessionStore] Deleted session {session_id}")
                    return True
                else:
                    logger.debug(f"[AgentSessionStore] Session {session_id} not found")
                    return False
        except Exception as e:
            logger.error(f"[AgentSessionStore] delete_session failed: {e}")
            return False

    def list_sessions(
        self,
        user_id: str = "default",
        limit: int = 50,
        agent_id: Optional[str] = None,
        tenant_id: str = DEFAULT_AGENT_SESSION_TENANT_ID,
    ) -> List[AgentSession]:
        """列出会话（分页查询优化，按租户过滤）"""
        sessions = []
        try:
            tid = (tenant_id or DEFAULT_AGENT_SESSION_TENANT_ID).strip() or DEFAULT_AGENT_SESSION_TENANT_ID
            # 使用只读模式，减少锁竞争
            with db_session(retry_count=2, retry_delay=0.05) as db:
                query = db.query(AgentSessionORM).filter(
                    AgentSessionORM.user_id == user_id,
                    AgentSessionORM.tenant_id == tid,
                )
                if agent_id:
                    query = query.filter(AgentSessionORM.agent_id == agent_id)
                # 使用索引排序（updated_at DESC）
                rows = query.order_by(AgentSessionORM.updated_at.desc()).limit(limit).all()
                for row in rows:
                    sessions.append(self._orm_to_session(row))
        except Exception as e:
            logger.error(f"[AgentSessionStore] list_sessions failed: {e}")
        return sessions


_store: Optional[AgentSessionStore] = None


def get_agent_session_store() -> AgentSessionStore:
    """获取 AgentSession 存储单例"""
    global _store
    if _store is None:
        _store = AgentSessionStore()
    return _store
