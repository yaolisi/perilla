"""单元测试：`api.errors._structured_http_exception_parts`（HTTPException 结构化 ``detail`` 合并）。"""

from __future__ import annotations

from api.errors import _structured_http_exception_parts


def test_merges_nested_details_with_top_level_extras() -> None:
    detail = {
        "code": "c1",
        "message": "msg",
        "details": {"field": "x", "n": 1},
        "unknown_fields": ["u"],
        "allowed_fields": ["a"],
    }
    code, message, merged = _structured_http_exception_parts(detail)
    assert code == "c1"
    assert message == "msg"
    assert merged == {"field": "x", "n": 1, "unknown_fields": ["u"], "allowed_fields": ["a"]}


def test_extras_override_nested_same_key() -> None:
    detail = {
        "code": "c",
        "message": "m",
        "details": {"overlap": "nested"},
        "overlap": "extra",
    }
    _, _, merged = _structured_http_exception_parts(detail)
    assert merged == {"overlap": "extra"}


def test_whitelist_style_only_top_level_extras() -> None:
    detail = {
        "code": "request_unknown_fields",
        "message": "Request contains unknown fields",
        "unknown_fields": ["bad"],
        "allowed_fields": ["ok"],
    }
    _, _, merged = _structured_http_exception_parts(detail)
    assert merged == {"unknown_fields": ["bad"], "allowed_fields": ["ok"]}


def test_nested_none_no_extras_returns_none() -> None:
    detail = {"code": "c", "message": "m"}
    _, _, merged = _structured_http_exception_parts(detail)
    assert merged is None


def test_nested_empty_dict_no_extras_returns_empty_dict() -> None:
    detail = {"code": "c", "message": "m", "details": {}}
    _, _, merged = _structured_http_exception_parts(detail)
    assert merged == {}


def test_non_dict_nested_with_extras_uses_extras_only() -> None:
    """非 dict 的 ``details`` 不合并进结果；顶层扩展键仍保留（与实现一致）。"""
    detail = {
        "code": "c",
        "message": "m",
        "details": [1, 2],
        "unknown_fields": ["u"],
    }
    _, _, merged = _structured_http_exception_parts(detail)
    assert merged == {"unknown_fields": ["u"]}


def test_non_dict_nested_without_extras_returns_none() -> None:
    detail = {"code": "c", "message": "m", "details": [1, 2]}
    _, _, merged = _structured_http_exception_parts(detail)
    assert merged is None
