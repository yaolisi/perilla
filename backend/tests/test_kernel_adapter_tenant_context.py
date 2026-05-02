"""Execution Kernel 适配器：会话租户注入 global_context / runtime_context。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.agent_runtime.session import DEFAULT_AGENT_SESSION_TENANT_ID
from core.execution.adapters.kernel_adapter import _session_tenant_id

pytestmark = pytest.mark.tenant_isolation


def test_session_tenant_id_strips_and_falls_back() -> None:
    s = MagicMock()
    s.tenant_id = "  acme  "
    assert _session_tenant_id(s) == "acme"

    s.tenant_id = None
    assert _session_tenant_id(s) == DEFAULT_AGENT_SESSION_TENANT_ID

    s.tenant_id = ""
    assert _session_tenant_id(s) == DEFAULT_AGENT_SESSION_TENANT_ID
