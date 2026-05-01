"""middleware.client_ip：解析客户端主机。"""

from __future__ import annotations

from starlette.requests import Request

from middleware.client_ip import client_host_from_request


def _req(headers: list[tuple[bytes, bytes]], client: tuple[str, int] | None) -> Request:
    scope: dict = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "GET",
        "path": "/",
        "headers": headers,
    }
    if client is not None:
        scope["client"] = client
    return Request(scope)


def test_trusted_uses_xff_first_hop() -> None:
    r = _req([(b"x-forwarded-for", b"203.0.113.1, 10.0.0.1")], ("127.0.0.1", 80))
    assert client_host_from_request(r, trust_x_forwarded_for=True) == "203.0.113.1"


def test_untrusted_ignores_xff() -> None:
    r = _req([(b"x-forwarded-for", b"203.0.113.1")], ("192.168.1.5", 80))
    assert client_host_from_request(r, trust_x_forwarded_for=False) == "192.168.1.5"


def test_empty_when_no_client_and_no_xff() -> None:
    r = _req([], None)
    assert client_host_from_request(r, trust_x_forwarded_for=False) == ""
