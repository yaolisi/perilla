"""
Tenant namespace guard for workflow control plane.
"""
from __future__ import annotations

from typing import Any


def resolve_tenant_id(request: Any, default_tenant: str = "default") -> str:
    tenant_id = getattr(getattr(request, "state", None), "tenant_id", None)
    tenant_id = (tenant_id or default_tenant or "default").strip()
    return tenant_id or "default"


def namespace_matches_tenant(namespace: str | None, tenant_id: str) -> bool:
    return (namespace or "").strip() == (tenant_id or "").strip()
