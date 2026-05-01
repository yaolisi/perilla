"""租户强制路径前缀须与中间件一致（单一入口 middleware/tenant_paths.py）。"""

from __future__ import annotations

from middleware.tenant_paths import is_tenant_enforcement_protected_path


def test_tenant_enforcement_protected_paths_examples():
    assert is_tenant_enforcement_protected_path("/api/v1/workflows/x")
    assert is_tenant_enforcement_protected_path("/api/v1/audit/rec")
    assert is_tenant_enforcement_protected_path("/api/system/runtime")
    assert not is_tenant_enforcement_protected_path("/api/v1/chat/stream")
    assert not is_tenant_enforcement_protected_path("/health")
