"""
租户 HTTP 强制（显式 X-Tenant-Id）所覆盖的路由前缀。

与 TenantContextMiddleware、TenantApiKeyBindingMiddleware 共用，禁止在两处各写一份列表。
"""

from __future__ import annotations


def is_tenant_enforcement_protected_path(path: str) -> bool:
    """当 TENANT_ENFORCEMENT_ENABLED / TENANT_API_KEY_BINDING_ENABLED 开启时，须命中此前缀集合之一。"""
    return (
        path.startswith("/api/v1/workflows")
        or path.startswith("/api/v1/audit")
        or path.startswith("/api/system")
    )
