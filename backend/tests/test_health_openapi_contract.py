"""OpenAPI：健康检查路径与 Health 标签契约。"""

from __future__ import annotations

from fastapi.testclient import TestClient

import main as main_mod


def test_openapi_health_endpoints_use_health_tag_and_ready_documents_503() -> None:
    with TestClient(main_mod.app) as client:
        spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    for path in ("/api/health", "/api/health/live", "/api/health/ready"):
        assert path in paths, f"missing {path}"
        get_op = paths[path].get("get") or {}
        assert "Health" in (get_op.get("tags") or []), path
    ready = paths["/api/health/ready"]["get"]
    assert "503" in (ready.get("responses") or {})
