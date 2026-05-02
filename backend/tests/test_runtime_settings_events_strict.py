"""Runtime settings: eventsStrictWorkflowBinding ↔ get_events_strict_workflow_binding."""

import pytest

from core.system import runtime_settings as rs

pytestmark = pytest.mark.no_fallback


class _StoreNone:
    def get_setting(self, key: str):
        return None


class _StoreFalse:
    def get_setting(self, key: str):
        if key == "eventsStrictWorkflowBinding":
            return False
        return None


class _StoreTrue:
    def get_setting(self, key: str):
        if key == "eventsStrictWorkflowBinding":
            return True
        return None


def test_get_events_strict_workflow_binding_falls_back_to_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rs, "get_system_settings_store", lambda: _StoreNone())
    monkeypatch.setattr(rs.settings, "events_strict_workflow_binding", False, raising=False)
    assert rs.get_events_strict_workflow_binding() is False

    monkeypatch.setattr(rs.settings, "events_strict_workflow_binding", True, raising=False)
    assert rs.get_events_strict_workflow_binding() is True


def test_get_events_strict_workflow_binding_store_overrides_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rs.settings, "events_strict_workflow_binding", True, raising=False)
    monkeypatch.setattr(rs, "get_system_settings_store", lambda: _StoreFalse())
    assert rs.get_events_strict_workflow_binding() is False

    monkeypatch.setattr(rs.settings, "events_strict_workflow_binding", False, raising=False)
    monkeypatch.setattr(rs, "get_system_settings_store", lambda: _StoreTrue())
    assert rs.get_events_strict_workflow_binding() is True
