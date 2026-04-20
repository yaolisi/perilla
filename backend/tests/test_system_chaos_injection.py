import asyncio

import pytest
from sqlalchemy.exc import OperationalError


def test_sqlite_lock_conflict_commit_raises_and_rolls_back(monkeypatch):
    from core.data import base as db_base

    class FakeSession:
        def __init__(self):
            self.rollback_called = False
            self.close_called = False

        def commit(self):
            raise OperationalError("COMMIT", {}, RuntimeError("database is locked"))

        def rollback(self):
            self.rollback_called = True

        def close(self):
            self.close_called = True

    holder = {}

    def _session_factory():
        s = FakeSession()
        holder["s"] = s
        return s

    monkeypatch.setattr(db_base, "SessionLocal", _session_factory)

    with pytest.raises(OperationalError):
        with db_base.db_session():
            _ = "trigger-commit-on-exit"
    s = holder["s"]
    assert s.rollback_called is True
    assert s.close_called is True


def test_workflow_debug_recent_events_empty_source():
    import core.workflows.debug_runtime as debug_rt

    class FakeStore:
        def __init__(self, _session):
            self._session = _session

        async def get_latest_events(self, instance_id, limit=80):
            await asyncio.sleep(0)
            return []

    class _AsyncSessionCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            # 测试用：不吞异常
            return False

    class FakeDB:
        def async_session(self):
            return _AsyncSessionCtx()

    out = asyncio.run(
        debug_rt.recent_events_debug(
            "inst-1",
            limit=10,
            database_cls=FakeDB,
            event_store_cls=FakeStore,
        )
    )
    assert out == []


def test_workflow_debug_recent_events_corrupted_source():
    import core.workflows.debug_runtime as debug_rt

    class BrokenEvent:
        pass

    class FakeStore:
        def __init__(self, _session):
            self._session = _session

        async def get_latest_events(self, instance_id, limit=80):
            await asyncio.sleep(0)
            return [BrokenEvent()]

    class _AsyncSessionCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            # 测试用：不吞异常
            return False

    class FakeDB:
        def async_session(self):
            return _AsyncSessionCtx()

    out = asyncio.run(
        debug_rt.recent_events_debug(
            "inst-1",
            limit=10,
            database_cls=FakeDB,
            event_store_cls=FakeStore,
        )
    )
    assert isinstance(out, list)
    assert out
    assert "_error" in out[0]


def test_workflow_debug_kernel_snapshot_degrades_on_exception():
    import core.workflows.debug_runtime as debug_rt

    class FakeDB:
        pass

    class FakeAdapter:
        @staticmethod
        async def extract_execution_result_from_kernel(graph_instance_id, kernel_db):
            raise RuntimeError("kernel db unavailable")

    out = asyncio.run(
        debug_rt.kernel_debug_snapshot(
            "graph-1",
            database_cls=FakeDB,
            graph_adapter=FakeAdapter,
        )
    )
    assert "_error" in out

