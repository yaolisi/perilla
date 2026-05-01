"""审计日志 client_ip：与 api_rate_limit_trust_x_forwarded_for 一致。"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from middleware import audit_log as audit_log_mod


def test_audit_client_ip_prefers_xff_when_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_log_mod.settings, "api_rate_limit_trust_x_forwarded_for", True)
    mw = audit_log_mod.AuditLogMiddleware(object())
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "GET",
        "path": "/api/x",
        "headers": [(b"x-forwarded-for", b"203.0.113.2, 10.0.0.1")],
        "client": ("192.168.0.1", 12345),
    }
    req = Request(scope)
    assert mw._client_ip(req) == "203.0.113.2"


def test_audit_client_ip_ignores_xff_when_untrusted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_log_mod.settings, "api_rate_limit_trust_x_forwarded_for", False)
    mw = audit_log_mod.AuditLogMiddleware(object())
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "GET",
        "path": "/api/x",
        "headers": [(b"x-forwarded-for", b"203.0.113.9")],
        "client": ("10.1.2.3", 12345),
    }
    req = Request(scope)
    assert mw._client_ip(req) == "10.1.2.3"
