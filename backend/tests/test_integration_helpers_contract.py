"""契约测试：tests.helpers 与生产 get_db / ExecutionManager 引擎约定一致。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from core.data.base import Base, DB_ENGINE_STATE_KEY, get_db
from core.workflows.governance import get_execution_manager, reset_execution_manager_singleton
from tests.helpers import (
    bind_execution_manager_to_session_factory,
    make_fastapi_app_router_only,
    session_factory_as_get_db_override,
)


def test_session_factory_override_sets_same_bind_on_state_as_session(tmp_path) -> None:
    db_file = tmp_path / "contract.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)

    app = make_fastapi_app_router_only()
    app.dependency_overrides[get_db] = session_factory_as_get_db_override(factory)

    @app.get("/probe")
    def _probe(
        request: Request,
        db: Annotated[Session, Depends(get_db)],
    ) -> dict[str, bool]:
        state_engine = getattr(request.state, DB_ENGINE_STATE_KEY, None)
        return {
            "state_is_bind": state_engine is db.get_bind(),
            "state_is_fixture_engine": state_engine is engine,
        }

    client = TestClient(app)
    body = client.get("/probe").json()
    assert body["state_is_bind"] is True
    assert body["state_is_fixture_engine"] is True


def test_bind_execution_manager_persist_engine_matches_session_factory(tmp_path) -> None:
    db_file = tmp_path / "em_contract.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    try:
        bind_execution_manager_to_session_factory(factory)
        with factory() as db:
            mgr = get_execution_manager()
            assert mgr._persist_engine is db.get_bind()
            assert mgr._persist_engine is engine
    finally:
        reset_execution_manager_singleton()


def test_helpers_joint_same_engine_for_route_and_execution_manager(tmp_path) -> None:
    """与工作流集成相同组合：get_db override + ExecutionManager 共用 fixture 引擎。"""
    db_file = tmp_path / "joint.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    try:
        bind_execution_manager_to_session_factory(factory)

        app = make_fastapi_app_router_only()
        app.dependency_overrides[get_db] = session_factory_as_get_db_override(factory)

        @app.get("/joint")
        def _joint(
            request: Request,
            db: Annotated[Session, Depends(get_db)],
        ) -> dict[str, bool]:
            mgr = get_execution_manager()
            state_e = getattr(request.state, DB_ENGINE_STATE_KEY, None)
            b = db.get_bind()
            pe = mgr._persist_engine
            return {
                "state_bind": state_e is b,
                "bind_persist": b is pe,
                "persist_fixture_engine": pe is engine,
            }

        client = TestClient(app)
        body = client.get("/joint").json()
        assert body["state_bind"] is True
        assert body["bind_persist"] is True
        assert body["persist_fixture_engine"] is True
    finally:
        reset_execution_manager_singleton()
