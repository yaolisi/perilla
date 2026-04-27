from __future__ import annotations

import json
from datetime import UTC, datetime

from api.workflows import _build_status_or_heartbeat_event, _build_workflow_status_delta


def test_build_workflow_status_delta_keeps_core_fields() -> None:
    payload = {
        "execution_id": "exec_1",
        "workflow_id": "wf_1",
        "version_id": "v_1",
        "state": "running",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": None,
        "duration_ms": 123,
        "queue_position": 0,
        "wait_duration_ms": 5,
        "node_timeline": [{"node_id": "n1"}, {"node_id": "n2"}],
        "extra": "ignored",
    }
    delta = _build_workflow_status_delta(payload)
    assert delta == {
        "schema_version": 1,
        "execution_id": "exec_1",
        "workflow_id": "wf_1",
        "version_id": "v_1",
        "state": "running",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": None,
        "duration_ms": 123,
        "queue_position": 0,
        "wait_duration_ms": 5,
        "node_timeline_count": 2,
    }


def test_build_status_event_compact_emits_status_delta() -> None:
    now = datetime.now(UTC)
    payload = {
        "execution_id": "exec_2",
        "workflow_id": "wf_2",
        "version_id": "v_2",
        "state": "queued",
        "node_timeline": [],
    }
    event, next_hash, _ = _build_status_or_heartbeat_event(
        current_hash="hash-1",
        last_hash=None,
        heartbeat_at=now,
        now=now,
        heartbeat_every=15,
        status_payload=payload,
        compact=True,
    )
    assert next_hash == "hash-1"
    assert event is not None
    line = event.strip().replace("data: ", "", 1)
    obj = json.loads(line)
    assert obj["type"] == "status_delta"
    assert obj["payload"]["schema_version"] == 1
    assert obj["payload"]["execution_id"] == "exec_2"
    assert obj["payload"]["node_timeline_count"] == 0

