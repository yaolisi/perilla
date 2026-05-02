"""tenant_paths：受保护前缀集合契约（与 TenantContext / ApiKey 绑定共用）。"""

from __future__ import annotations

import pytest

from middleware.tenant_paths import is_tenant_enforcement_protected_path

pytestmark = pytest.mark.tenant_isolation


@pytest.mark.parametrize(
    ("path", "protected"),
    [
        ("/api/v1/workflows/w1", True),
        ("/api/v1/audit/events", True),
        ("/api/system/health", True),
        ("/v1/chat/completions", True),
        ("/api/sessions/s1", True),
        ("/api/memory/m1", True),
        ("/api/knowledge-bases/kb1", True),
        ("/api/agent-sessions/as1", True),
        ("/v1/vlm/upload", True),
        ("/api/mcp/servers", False),
        ("/api/skills/x/execute", False),
        ("/openapi.json", False),
        ("/health", False),
        ("/api/v1/other", False),
    ],
)
def test_tenant_enforcement_path_classification(path: str, protected: bool) -> None:
    assert is_tenant_enforcement_protected_path(path) is protected
