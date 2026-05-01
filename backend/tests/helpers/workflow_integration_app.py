"""工作流集成测试：最小 FastAPI + TestClient（与 fixture DB / ExecutionManager 对齐）。"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.helpers.router_integration_app import make_fastapi_app_with_db_override
from tests.helpers.workflow_execution_manager import bind_execution_manager_to_session_factory


def build_workflow_integration_test_client(
    session_factory: Any,
    workflows_api: Any,
    *,
    current_user: str = "u1",
) -> TestClient:
    """挂载 workflows 路由，注入 get_db override、ExecutionManager persist_engine、固定当前用户。"""
    bind_execution_manager_to_session_factory(session_factory)

    app = make_fastapi_app_with_db_override(session_factory, workflows_api)
    app.dependency_overrides[workflows_api.get_current_user] = lambda: current_user
    return TestClient(app)
