from __future__ import annotations

from starlette.requests import Request

from api.error_i18n import _resolve_locale, resolve_accept_language_for_sse


def _make_request(*, query_string: bytes = b"", accept_language: str | None = "en-US") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if accept_language:
        headers.append((b"accept-language", accept_language.encode("utf-8")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/t",
        "raw_path": b"/t",
        "query_string": query_string,
        "headers": headers,
        "client": ("127.0.0.1", 0),
        "server": ("test", 80),
    }
    return Request(scope)


def test_resolve_locale_defaults_to_english_for_empty_header() -> None:
    assert _resolve_locale(None) == "en"
    assert _resolve_locale("") == "en"


def test_resolve_locale_prefers_highest_q_language() -> None:
    assert _resolve_locale("en-US;q=0.9, zh-CN;q=0.8") == "en"
    assert _resolve_locale("en-US;q=0.5, zh-CN;q=0.9") == "zh"


def test_resolve_locale_handles_wildcard_and_invalid_q() -> None:
    assert _resolve_locale("*") == "en"
    assert _resolve_locale("zh-CN;q=abc, en-US;q=0.7") == "en"
    assert _resolve_locale("*, zh-CN;q=0.9") == "zh"


def test_resolve_accept_language_for_sse_prefers_explicit_lang_over_header() -> None:
    req_en_header = _make_request(query_string=b"", accept_language="en-US,en;q=0.9")
    assert resolve_accept_language_for_sse(req_en_header, "zh") == "zh-CN, zh;q=0.9"
    req_zh_header = _make_request(query_string=b"", accept_language="zh-CN, zh;q=0.9")
    assert resolve_accept_language_for_sse(req_zh_header, "en") == "en-US, en;q=0.9"


def test_resolve_accept_language_for_sse_falls_back_to_accept_language_header() -> None:
    req = _make_request(query_string=b"", accept_language="zh-CN, zh;q=0.9")
    assert resolve_accept_language_for_sse(req, None) == "zh-CN, zh;q=0.9"


def test_resolve_accept_language_for_sse_lang_none_uses_header_even_when_lang_empty_string() -> None:
    """Explicit empty lang still triggers zh/en branches only when non-empty after strip."""
    req = _make_request(query_string=b"lang=", accept_language="de-DE, de;q=0.9")
    assert resolve_accept_language_for_sse(req, "") == "de-DE, de;q=0.9"

