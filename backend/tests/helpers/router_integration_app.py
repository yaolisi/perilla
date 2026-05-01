"""通用集成测试：挂载 api 模块路由；可选 SQLite ``get_db`` override 或仅路由（mock 集成）。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.errors import register_error_handlers
from tests.helpers.get_db_override import session_factory_as_get_db_override


def _include_router(router_or_module: Any) -> Any:
    """接受 api 模块（含 ``router``）或裸 ``APIRouter``。"""
    return router_or_module.router if hasattr(router_or_module, "router") else router_or_module


def make_fastapi_app_with_handlers(**kwargs: Any) -> FastAPI:
    """``FastAPI(**kwargs)`` + ``register_error_handlers``（不 ``include_router``）。"""
    app = FastAPI(**kwargs)
    register_error_handlers(app)
    return app


def make_fastapi_app_router_only(*router_or_modules: Any) -> FastAPI:
    """``register_error_handlers`` + 顺序 ``include_router``（无 DB；可传多个 api 模块或 APIRouter）。"""
    app = make_fastapi_app_with_handlers()
    for item in router_or_modules:
        app.include_router(_include_router(item))
    return app


def build_minimal_router_test_client(*router_or_modules: Any) -> TestClient:
    """仅路由 + 统一错误处理；单个或多个 router / 模块。"""
    return TestClient(make_fastapi_app_router_only(*router_or_modules))


def make_fastapi_app_with_db_override(session_factory: Any, router_module: Any) -> FastAPI:
    """``register_error_handlers`` + ``include_router`` + ``dependency_overrides[router_module.get_db]``。"""
    app = make_fastapi_app_router_only(router_module)
    app.dependency_overrides[router_module.get_db] = session_factory_as_get_db_override(session_factory)
    return app


def build_router_integration_test_client(session_factory: Any, router_module: Any) -> TestClient:
    """基于 fixture ``session_factory`` 与模块 ``get_db`` 的 TestClient。"""
    return TestClient(make_fastapi_app_with_db_override(session_factory, router_module))
