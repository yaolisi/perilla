"""工作流集成测试：全局 ExecutionManager 队列持久化与 fixture Session 使用同一引擎。"""

from __future__ import annotations

from core.workflows.governance import get_execution_manager, reset_execution_manager_singleton


def bind_execution_manager_to_session_factory(session_factory) -> None:
    """重置单例并将 persist_engine 设为 session_factory 的 bind（与 Depends(get_db) override 一致）。"""
    reset_execution_manager_singleton()
    with session_factory() as db:
        persist_bind = db.get_bind()
    get_execution_manager(persist_engine=persist_bind)
