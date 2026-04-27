#!/usr/bin/env python3
"""
EventBus DLQ smoke script.

Usage:
  python backend/scripts/event_bus_dlq_smoke.py \
    --base-url http://127.0.0.1:8000 \
    --admin-token <TOKEN>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable, Dict
from urllib import error, parse, request

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from scripts.event_bus_smoke_error_codes import ERR_SMOKE_DLQ_ASSERTION_FAILED, ERR_SMOKE_DLQ_HTTP_STEP
from scripts.event_bus_smoke_json_integrity import canonical_json_dumps

STEP_STATUS = "event-bus/status"
STEP_DLQ_EVENT_TYPE = "event-bus/dlq?event_type"
STEP_DLQ_SINCE_TS = "event-bus/dlq?since_ts"
STEP_REPLAY_DRY_RUN = "event-bus/dlq/replay dry-run"
STEP_REPLAY_REAL = "event-bus/dlq/replay real"
STEP_REPLAY_DUP = "event-bus/dlq/replay duplicate-idempotent"
STEP_REPLAY_CONFLICT = "event-bus/dlq/replay conflict-idempotent"
STEP_DLQ_CLEAR = "event-bus/dlq/clear"
ASSERT_DRY_RUN = "assert dry-run"
ASSERT_DUPLICATE = "assert duplicate-idempotent"
ASSERT_CONFLICT = "assert conflict-idempotent"
ASSERT_CLEAR = "assert dlq/clear"
RESULT_SCHEMA_VERSION = 1


def _request_json(
    method: str,
    url: str,
    token: str,
    idempotency_key: str | None = None,
    body: Dict[str, Any] | None = None,
) -> tuple[int, Dict[str, Any]]:
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    req = request.Request(url=url, method=method, data=data, headers=headers)
    try:
        with request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
            return int(resp.status), payload
    except error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
        try:
            payload = json.loads(raw or "{}")
        except Exception:
            payload = {"raw": raw}
        return int(e.code), payload


def _print_step(name: str, status: int, payload: Dict[str, Any]) -> None:
    if 200 <= status < 300:
        print(f"[OK] {name} -> HTTP {status}")
    else:
        details = {"http_status": status, "step": name}
        print(
            f"[{ERR_SMOKE_DLQ_HTTP_STEP}] {name} -> HTTP {status} "
            f"(details={canonical_json_dumps(details)})"
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _record_step(results: list[Dict[str, Any]], name: str, status: int, ok: bool, detail: str = "") -> None:
    results.append(
        {
            "name": name,
            "status": int(status),
            "ok": bool(ok),
            "detail": detail,
            "ts_ms": int(time.time() * 1000),
        }
    )


def _write_json_output(path: str | None, payload: Dict[str, Any]) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_result_payload(ok: bool, steps: list[Dict[str, Any]], failed_step: str) -> Dict[str, Any]:
    ok_steps = len([s for s in steps if isinstance(s, dict) and s.get("ok") is True])
    err_steps = len([s for s in steps if isinstance(s, dict) and s.get("ok") is False])
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "generated_at_ms": int(time.time() * 1000),
        "ok": bool(ok),
        "steps": steps,
        "failed_step": failed_step,
        "total_steps": len(steps),
        "ok_steps": ok_steps,
        "err_steps": err_steps,
    }


def _fail(json_output: str | None, steps: list[Dict[str, Any]], failed_step: str) -> int:
    _write_json_output(
        json_output,
        _build_result_payload(False, steps, failed_step),
    )
    return 1


def _step_get(
    *,
    step_name: str,
    url: str,
    token: str,
    steps: list[Dict[str, Any]],
    json_output: str | None,
) -> tuple[int, Dict[str, Any], int]:
    status, payload = _request_json("GET", url, token)
    _print_step(step_name, status, payload)
    _record_step(steps, step_name, status, 200 <= status < 400)
    if status >= 400:
        return status, payload, _fail(json_output, steps, step_name)
    return status, payload, 0


def _step_post(
    *,
    step_name: str,
    url: str,
    token: str,
    steps: list[Dict[str, Any]],
    json_output: str | None,
    body: Dict[str, Any],
    idempotency_key: str | None = None,
    ok_predicate=None,
    fail_status_ge: int = 400,
) -> tuple[int, Dict[str, Any], int]:
    status, payload = _request_json(
        "POST",
        url,
        token,
        idempotency_key=idempotency_key,
        body=body,
    )
    _print_step(step_name, status, payload)
    ok = ok_predicate(status, payload) if callable(ok_predicate) else (200 <= status < 400)
    _record_step(steps, step_name, status, ok)
    if status >= fail_status_ge:
        return status, payload, _fail(json_output, steps, step_name)
    return status, payload, 0


def _assert_or_fail(
    *,
    condition: bool,
    message: str,
    assert_step: str,
    steps: list[Dict[str, Any]],
    json_output: str | None,
) -> int:
    try:
        _ensure(condition, message)
        return 0
    except RuntimeError as e:
        details = {"step": assert_step, "error": str(e)}
        print(
            f"[{ERR_SMOKE_DLQ_ASSERTION_FAILED}] {assert_step} assertion failed "
            f"(details={canonical_json_dumps(details)})"
        )
        _record_step(steps, assert_step, 0, False, str(e))
        return _fail(json_output, steps, assert_step)


def _validate_dry_run_payload(
    *,
    payload: Dict[str, Any],
    steps: list[Dict[str, Any]],
    json_output: str | None,
) -> int:
    rc = _assert_or_fail(
        condition=payload.get("dry_run") is True,
        message="dry-run replay response missing dry_run=true",
        assert_step=ASSERT_DRY_RUN,
        steps=steps,
        json_output=json_output,
    )
    if rc:
        return rc
    return _assert_or_fail(
        condition="grouped" in payload,
        message="dry-run replay response missing grouped",
        assert_step=ASSERT_DRY_RUN,
        steps=steps,
        json_output=json_output,
    )


def _validate_duplicate_payload(
    *,
    payload: Dict[str, Any],
    payload2: Dict[str, Any],
    steps: list[Dict[str, Any]],
    json_output: str | None,
) -> int:
    checks = [
        (payload2.get("success", True) is True, "duplicate idempotent replay did not return success"),
        (payload2.get("candidate") == payload.get("candidate"), "duplicate replay candidate mismatch"),
        (payload2.get("replayed") == payload.get("replayed"), "duplicate replay replayed mismatch"),
        (payload2.get("failed") == payload.get("failed"), "duplicate replay failed mismatch"),
    ]
    for condition, message in checks:
        rc = _assert_or_fail(
            condition=condition,
            message=message,
            assert_step=ASSERT_DUPLICATE,
            steps=steps,
            json_output=json_output,
        )
        if rc:
            return rc
    return 0


def _validate_conflict_payload(
    *,
    status3: int,
    payload3: Dict[str, Any],
    steps: list[Dict[str, Any]],
    json_output: str | None,
) -> int:
    rc = _assert_or_fail(
        condition=status3 == 409,
        message="conflict idempotent replay should return HTTP 409",
        assert_step=ASSERT_CONFLICT,
        steps=steps,
        json_output=json_output,
    )
    if rc:
        return rc
    err_code = ((payload3.get("error") or {}).get("code") if isinstance(payload3, dict) else None)
    return _assert_or_fail(
        condition=err_code == "idempotency_conflict",
        message="conflict idempotent replay should return idempotency_conflict",
        assert_step=ASSERT_CONFLICT,
        steps=steps,
        json_output=json_output,
    )


def _validate_clear_payload(
    *,
    payload: Dict[str, Any],
    steps: list[Dict[str, Any]],
    json_output: str | None,
) -> int:
    return _assert_or_fail(
        condition=payload.get("success") is True,
        message="dlq clear response missing success=true",
        assert_step=ASSERT_CLEAR,
        steps=steps,
        json_output=json_output,
    )


@dataclass
class SmokeState:
    base_url: str
    token: str
    event_type: str
    limit: int
    json_output: str | None
    since_ts: int = field(default_factory=lambda: int(time.time() * 1000) - 24 * 60 * 60 * 1000)
    idem_replay_real: str = field(default_factory=lambda: f"smoke-replay-{int(time.time())}")
    result_steps: list[Dict[str, Any]] = field(default_factory=list)
    replay_real_payload: Dict[str, Any] = field(default_factory=dict)


def _step_status(state: SmokeState) -> int:
    _, _, rc = _step_get(
        step_name=STEP_STATUS,
        url=f"{state.base_url}/api/system/event-bus/status",
        token=state.token,
        steps=state.result_steps,
        json_output=state.json_output,
    )
    return rc


def _step_dlq_by_event_type(state: SmokeState) -> int:
    qs = parse.urlencode({"limit": str(state.limit), "event_type": state.event_type})
    _, _, rc = _step_get(
        step_name=STEP_DLQ_EVENT_TYPE,
        url=f"{state.base_url}/api/system/event-bus/dlq?{qs}",
        token=state.token,
        steps=state.result_steps,
        json_output=state.json_output,
    )
    return rc


def _step_dlq_by_since_ts(state: SmokeState) -> int:
    qs = parse.urlencode({"limit": str(state.limit), "since_ts": str(state.since_ts)})
    _, _, rc = _step_get(
        step_name=STEP_DLQ_SINCE_TS,
        url=f"{state.base_url}/api/system/event-bus/dlq?{qs}",
        token=state.token,
        steps=state.result_steps,
        json_output=state.json_output,
    )
    return rc


def _step_replay_dry_run(state: SmokeState) -> int:
    _, payload, rc = _step_post(
        step_name=STEP_REPLAY_DRY_RUN,
        url=f"{state.base_url}/api/system/event-bus/dlq/replay",
        token=state.token,
        steps=state.result_steps,
        json_output=state.json_output,
        idempotency_key="smoke-replay-dryrun",
        body={
            "confirm": True,
            "dry_run": True,
            "event_type": state.event_type,
            "limit": state.limit,
        },
    )
    if rc:
        return rc
    return _validate_dry_run_payload(payload=payload, steps=state.result_steps, json_output=state.json_output)


def _step_replay_real(state: SmokeState) -> int:
    _, payload, rc = _step_post(
        step_name=STEP_REPLAY_REAL,
        url=f"{state.base_url}/api/system/event-bus/dlq/replay",
        token=state.token,
        steps=state.result_steps,
        json_output=state.json_output,
        idempotency_key=state.idem_replay_real,
        body={"confirm": True, "dry_run": False, "limit": state.limit},
        fail_status_ge=500,
    )
    if rc:
        return rc
    state.replay_real_payload = payload
    return 0


def _step_replay_duplicate(state: SmokeState) -> int:
    _, payload2, rc = _step_post(
        step_name=STEP_REPLAY_DUP,
        url=f"{state.base_url}/api/system/event-bus/dlq/replay",
        token=state.token,
        steps=state.result_steps,
        json_output=state.json_output,
        idempotency_key=state.idem_replay_real,
        body={"confirm": True, "dry_run": False, "limit": state.limit},
    )
    if rc:
        return rc
    return _validate_duplicate_payload(
        payload=state.replay_real_payload,
        payload2=payload2,
        steps=state.result_steps,
        json_output=state.json_output,
    )


def _step_replay_conflict(state: SmokeState) -> int:
    status3, payload3, _ = _step_post(
        step_name=STEP_REPLAY_CONFLICT,
        url=f"{state.base_url}/api/system/event-bus/dlq/replay",
        token=state.token,
        steps=state.result_steps,
        json_output=None,
        idempotency_key=state.idem_replay_real,
        body={"confirm": True, "dry_run": True, "limit": state.limit},
        ok_predicate=lambda st, _pl: st == 409,
        fail_status_ge=999,
    )
    return _validate_conflict_payload(
        status3=status3,
        payload3=payload3,
        steps=state.result_steps,
        json_output=state.json_output,
    )


def _step_dlq_clear(state: SmokeState) -> int:
    _, payload, rc = _step_post(
        step_name=STEP_DLQ_CLEAR,
        url=f"{state.base_url}/api/system/event-bus/dlq/clear",
        token=state.token,
        steps=state.result_steps,
        json_output=state.json_output,
        body={"confirm": True},
    )
    if rc:
        return rc
    return _validate_clear_payload(payload=payload, steps=state.result_steps, json_output=state.json_output)


def _run_smoke(
    *,
    base_url: str,
    token: str,
    event_type: str,
    limit: int,
    json_output: str | None,
) -> int:
    state = SmokeState(
        base_url=base_url,
        token=token,
        event_type=event_type,
        limit=limit,
        json_output=json_output,
    )
    step_runners: list[Callable[[SmokeState], int]] = [
        _step_status,
        _step_dlq_by_event_type,
        _step_dlq_by_since_ts,
        _step_replay_dry_run,
        _step_replay_real,
        _step_replay_duplicate,
        _step_replay_conflict,
        _step_dlq_clear,
    ]
    for runner in step_runners:
        rc = runner(state)
        if rc:
            return rc

    print("Smoke finished.")
    _write_json_output(
        state.json_output,
        _build_result_payload(True, state.result_steps, ""),
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test EventBus DLQ APIs")
    parser.add_argument("--base-url", required=True, help="API base URL, e.g. http://127.0.0.1:8000")
    parser.add_argument("--admin-token", required=True, help="Platform admin bearer token")
    parser.add_argument("--event-type", default="agent.status.changed", help="DLQ filter event_type")
    parser.add_argument("--limit", type=int, default=20, help="Replay/query limit")
    parser.add_argument("--json-output", default="", help="Optional path to write structured smoke result JSON")
    args = parser.parse_args()

    return _run_smoke(
        base_url=args.base_url.rstrip("/"),
        token=args.admin_token,
        event_type=args.event_type,
        limit=max(1, min(200, int(args.limit))),
        json_output=args.json_output or None,
    )


if __name__ == "__main__":
    sys.exit(main())

