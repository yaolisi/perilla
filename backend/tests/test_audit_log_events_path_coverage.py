"""audit_settings_cover_events_api_paths：与 AuditLogMiddleware 前缀语义对齐。"""

from __future__ import annotations

import pytest

from middleware.audit_log import audit_settings_cover_events_api_paths

pytestmark = pytest.mark.no_fallback


def test_audit_cover_events_false_when_audit_disabled(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "audit_log_enabled", False, raising=False)
    monkeypatch.setattr(settings, "audit_log_path_prefixes", "/api/events", raising=False)
    assert audit_settings_cover_events_api_paths() is False


def test_audit_cover_events_false_when_prefixes_empty(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "audit_log_enabled", True, raising=False)
    monkeypatch.setattr(settings, "audit_log_path_prefixes", "", raising=False)
    assert audit_settings_cover_events_api_paths() is False


def test_audit_cover_events_true_when_prefix_matches(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "audit_log_enabled", True, raising=False)
    monkeypatch.setattr(settings, "audit_log_path_prefixes", "/api/v1/workflows", raising=False)
    assert audit_settings_cover_events_api_paths() is False
    monkeypatch.setattr(settings, "audit_log_path_prefixes", "/api/events", raising=False)
    assert audit_settings_cover_events_api_paths() is True
    monkeypatch.setattr(settings, "audit_log_path_prefixes", "/api", raising=False)
    assert audit_settings_cover_events_api_paths() is True
