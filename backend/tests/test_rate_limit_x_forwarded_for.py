"""API 限流：可选忽略 X-Forwarded-For（直连公网防伪造）。"""

from __future__ import annotations

from unittest.mock import MagicMock

from starlette.applications import Starlette

from middleware.rate_limit import InMemoryRateLimitMiddleware


def _make_request(*, xff: str | None, client_host: str) -> MagicMock:
    req = MagicMock()

    def _get(name: str, default: str | None = None) -> str | None:
        if name.lower() == "x-forwarded-for":
            return xff if xff is not None else default
        return default

    req.headers.get = _get
    req.client.host = client_host
    req.state.user_id = ""
    return req


def test_identity_uses_xff_when_trust_enabled() -> None:
    app = Starlette()
    mw = InMemoryRateLimitMiddleware(
        app,
        requests_per_window=10,
        window_seconds=60,
        trust_x_forwarded_for=True,
    )
    req = _make_request(xff="203.0.113.9, 10.0.0.1", client_host="127.0.0.1")
    assert mw._identity(req) == "ip:203.0.113.9"


def test_identity_ignores_xff_when_trust_disabled() -> None:
    app = Starlette()
    mw = InMemoryRateLimitMiddleware(
        app,
        requests_per_window=10,
        window_seconds=60,
        trust_x_forwarded_for=False,
    )
    req = _make_request(xff="203.0.113.9", client_host="192.168.1.2")
    assert mw._identity(req) == "ip:192.168.1.2"
