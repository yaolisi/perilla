"""execution_kernel 连接池参数与 Settings 对齐。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from execution_kernel.persistence import db as ek_db


def test_sqlalchemy_pool_kwargs_uses_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "config.settings.settings",
        SimpleNamespace(
            db_pool_recycle_seconds=900,
            db_max_overflow=5,
            db_pool_size=8,
            db_pool_timeout_seconds=42.0,
        ),
        raising=False,
    )
    kw = ek_db._sqlalchemy_pool_kwargs("postgresql+asyncpg://u:p@h/db")
    assert kw["pool_recycle"] == 900
    assert kw["max_overflow"] == 5
    assert kw["pool_size"] == 8
    assert kw["pool_timeout"] == 42.0


def test_sqlalchemy_pool_kwargs_sqlite_no_pool_size():
    kw = ek_db._sqlalchemy_pool_kwargs("sqlite+aiosqlite:///tmp/x.db")
    assert kw == {"pool_pre_ping": True}
