"""execution_kernel 全局库关停。"""

from __future__ import annotations

import pytest

import execution_kernel.persistence.db as ek_db


@pytest.mark.asyncio
async def test_close_global_database_noop_when_uninitialized() -> None:
    ek_db._db = None
    await ek_db.close_global_database()


@pytest.mark.asyncio
async def test_close_global_database_clears_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []

    class _FakeDb:
        async def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(ek_db, "_db", _FakeDb())
    await ek_db.close_global_database()
    assert closed == [True]
    assert ek_db._db is None
