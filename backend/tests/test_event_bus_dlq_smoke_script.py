from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict


def _load_smoke_module() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "backend" / "scripts" / "event_bus_dlq_smoke.py"
    spec = importlib.util.spec_from_file_location("event_bus_dlq_smoke", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_get_success(url: str) -> tuple[int, Dict[str, Any]]:
    if url.endswith("/api/system/event-bus/status"):
        return 200, {"ok": True}
    if "/api/system/event-bus/dlq?" in url and "event_type=" in url:
        return 200, {"items": []}
    if "/api/system/event-bus/dlq?" in url and "since_ts=" in url:
        return 200, {"items": []}
    raise AssertionError(f"Unexpected GET request: {url}")


def _fake_post_success(
    url: str,
    idempotency_key: str | None = None,
    body: Dict[str, Any] | None = None,
) -> tuple[int, Dict[str, Any]]:
    if url.endswith("/api/system/event-bus/dlq/replay"):
        if idempotency_key == "smoke-replay-dryrun":
            return 200, {"dry_run": True, "grouped": {}}
        if body and body.get("dry_run") is True:
            return 409, {"error": {"code": "idempotency_conflict"}}
        return 200, {"success": True, "candidate": 1, "replayed": 1, "failed": 0}
    if url.endswith("/api/system/event-bus/dlq/clear"):
        return 200, {"success": True}
    raise AssertionError(f"Unexpected POST request: {url} body={body} idem={idempotency_key}")


def _fake_replay_post_response(
    *,
    replay_real_calls: dict[str, int],
    idempotency_key: str | None,
    body: Dict[str, Any] | None,
) -> tuple[int, Dict[str, Any]]:
    if idempotency_key == "smoke-replay-dryrun":
        return 200, {"dry_run": True, "grouped": {}}
    if body and body.get("dry_run") is False:
        replay_real_calls["count"] += 1
        if replay_real_calls["count"] == 1:
            return 429, {"success": True, "candidate": 0, "replayed": 0, "failed": 0}
        return 200, {"success": True, "candidate": 0, "replayed": 0, "failed": 0}
    if body and body.get("dry_run") is True:
        return 409, {"error": {"code": "idempotency_conflict"}}
    raise AssertionError(f"Unexpected replay body={body} idem={idempotency_key}")


def _fake_replay_response_duplicate_mismatch(
    *,
    replay_real_calls: dict[str, int],
    idempotency_key: str | None,
    body: Dict[str, Any] | None,
) -> tuple[int, Dict[str, Any]]:
    if idempotency_key == "smoke-replay-dryrun":
        return 200, {"dry_run": True, "grouped": {}}
    if body and body.get("dry_run") is False:
        replay_real_calls["count"] += 1
        if replay_real_calls["count"] == 1:
            return 200, {"success": True, "candidate": 2, "replayed": 2, "failed": 0}
        # mismatch: candidate/replayed differs from first response
        return 200, {"success": True, "candidate": 1, "replayed": 1, "failed": 0}
    if body and body.get("dry_run") is True:
        return 409, {"error": {"code": "idempotency_conflict"}}
    raise AssertionError(f"Unexpected replay body={body} idem={idempotency_key}")


def _build_fake_request_json(
    replay_responder,
):
    replay_real_calls = {"count": 0}

    def _handler(
        method: str,
        url: str,
        token: str,
        idempotency_key: str | None = None,
        body: Dict[str, Any] | None = None,
    ) -> tuple[int, Dict[str, Any]]:
        assert token == "t"
        if method == "GET":
            return _fake_get_success(url)
        if method == "POST" and url.endswith("/api/system/event-bus/dlq/replay"):
            return replay_responder(
                replay_real_calls=replay_real_calls,
                idempotency_key=idempotency_key,
                body=body,
            )
        if method == "POST" and url.endswith("/api/system/event-bus/dlq/clear"):
            return 200, {"success": True}
        raise AssertionError(f"Unexpected request: {method} {url} body={body} idem={idempotency_key}")

    return _handler


def _fake_request_json_replay_429_then_cached_success():
    return _build_fake_request_json(_fake_replay_post_response)


def _fake_request_json_duplicate_mismatch():
    return _build_fake_request_json(_fake_replay_response_duplicate_mismatch)


def _fake_replay_response_conflict_wrong_code(
    *,
    replay_real_calls: dict[str, int],
    idempotency_key: str | None,
    body: Dict[str, Any] | None,
) -> tuple[int, Dict[str, Any]]:
    if idempotency_key == "smoke-replay-dryrun":
        return 200, {"dry_run": True, "grouped": {}}
    if body and body.get("dry_run") is False:
        replay_real_calls["count"] += 1
        return 200, {"success": True, "candidate": 1, "replayed": 1, "failed": 0}
    if body and body.get("dry_run") is True:
        # wrong error code on conflict assertion path
        return 409, {"error": {"code": "unexpected_conflict"}}
    raise AssertionError(f"Unexpected replay body={body} idem={idempotency_key}")


def _fake_request_json_conflict_wrong_code():
    return _build_fake_request_json(_fake_replay_response_conflict_wrong_code)


def _fake_replay_response_clear_assert_fail(
    *,
    replay_real_calls: dict[str, int],
    idempotency_key: str | None,
    body: Dict[str, Any] | None,
) -> tuple[int, Dict[str, Any]]:
    if idempotency_key == "smoke-replay-dryrun":
        return 200, {"dry_run": True, "grouped": {}}
    if body and body.get("dry_run") is False:
        replay_real_calls["count"] += 1
        return 200, {"success": True, "candidate": 1, "replayed": 1, "failed": 0}
    if body and body.get("dry_run") is True:
        return 409, {"error": {"code": "idempotency_conflict"}}
    raise AssertionError(f"Unexpected replay body={body} idem={idempotency_key}")


def _fake_request_json_clear_assert_fail():
    replay_handler = _build_fake_request_json(_fake_replay_response_clear_assert_fail)

    def _handler(
        method: str,
        url: str,
        token: str,
        idempotency_key: str | None = None,
        body: Dict[str, Any] | None = None,
    ) -> tuple[int, Dict[str, Any]]:
        if method == "POST" and url.endswith("/api/system/event-bus/dlq/clear"):
            # clear endpoint returns HTTP 200 but missing success=true
            return 200, {"success": False}
        return replay_handler(
            method=method,
            url=url,
            token=token,
            idempotency_key=idempotency_key,
            body=body,
        )

    return _handler


def _fake_request_json_dry_run_missing_grouped():
    replay_handler = _build_fake_request_json(_fake_replay_response_clear_assert_fail)

    def _handler(
        method: str,
        url: str,
        token: str,
        idempotency_key: str | None = None,
        body: Dict[str, Any] | None = None,
    ) -> tuple[int, Dict[str, Any]]:
        if (
            method == "POST"
            and url.endswith("/api/system/event-bus/dlq/replay")
            and idempotency_key == "smoke-replay-dryrun"
        ):
            return 200, {"dry_run": True}
        return replay_handler(
            method=method,
            url=url,
            token=token,
            idempotency_key=idempotency_key,
            body=body,
        )

    return _handler


def _fake_request_json_dry_run_false_value():
    replay_handler = _build_fake_request_json(_fake_replay_response_clear_assert_fail)

    def _handler(
        method: str,
        url: str,
        token: str,
        idempotency_key: str | None = None,
        body: Dict[str, Any] | None = None,
    ) -> tuple[int, Dict[str, Any]]:
        if (
            method == "POST"
            and url.endswith("/api/system/event-bus/dlq/replay")
            and idempotency_key == "smoke-replay-dryrun"
        ):
            return 200, {"dry_run": False, "grouped": {}}
        return replay_handler(
            method=method,
            url=url,
            token=token,
            idempotency_key=idempotency_key,
            body=body,
        )

    return _handler


def _fake_replay_response_conflict_status_not_409(
    *,
    replay_real_calls: dict[str, int],
    idempotency_key: str | None,
    body: Dict[str, Any] | None,
) -> tuple[int, Dict[str, Any]]:
    if idempotency_key == "smoke-replay-dryrun":
        return 200, {"dry_run": True, "grouped": {}}
    if body and body.get("dry_run") is False:
        replay_real_calls["count"] += 1
        return 200, {"success": True, "candidate": 1, "replayed": 1, "failed": 0}
    if body and body.get("dry_run") is True:
        return 200, {"error": {"code": "idempotency_conflict"}}
    raise AssertionError(f"Unexpected replay body={body} idem={idempotency_key}")


def _fake_request_json_conflict_status_not_409():
    return _build_fake_request_json(_fake_replay_response_conflict_status_not_409)


def _fake_request_json_success(
    method: str,
    url: str,
    token: str,
    idempotency_key: str | None = None,
    body: Dict[str, Any] | None = None,
) -> tuple[int, Dict[str, Any]]:
    assert token == "t"
    if method == "GET":
        return _fake_get_success(url)
    if method == "POST":
        return _fake_post_success(url, idempotency_key=idempotency_key, body=body)
    raise AssertionError(f"Unexpected method: {method}")


def test_run_smoke_success_writes_structured_json(tmp_path: Path, monkeypatch) -> None:
    smoke = _load_smoke_module()
    json_output = tmp_path / "smoke-result.json"

    monkeypatch.setattr(smoke, "_request_json", _fake_request_json_success)

    rc = smoke._run_smoke(
        base_url="http://mock",
        token="t",
        event_type="agent.status.changed",
        limit=20,
        json_output=str(json_output),
    )
    assert rc == 0
    result = json.loads(json_output.read_text(encoding="utf-8"))
    assert result["schema_version"] == 1
    assert isinstance(result.get("generated_at_ms"), int)
    assert result["ok"] is True
    assert result["failed_step"] == ""
    assert len(result["steps"]) == 8
    assert result["total_steps"] == 8
    assert result["ok_steps"] == 8
    assert result["err_steps"] == 0


def test_run_smoke_first_step_failure_writes_failed_step_json(tmp_path: Path, monkeypatch) -> None:
    smoke = _load_smoke_module()
    json_output = tmp_path / "smoke-failed.json"

    def _fake_request_json(
        method: str,
        url: str,
        token: str,
        idempotency_key: str | None = None,
        body: Dict[str, Any] | None = None,
    ) -> tuple[int, Dict[str, Any]]:
        del token, idempotency_key, body
        if method == "GET" and url.endswith("/api/system/event-bus/status"):
            return 500, {"error": "boom"}
        raise AssertionError(f"Unexpected request after failed first step: {method} {url}")

    monkeypatch.setattr(smoke, "_request_json", _fake_request_json)

    rc = smoke._run_smoke(
        base_url="http://mock",
        token="t",
        event_type="agent.status.changed",
        limit=20,
        json_output=str(json_output),
    )
    assert rc == 1
    result = json.loads(json_output.read_text(encoding="utf-8"))
    assert result["schema_version"] == 1
    assert isinstance(result.get("generated_at_ms"), int)
    assert result["ok"] is False
    assert result["failed_step"] == smoke.STEP_STATUS
    assert len(result["steps"]) == 1
    assert result["total_steps"] == 1
    assert result["ok_steps"] == 0
    assert result["err_steps"] == 1


def test_run_smoke_stops_after_mid_failure_and_keeps_failed_step(tmp_path: Path, monkeypatch) -> None:
    smoke = _load_smoke_module()
    json_output = tmp_path / "smoke-mid-failed.json"
    calls: list[str] = []

    def _fake_request_json(
        method: str,
        url: str,
        token: str,
        idempotency_key: str | None = None,
        body: Dict[str, Any] | None = None,
    ) -> tuple[int, Dict[str, Any]]:
        del token, idempotency_key, body
        key = f"{method} {url}"
        calls.append(key)
        if method == "GET" and url.endswith("/api/system/event-bus/status"):
            return 200, {"ok": True}
        if method == "GET" and "/api/system/event-bus/dlq?" in url and "event_type=" in url:
            return 503, {"error": "dlq unavailable"}
        raise AssertionError(f"Unexpected request after mid-step failure: {method} {url}")

    monkeypatch.setattr(smoke, "_request_json", _fake_request_json)

    rc = smoke._run_smoke(
        base_url="http://mock",
        token="t",
        event_type="agent.status.changed",
        limit=20,
        json_output=str(json_output),
    )
    assert rc == 1
    result = json.loads(json_output.read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["failed_step"] == smoke.STEP_DLQ_EVENT_TYPE
    assert len(result["steps"]) == 2
    assert len(calls) == 2


def test_run_smoke_replay_real_429_still_completes(tmp_path: Path, monkeypatch) -> None:
    smoke = _load_smoke_module()
    json_output = tmp_path / "smoke-replay-429.json"
    monkeypatch.setattr(smoke, "_request_json", _fake_request_json_replay_429_then_cached_success())

    rc = smoke._run_smoke(
        base_url="http://mock",
        token="t",
        event_type="agent.status.changed",
        limit=20,
        json_output=str(json_output),
    )
    assert rc == 0
    result = json.loads(json_output.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["failed_step"] == ""
    assert len(result["steps"]) == 8
    replay_real_step = [s for s in result["steps"] if s.get("name") == smoke.STEP_REPLAY_REAL][0]
    assert replay_real_step["status"] == 429
    assert replay_real_step["ok"] is False
    replay_dup_step = [s for s in result["steps"] if s.get("name") == smoke.STEP_REPLAY_DUP][0]
    assert replay_dup_step["status"] == 200
    assert replay_dup_step["ok"] is True


def test_run_smoke_duplicate_mismatch_fails_with_assert_step(tmp_path: Path, monkeypatch) -> None:
    smoke = _load_smoke_module()
    json_output = tmp_path / "smoke-duplicate-mismatch.json"
    monkeypatch.setattr(smoke, "_request_json", _fake_request_json_duplicate_mismatch())

    rc = smoke._run_smoke(
        base_url="http://mock",
        token="t",
        event_type="agent.status.changed",
        limit=20,
        json_output=str(json_output),
    )
    assert rc == 1
    result = json.loads(json_output.read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["failed_step"] == smoke.ASSERT_DUPLICATE
    assert len(result["steps"]) >= 6


def test_run_smoke_conflict_wrong_code_fails_with_assert_step(tmp_path: Path, monkeypatch) -> None:
    smoke = _load_smoke_module()
    json_output = tmp_path / "smoke-conflict-wrong-code.json"
    monkeypatch.setattr(smoke, "_request_json", _fake_request_json_conflict_wrong_code())

    rc = smoke._run_smoke(
        base_url="http://mock",
        token="t",
        event_type="agent.status.changed",
        limit=20,
        json_output=str(json_output),
    )
    assert rc == 1
    result = json.loads(json_output.read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["failed_step"] == smoke.ASSERT_CONFLICT
    assert len(result["steps"]) >= 7


def test_run_smoke_clear_missing_success_fails_with_assert_step(tmp_path: Path, monkeypatch) -> None:
    smoke = _load_smoke_module()
    json_output = tmp_path / "smoke-clear-assert-fail.json"
    monkeypatch.setattr(smoke, "_request_json", _fake_request_json_clear_assert_fail())

    rc = smoke._run_smoke(
        base_url="http://mock",
        token="t",
        event_type="agent.status.changed",
        limit=20,
        json_output=str(json_output),
    )
    assert rc == 1
    result = json.loads(json_output.read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["failed_step"] == smoke.ASSERT_CLEAR
    assert len(result["steps"]) >= 8


def test_run_smoke_dry_run_missing_grouped_fails_with_assert_step(tmp_path: Path, monkeypatch) -> None:
    smoke = _load_smoke_module()
    json_output = tmp_path / "smoke-dry-run-missing-grouped.json"
    monkeypatch.setattr(smoke, "_request_json", _fake_request_json_dry_run_missing_grouped())

    rc = smoke._run_smoke(
        base_url="http://mock",
        token="t",
        event_type="agent.status.changed",
        limit=20,
        json_output=str(json_output),
    )
    assert rc == 1
    result = json.loads(json_output.read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["failed_step"] == smoke.ASSERT_DRY_RUN
    assert len(result["steps"]) >= 5


def test_run_smoke_conflict_status_not_409_fails_with_assert_step(tmp_path: Path, monkeypatch) -> None:
    smoke = _load_smoke_module()
    json_output = tmp_path / "smoke-conflict-status-not-409.json"
    monkeypatch.setattr(smoke, "_request_json", _fake_request_json_conflict_status_not_409())

    rc = smoke._run_smoke(
        base_url="http://mock",
        token="t",
        event_type="agent.status.changed",
        limit=20,
        json_output=str(json_output),
    )
    assert rc == 1
    result = json.loads(json_output.read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["failed_step"] == smoke.ASSERT_CONFLICT
    assert len(result["steps"]) >= 7


def test_run_smoke_dry_run_false_value_records_assert_detail(tmp_path: Path, monkeypatch) -> None:
    smoke = _load_smoke_module()
    json_output = tmp_path / "smoke-dry-run-false.json"
    monkeypatch.setattr(smoke, "_request_json", _fake_request_json_dry_run_false_value())

    rc = smoke._run_smoke(
        base_url="http://mock",
        token="t",
        event_type="agent.status.changed",
        limit=20,
        json_output=str(json_output),
    )
    assert rc == 1
    result = json.loads(json_output.read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["failed_step"] == smoke.ASSERT_DRY_RUN
    last_step = result["steps"][-1]
    assert last_step["name"] == smoke.ASSERT_DRY_RUN
    assert isinstance(last_step.get("detail"), str) and len(last_step["detail"]) > 0
