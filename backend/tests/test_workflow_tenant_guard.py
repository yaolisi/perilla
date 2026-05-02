from types import SimpleNamespace

import pytest

from core.workflows.tenant_guard import resolve_tenant_id, namespace_matches_tenant

pytestmark = pytest.mark.tenant_isolation


def test_resolve_tenant_id_from_request_state():
    request = SimpleNamespace(state=SimpleNamespace(tenant_id="tenant-a"))
    assert resolve_tenant_id(request) == "tenant-a"


def test_resolve_tenant_id_falls_back_to_default():
    request = SimpleNamespace(state=SimpleNamespace(tenant_id=""))
    assert resolve_tenant_id(request, default_tenant="tenant-default") == "tenant-default"


def test_namespace_matches_tenant_exact_only():
    assert namespace_matches_tenant("tenant-a", "tenant-a") is True
    assert namespace_matches_tenant("tenant-a", "tenant-b") is False
