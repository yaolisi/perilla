"""
MCP 控制面 API：多租户 + SQLite 集成（跨租户 404、创建归属、同租户 tools/skill-previews/import mock 成功路径）。

说明：生产网关应在可信边界把租户写入 request.state；本测试用中间件将 X-Tenant-Id
写入 state，以模拟该契约（resolve_api_tenant_id 不直接读取请求头）。
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api import mcp as mcp_api
from core.data.base import Base
from core.data.models.mcp_server import McpServer
from config.settings import settings
from core.mcp.persistence import create_mcp_server
from core.security.deps import require_authenticated_platform_admin
from tests.helpers import make_fastapi_app_router_only

pytestmark = pytest.mark.tenant_isolation


def _bind_test_db(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "mcp_api_tenant.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine, tables=[McpServer.__table__])

    SessionLocalTest = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    @contextmanager
    def test_db_session(retry_count: int = 3, retry_delay: float = 0.1):
        _ = (retry_count, retry_delay)
        db = SessionLocalTest()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr("core.mcp.persistence.db_session", test_db_session)


def _client_for_mcp(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = make_fastapi_app_router_only(mcp_api)

    @app.middleware("http")
    async def _trusted_tenant_from_gateway(request: Request, call_next):  # type: ignore[no-untyped-def]
        hdr = (request.headers.get("X-Tenant-Id") or "").strip()
        request.state.tenant_id = hdr if hdr else None
        return await call_next(request)

    app.dependency_overrides[require_authenticated_platform_admin] = lambda: None
    return TestClient(app)


@pytest.fixture()
def tenant_mcp_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _bind_test_db(tmp_path, monkeypatch)
    create_mcp_server(
        name="Alpha MCP",
        command=["true"],
        server_id="srv_tenant_alpha",
        tenant_id="tenant_alpha",
        description="",
    )
    create_mcp_server(
        name="Beta MCP",
        command=["true"],
        server_id="srv_tenant_beta",
        tenant_id="tenant_beta",
        description="",
    )
    create_mcp_server(
        name="Default NS MCP",
        command=["true"],
        server_id="srv_default_ns",
        tenant_id="default",
        description="",
    )
    return _client_for_mcp(monkeypatch)


def test_mcp_list_servers_scoped_per_tenant(tenant_mcp_db: TestClient) -> None:
    client = tenant_mcp_db
    ra = client.get("/api/mcp/servers", headers={"X-Tenant-Id": "tenant_alpha"})
    assert ra.status_code == 200
    ids_a = {row["id"] for row in ra.json()["data"]}
    assert ids_a == {"srv_tenant_alpha"}

    rb = client.get("/api/mcp/servers", headers={"X-Tenant-Id": "tenant_beta"})
    assert rb.status_code == 200
    ids_b = {row["id"] for row in rb.json()["data"]}
    assert ids_b == {"srv_tenant_beta"}


def test_mcp_get_server_cross_tenant_returns_404(tenant_mcp_db: TestClient) -> None:
    client = tenant_mcp_db
    r = client.get("/api/mcp/servers/srv_tenant_beta", headers={"X-Tenant-Id": "tenant_alpha"})
    assert r.status_code == 404


def test_mcp_update_server_cross_tenant_returns_404(tenant_mcp_db: TestClient) -> None:
    client = tenant_mcp_db
    r = client.put(
        "/api/mcp/servers/srv_tenant_beta",
        headers={"X-Tenant-Id": "tenant_alpha"},
        json={"name": "Should Not Apply"},
    )
    assert r.status_code == 404


def test_mcp_delete_server_cross_tenant_returns_404(tenant_mcp_db: TestClient) -> None:
    client = tenant_mcp_db
    r = client.delete(
        "/api/mcp/servers/srv_tenant_beta",
        headers={"X-Tenant-Id": "tenant_alpha"},
    )
    assert r.status_code == 404


def test_mcp_cross_tenant_mutations_do_not_touch_other_tenant_rows(tenant_mcp_db: TestClient) -> None:
    """跨租户 PUT/DELETE 仅 404，不得修改或删除对方命名空间下的 ORM 行。"""
    client = tenant_mcp_db
    client.delete(
        "/api/mcp/servers/srv_tenant_beta",
        headers={"X-Tenant-Id": "tenant_alpha"},
    )
    client.put(
        "/api/mcp/servers/srv_tenant_beta",
        headers={"X-Tenant-Id": "tenant_alpha"},
        json={"name": "Hijack Attempt"},
    )
    rb = client.get("/api/mcp/servers/srv_tenant_beta", headers={"X-Tenant-Id": "tenant_beta"})
    assert rb.status_code == 200
    body = rb.json()
    assert body["id"] == "srv_tenant_beta"
    assert body["name"] == "Beta MCP"


def test_mcp_server_tools_same_tenant_ok_with_mock_fetch(tenant_mcp_db: TestClient) -> None:
    """本租户 tools 路由：查库成功后可在 mock 下发 200（不落真实 MCP）。"""
    client = tenant_mcp_db
    with patch("api.mcp.fetch_tools_for_server_config", new_callable=AsyncMock, return_value=[]):
        r = client.get(
            "/api/mcp/servers/srv_tenant_alpha/tools",
            headers={"X-Tenant-Id": "tenant_alpha"},
        )
    assert r.status_code == 200
    payload = r.json()
    assert payload["server_id"] == "srv_tenant_alpha"
    assert payload["tools"] == []


def test_mcp_skill_previews_same_tenant_ok_with_mock(tenant_mcp_db: TestClient) -> None:
    client = tenant_mcp_db
    with patch("api.mcp.skill_previews_for_server", new_callable=AsyncMock, return_value=[]):
        r = client.get(
            "/api/mcp/servers/srv_tenant_alpha/skill-previews",
            headers={"X-Tenant-Id": "tenant_alpha"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["server_id"] == "srv_tenant_alpha"
    assert body["skill_previews"] == []


def test_mcp_import_tools_same_tenant_ok_with_mock(tenant_mcp_db: TestClient) -> None:
    client = tenant_mcp_db
    empty_import = {"imported": [], "skipped_existing": [], "errors": []}
    with patch("api.mcp.import_mcp_tools_as_skills", new_callable=AsyncMock, return_value=empty_import):
        r = client.post(
            "/api/mcp/servers/srv_tenant_alpha/import-tools",
            headers={"X-Tenant-Id": "tenant_alpha"},
            json={},
        )
    assert r.status_code == 200
    assert r.json() == empty_import


def test_mcp_create_server_only_visible_in_own_tenant(tenant_mcp_db: TestClient) -> None:
    """POST /servers 写入的租户应与请求上下文一致，其它租户列表不可见。"""
    client = tenant_mcp_db
    r = client.post(
        "/api/mcp/servers",
        headers={"X-Tenant-Id": "tenant_gamma"},
        json={
            "name": "Gamma Created",
            "description": "",
            "transport": "stdio",
            "command": ["true"],
            "enabled": True,
        },
    )
    assert r.status_code == 200
    new_id = r.json()["id"]
    assert new_id

    gamma_list = client.get("/api/mcp/servers", headers={"X-Tenant-Id": "tenant_gamma"})
    assert gamma_list.status_code == 200
    assert new_id in {row["id"] for row in gamma_list.json()["data"]}

    alpha_list = client.get("/api/mcp/servers", headers={"X-Tenant-Id": "tenant_alpha"})
    assert alpha_list.status_code == 200
    assert new_id not in {row["id"] for row in alpha_list.json()["data"]}


def test_mcp_list_without_tenant_header_uses_default_namespace(tenant_mcp_db: TestClient) -> None:
    """未注入 X-Tenant-Id 时 state.tenant_id 为空，resolve_api_tenant_id 回落到 settings.tenant_default_id。"""
    client = tenant_mcp_db
    default_tid = str(getattr(settings, "tenant_default_id", "default") or "default").strip() or "default"
    assert default_tid == "default"

    r = client.get("/api/mcp/servers")
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()["data"]}
    assert ids == {"srv_default_ns"}

    r2 = client.get("/api/mcp/servers/srv_default_ns")
    assert r2.status_code == 200
    assert r2.json()["id"] == "srv_default_ns"


def test_mcp_server_tools_cross_tenant_returns_404_before_fetch(tenant_mcp_db: TestClient) -> None:
    """其它租户的 server_id：应在查库阶段 404，不触发 fetch_tools_for_server_config。"""
    client = tenant_mcp_db
    r = client.get(
        "/api/mcp/servers/srv_tenant_beta/tools",
        headers={"X-Tenant-Id": "tenant_alpha"},
    )
    assert r.status_code == 404


def test_mcp_skill_previews_cross_tenant_returns_404(tenant_mcp_db: TestClient) -> None:
    client = tenant_mcp_db
    r = client.get(
        "/api/mcp/servers/srv_tenant_beta/skill-previews",
        headers={"X-Tenant-Id": "tenant_alpha"},
    )
    assert r.status_code == 404


def test_mcp_import_tools_cross_tenant_returns_404(tenant_mcp_db: TestClient) -> None:
    client = tenant_mcp_db
    r = client.post(
        "/api/mcp/servers/srv_tenant_beta/import-tools",
        headers={"X-Tenant-Id": "tenant_alpha"},
        json={},
    )
    assert r.status_code == 404
