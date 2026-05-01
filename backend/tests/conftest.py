from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# 与 requirements/base.txt 中 pytest-asyncio 配套，支持 @pytest.mark.asyncio
pytest_plugins = ("pytest_asyncio",)
from fastapi.testclient import TestClient

from api.errors import set_http_exception_fallback_observer
from api.stream_resume_store import StreamResumeStore
from config.settings import settings
from middleware.csrf_protection import CSRFMiddleware
from middleware.user_context import UserContextMiddleware
from tests.helpers import make_fastapi_app_router_only
from tests.helpers.chat_stream_helpers import chat_prime_csrf, chat_seed_stream_store

# 减轻部分环境下 OpenMP / 大依赖导入时的异常退出
os.environ.setdefault("OMP_NUM_THREADS", "1")


@pytest.fixture(autouse=True)
def _reset_workflow_execution_manager_singleton_after_test() -> Iterator[None]:
    """避免 ExecutionManager 全局单例（persist_engine）泄漏到下一测试。"""
    yield
    from core.workflows.governance import reset_execution_manager_singleton

    reset_execution_manager_singleton()


@pytest.fixture()
def fallback_probe() -> Iterator[list[tuple[int, str, str]]]:
    events: list[tuple[int, str, str]] = []

    def _observer(status: int, message: str, path: str) -> None:
        events.append((status, message, path))

    set_http_exception_fallback_observer(_observer)
    try:
        yield events
    finally:
        set_http_exception_fallback_observer(None)


@pytest.fixture()
def chat_stream_resume_client(monkeypatch: pytest.MonkeyPatch):
    """
    TestClient fixture for /v1/chat/completions/stream/resume integration tests.

    Includes:
    - patched in-memory StreamResumeStore
    - CSRF + UserContext middlewares
    - temporary chat_stream_resume/csrf settings overrides
    """
    from api import chat as chat_api

    test_store = StreamResumeStore(ttl_seconds=9999, max_sessions=50)
    monkeypatch.setattr(chat_api, "get_stream_resume_store", lambda: test_store)

    prev_resume = bool(getattr(settings, "chat_stream_resume_enabled", True))
    prev_csrf = bool(getattr(settings, "csrf_enabled", True))
    prev_cookie = getattr(settings, "csrf_cookie_name", "csrf_token")
    prev_header = getattr(settings, "csrf_header_name", "X-CSRF-Token")

    settings.chat_stream_resume_enabled = True
    settings.csrf_enabled = True
    settings.csrf_cookie_name = "csrf_token"
    settings.csrf_header_name = "X-CSRF-Token"

    app = make_fastapi_app_router_only(chat_api)
    app.add_middleware(UserContextMiddleware)
    app.add_middleware(CSRFMiddleware)

    @app.get("/_ping")
    def _ping() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    try:
        yield client, test_store
    finally:
        settings.chat_stream_resume_enabled = prev_resume
        settings.csrf_enabled = prev_csrf
        settings.csrf_cookie_name = prev_cookie
        settings.csrf_header_name = prev_header
