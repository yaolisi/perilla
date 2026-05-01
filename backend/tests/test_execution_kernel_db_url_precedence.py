"""execution_kernel Database：EXECUTION_KERNEL_DB_URL 与 Settings.execution_kernel_db_url 优先级。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import config.settings as settings_module


def test_database_constructor_prefers_explicit_arg_over_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from execution_kernel.persistence.db import Database

    monkeypatch.setattr(
        settings_module,
        "settings",
        SimpleNamespace(execution_kernel_db_url="postgresql+asyncpg://settings-only/db"),
    )
    d = Database(database_url="postgresql+asyncpg://explicit/db")
    assert "explicit" in d.database_url


def test_database_constructor_prefers_settings_execution_kernel_db_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from execution_kernel.persistence.db import Database

    monkeypatch.setattr(
        settings_module,
        "settings",
        SimpleNamespace(execution_kernel_db_url="postgresql+asyncpg://from-settings/db"),
    )
    monkeypatch.delenv("EXECUTION_KERNEL_DB_URL", raising=False)
    d = Database()
    assert "from-settings" in d.database_url


def test_database_constructor_falls_back_to_env_when_settings_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from execution_kernel.persistence.db import Database

    monkeypatch.setattr(settings_module, "settings", SimpleNamespace(execution_kernel_db_url=""))
    monkeypatch.setenv("EXECUTION_KERNEL_DB_URL", "postgresql+asyncpg://from-env/db")
    d = Database()
    assert "from-env" in d.database_url
