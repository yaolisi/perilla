from __future__ import annotations

import pytest

from scripts.event_bus_smoke_gh_contract_keys import GH_TRIGGER_INPUTS_AUDIT_EXPECTED_KEYS
from scripts.event_bus_smoke_gh_trigger_audit_payload import (
    build_initial_trigger_inputs_payload,
    finalize_trigger_inputs_payload,
)


def _base_args() -> dict[str, object]:
    return {
        "workflow": "event-bus-dlq-smoke.yml",
        "mode": "strict",
        "base_url": "http://127.0.0.1:8000",
        "event_type": "agent.status.changed",
        "limit": "20",
        "expected_schema_version": "1",
        "expected_summary_schema_version": "1",
        "payload_sha256_mode": "strict",
        "result_file_stale_threshold_ms": "600000",
        "file_suffix": "run-1",
        "trigger_inputs_audit_file": ".tmp/gh-trigger-inputs.json",
        "expected_conclusion": "success",
    }


def test_build_initial_payload_matches_contract_keys() -> None:
    payload = build_initial_trigger_inputs_payload(_base_args(), generated_at_ms=1710000000000)
    assert set(payload.keys()) == set(GH_TRIGGER_INPUTS_AUDIT_EXPECTED_KEYS - {"payload_sha256"})
    assert payload["run_id"] == ""
    assert payload["duration_ms"] == 0


def test_finalize_payload_fills_runtime_fields_and_duration() -> None:
    base = build_initial_trigger_inputs_payload(_base_args(), generated_at_ms=1710000000000)
    payload = finalize_trigger_inputs_payload(
        base,
        run_id="101",
        run_url="https://github.com/org/repo/actions/runs/101",
        conclusion="success",
        completed_at_ms=1710000001000,
    )
    assert payload["run_id"] == "101"
    assert payload["run_url"] == "https://github.com/org/repo/actions/runs/101"
    assert payload["conclusion"] == "success"
    assert payload["duration_ms"] == 1000


def test_finalize_payload_clamps_negative_duration_to_zero() -> None:
    base = build_initial_trigger_inputs_payload(_base_args(), generated_at_ms=1710000000000)
    payload = finalize_trigger_inputs_payload(
        base,
        run_id="101",
        run_url="https://github.com/org/repo/actions/runs/101",
        conclusion="success",
        completed_at_ms=1709999999000,
    )
    assert payload["duration_ms"] == 0


def test_initial_payload_raises_on_missing_required_arg() -> None:
    args = _base_args()
    args.pop("expected_conclusion")
    with pytest.raises(KeyError):
        build_initial_trigger_inputs_payload(args, generated_at_ms=1710000000000)
