from core.mcp.http_client import _parse_legacy_endpoint_url


def test_parse_endpoint_plain() -> None:
    assert _parse_legacy_endpoint_url("https://example.com/msg") == "https://example.com/msg"


def test_parse_endpoint_json_string() -> None:
    assert _parse_legacy_endpoint_url('"https://example.com/msg"') == "https://example.com/msg"


def test_parse_endpoint_json_object() -> None:
    assert (
        _parse_legacy_endpoint_url('{"uri": "https://example.com/x"}') == "https://example.com/x"
    )
