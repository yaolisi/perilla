"""生产环境关闭公开 OpenAPI（攻击面收敛）。"""

from __future__ import annotations

import pytest

import main as main_mod


def test_fastapi_openapi_kwargs_debug_always_exposes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main_mod.settings, "debug", True)
    monkeypatch.setattr(main_mod.settings, "openapi_public_enabled", False)
    assert main_mod._fastapi_openapi_kwargs() == {}


def test_fastapi_openapi_kwargs_prod_hidden_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main_mod.settings, "debug", False)
    monkeypatch.setattr(main_mod.settings, "openapi_public_enabled", False)
    assert main_mod._fastapi_openapi_kwargs() == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }


def test_fastapi_openapi_kwargs_prod_opt_in(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main_mod.settings, "debug", False)
    monkeypatch.setattr(main_mod.settings, "openapi_public_enabled", True)
    assert main_mod._fastapi_openapi_kwargs() == {}
