from __future__ import annotations

import json

from scripts.event_bus_smoke_json_integrity import canonical_json_sha256
import scripts.event_bus_smoke_preflight as preflight_module

from tests.repo_paths import repo_run_python


def _assert_payload_sha256(payload: dict[str, object]) -> None:
    sha = payload.get("payload_sha256")
    assert isinstance(sha, str) and len(sha) == 64
    core = dict(payload)
    core.pop("payload_sha256", None)
    expected = canonical_json_sha256(core)
    assert sha == expected


def _run_preflight_json(*args: str) -> tuple[int, dict[str, object]]:
    result = repo_run_python(
        "backend/scripts/event_bus_smoke_preflight.py",
        ["--json", *args],
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout.strip())
    return result.returncode, payload


def test_preflight_json_success_fields_contract() -> None:
    code, payload = _run_preflight_json()
    assert code == 0
    assert set(payload.keys()) == {
        "details",
        "generated_at_ms",
        "message",
        "ok",
        "payload_sha256",
        "schema_version",
        "source",
    }
    assert payload["ok"] is True
    assert payload["schema_version"] == preflight_module.PREFLIGHT_JSON_SCHEMA_VERSION
    assert payload["source"] == "event_bus_smoke_preflight.py"
    assert isinstance(payload["generated_at_ms"], int) and payload["generated_at_ms"] > 0
    assert payload["message"] == "EventBus smoke preflight passed"
    details = payload["details"]
    assert isinstance(details, dict)
    assert set(details.keys()) == {
        "current_python_version",
        "min_python_version",
        "required_files",
        "required_modules",
    }
    assert isinstance(details["required_files"], int)
    assert isinstance(details["required_modules"], int)
    _assert_payload_sha256(payload)


def test_preflight_json_failure_fields_contract() -> None:
    code, payload = _run_preflight_json("--module", "definitely_missing_module_for_preflight_json_contract_test")
    assert code == 2
    assert set(payload.keys()) == {
        "code",
        "details",
        "generated_at_ms",
        "message",
        "ok",
        "payload_sha256",
        "schema_version",
        "source",
    }
    assert payload["ok"] is False
    assert payload["code"] == "preflight_missing_modules"
    assert payload["schema_version"] == preflight_module.PREFLIGHT_JSON_SCHEMA_VERSION
    assert payload["source"] == "event_bus_smoke_preflight.py"
    assert isinstance(payload["generated_at_ms"], int) and payload["generated_at_ms"] > 0
    details = payload["details"]
    assert isinstance(details, dict)
    assert set(details.keys()) == {"missing_count", "missing_modules"}
    assert isinstance(details["missing_modules"], list)
    assert details["missing_count"] == len(details["missing_modules"])
    _assert_payload_sha256(payload)
