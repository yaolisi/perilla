"""工作流执行 SSE：错误帧 message 随 sse_accept_language 本地化。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

import api.workflows as workflows_api


def _dummy_parent_session():
    """与 _stream_status_tick 内 sessionmaker(bind=db.get_bind()) 对齐的最小父 Session。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    class _Parent:
        def get_bind(self):
            return engine

    return _Parent()


@pytest.mark.asyncio
async def test_stream_status_tick_execution_not_found_message_zh(monkeypatch) -> None:
    async def fake_load(**_kwargs):
        return None, None, workflows_api.MSG_EXECUTION_NOT_FOUND

    monkeypatch.setattr(workflows_api, "_load_execution_status_payload", fake_load)

    monkeypatch.setattr(workflows_api, "WorkflowExecutionService", lambda _db: object())

    out, _lh, _hb, stop = await workflows_api._stream_status_tick(
        db=_dummy_parent_session(),
        workflow_id="wf1",
        execution_id="ex1",
        last_hash=None,
        heartbeat_at=datetime.now(UTC),
        heartbeat_every=15,
        compact=True,
        sse_accept_language="zh-CN, zh;q=0.9",
    )
    assert stop is True
    assert out is not None
    line = out.strip()
    assert line.startswith("data: ")
    payload = json.loads(line[6:])
    assert payload["type"] == "error"
    assert payload["message"] == "工作流执行记录不存在"


@pytest.mark.asyncio
async def test_stream_status_tick_execution_not_found_message_en(monkeypatch) -> None:
    async def fake_load(**_kwargs):
        return None, None, workflows_api.MSG_EXECUTION_NOT_FOUND

    monkeypatch.setattr(workflows_api, "_load_execution_status_payload", fake_load)

    monkeypatch.setattr(workflows_api, "WorkflowExecutionService", lambda _db: object())

    out, *_ = await workflows_api._stream_status_tick(
        db=_dummy_parent_session(),
        workflow_id="wf1",
        execution_id="ex1",
        last_hash=None,
        heartbeat_at=datetime.now(UTC),
        heartbeat_every=15,
        compact=True,
        sse_accept_language="en-US, en;q=0.9",
    )
    payload = json.loads(out.strip()[6:])
    assert payload["message"] == "workflow execution not found"
