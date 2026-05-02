"""events API：instance 路径在 workflow_executions 有记录时按租户门禁。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api import events as events_api
from api.errors import APIException

pytestmark = pytest.mark.tenant_isolation


def test_require_graph_instance_tenant_scope_blocks_wrong_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    row = MagicMock()
    row.tenant_id = "tenant_owned"

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.first.return_value = row

    def fake_session():
        class CM:
            def __enter__(self):
                return fake_db

            def __exit__(self, *_args):
                return None

        return CM()

    monkeypatch.setattr(events_api, "db_session", fake_session)

    with pytest.raises(APIException) as ei:
        events_api._require_graph_instance_tenant_scope("gi_123", "other_tenant")
    assert ei.value.status_code == 404


def test_require_graph_instance_tenant_scope_allows_when_no_row(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.first.return_value = None

    def fake_session():
        class CM:
            def __enter__(self):
                return fake_db

            def __exit__(self, *_args):
                return None

        return CM()

    monkeypatch.setattr(events_api, "db_session", fake_session)
    events_api._require_graph_instance_tenant_scope("gi_orphan", "any_tenant")


def test_graph_instance_visible_to_tenant_false_when_row_other_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    row = MagicMock()
    row.tenant_id = "tenant_a"

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.first.return_value = row

    def fake_session():
        class CM:
            def __enter__(self):
                return fake_db

            def __exit__(self, *_args):
                return None

        return CM()

    monkeypatch.setattr(events_api, "db_session", fake_session)
    assert events_api._graph_instance_visible_to_tenant("gi_x", "tenant_b") is False


def test_graph_instance_visible_to_tenant_true_when_row_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    row = MagicMock()
    row.tenant_id = "tenant_a"

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.first.return_value = row

    def fake_session():
        class CM:
            def __enter__(self):
                return fake_db

            def __exit__(self, *_args):
                return None

        return CM()

    monkeypatch.setattr(events_api, "db_session", fake_session)
    assert events_api._graph_instance_visible_to_tenant("gi_x", "tenant_a") is True


def test_graph_instance_visible_to_tenant_true_when_no_row(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.first.return_value = None

    def fake_session():
        class CM:
            def __enter__(self):
                return fake_db

            def __exit__(self, *_args):
                return None

        return CM()

    monkeypatch.setattr(events_api, "db_session", fake_session)
    assert events_api._graph_instance_visible_to_tenant("gi_orphan", "any") is True
