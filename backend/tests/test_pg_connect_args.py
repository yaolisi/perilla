"""PostgreSQL connect_args 合并（超时）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.data import pg_connect_args as m


def test_merge_skips_non_postgresql():
    assert m.merge_postgresql_connect_args("sqlite:///x.db", sync_psycopg=True) == {}
    assert m.merge_postgresql_connect_args("", sync_psycopg=False) == {}


def test_merge_psycopg_includes_timeouts(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "config.settings.settings",
        SimpleNamespace(db_connect_timeout_seconds=12, db_statement_timeout_ms=15000),
        raising=False,
    )
    out = m.merge_postgresql_connect_args("postgresql+psycopg2://u:p@h/db", sync_psycopg=True)
    assert out["connect_timeout"] == 12
    assert "-c statement_timeout=15000" in out["options"]


def test_merge_asyncpg_statement_timeout(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "config.settings.settings",
        SimpleNamespace(db_connect_timeout_seconds=9, db_statement_timeout_ms=42000),
        raising=False,
    )
    out = m.merge_postgresql_connect_args("postgresql+asyncpg://u:p@h/db", sync_psycopg=False)
    assert out["timeout"] == 9.0
    assert out["server_settings"]["statement_timeout"] == "42000"


def test_merge_statement_timeout_zero_omits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "config.settings.settings",
        SimpleNamespace(db_connect_timeout_seconds=10, db_statement_timeout_ms=0),
        raising=False,
    )
    out = m.merge_postgresql_connect_args("postgresql+psycopg2://u:p@h/db", sync_psycopg=True)
    assert "options" not in out
    assert out.get("connect_timeout") == 10
