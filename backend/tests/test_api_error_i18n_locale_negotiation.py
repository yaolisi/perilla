from __future__ import annotations

from api.error_i18n import _resolve_locale


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

