from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api import system as system_api
from config.settings import settings
from core.models.descriptor import ModelDescriptor


def _descriptor(
    *,
    model_id: str,
    version: str | None = None,
) -> ModelDescriptor:
    return ModelDescriptor(
        id=model_id,
        name=model_id,
        provider="test",
        provider_model_id=model_id,
        runtime="test",
        version=version,
    )


def test_phase3_cluster_scaling_requires_multi_runtime_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system_api, "get_runtime_max_cached_local_runtimes", lambda: 1)
    assert system_api._detect_cluster_scaling_capability() is False
    monkeypatch.setattr(system_api, "get_runtime_max_cached_local_runtimes", lambda: 2)
    assert system_api._detect_cluster_scaling_capability() is True


def test_phase3_model_governance_requires_matrix_models_and_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system_api, "build_plugin_compatibility_matrix", lambda: {"ok": True})
    reg = MagicMock()
    reg.list_models.return_value = [
        _descriptor(model_id="m1", version="1.0.0"),
        _descriptor(model_id="m2", version=""),
    ]
    monkeypatch.setattr(system_api, "get_model_registry", lambda: reg)
    assert system_api._detect_model_version_governance_capability() is True

    reg.list_models.return_value = [_descriptor(model_id="m1", version="1.0.0")]
    assert system_api._detect_model_version_governance_capability() is False

    reg.list_models.return_value = [
        _descriptor(model_id="m1"),
        _descriptor(model_id="m2"),
    ]
    assert system_api._detect_model_version_governance_capability() is False


def test_phase3_model_governance_false_when_matrix_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> dict[str, str]:
        raise RuntimeError("matrix unavailable")

    monkeypatch.setattr(system_api, "build_plugin_compatibility_matrix", _boom)
    reg = MagicMock()
    reg.list_models.return_value = [
        _descriptor(model_id="m1", version="1"),
        _descriptor(model_id="m2", version="2"),
    ]
    monkeypatch.setattr(system_api, "get_model_registry", lambda: reg)
    assert system_api._detect_model_version_governance_capability() is False


def test_phase3_sso_requires_rbac_stack_or_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rbac_enabled", False, raising=False)
    monkeypatch.setattr(settings, "rbac_enforcement", False, raising=False)
    monkeypatch.setattr(settings, "tenant_enforcement_enabled", False, raising=False)
    assert system_api._detect_sso_integration_capability() is False

    monkeypatch.setattr(settings, "tenant_enforcement_enabled", True, raising=False)
    assert system_api._detect_sso_integration_capability() is True

    monkeypatch.setattr(settings, "tenant_enforcement_enabled", False, raising=False)
    monkeypatch.setattr(settings, "rbac_enabled", True, raising=False)
    monkeypatch.setattr(settings, "rbac_enforcement", True, raising=False)
    assert system_api._detect_sso_integration_capability() is True


def test_phase3_multimodal_requires_configured_default_models(monkeypatch: pytest.MonkeyPatch) -> None:
    class _StoreAsr:
        def get_setting(self, key: str, default: object = None) -> object:
            if key == "asrModelId":
                return " whisper-1 "
            return default

    monkeypatch.setattr(system_api, "get_system_settings_store", lambda: _StoreAsr())
    assert system_api._detect_multimodal_pilot_capability() is True

    class _StoreEmpty:
        def get_setting(self, key: str, default: object = None) -> object:
            return default

    monkeypatch.setattr(system_api, "get_system_settings_store", lambda: _StoreEmpty())
    assert system_api._detect_multimodal_pilot_capability() is False
