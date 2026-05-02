"""增强版：RBAC 解析、viewer 写拒绝、Trace W3C 解析（无重依赖）。"""
import pytest

from core.security.rbac import (
    PlatformRole,
    parse_api_key_list,
    resolve_role_from_api_key,
    viewer_http_access_denied,
    viewer_http_write_denied,
)
from middleware.request_trace import _trace_id_from_traceparent


def test_parse_api_key_list():
    assert parse_api_key_list("a, b") == {"a", "b"}
    assert parse_api_key_list("") == set()


def test_resolve_role_from_api_key():
    admin = {"adm"}
    op = {"op"}
    vw = {"vw"}
    assert (
        resolve_role_from_api_key("adm", admin, op, vw, PlatformRole.OPERATOR)
        == PlatformRole.ADMIN
    )
    assert (
        resolve_role_from_api_key("op", admin, op, vw, PlatformRole.VIEWER)
        == PlatformRole.OPERATOR
    )
    assert (
        resolve_role_from_api_key(None, admin, op, vw, PlatformRole.VIEWER)
        == PlatformRole.VIEWER
    )


@pytest.mark.parametrize(
    "method,path,denied",
    [
        ("POST", "/api/v1/workflows/foo", True),
        ("GET", "/api/v1/workflows/foo", False),
        ("POST", "/v1/chat/completions", False),
        ("POST", "/api/models/scan", True),
    ],
)
def test_viewer_write_denied(method, path, denied):
    assert viewer_http_write_denied(method, path) is denied


@pytest.mark.parametrize(
    "method,path,denied",
    [
        ("GET", "/api/events/instance/gi", True),
        ("HEAD", "/api/events/agent-session/s1", True),
        ("OPTIONS", "/api/events/instance/gi", False),
        ("GET", "/api/v1/workflows/w1", False),
        ("POST", "/api/v1/workflows/w1", True),
    ],
)
def test_viewer_access_denied_includes_events_observability(method, path, denied):
    assert viewer_http_access_denied(method, path) is denied


def test_traceparent_parses_trace_id():
    tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    assert _trace_id_from_traceparent(tp) == "4bf92f3577b34da6a3ce929d0e0e4736"
