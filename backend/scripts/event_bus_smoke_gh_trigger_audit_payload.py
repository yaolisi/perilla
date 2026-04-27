from __future__ import annotations

from typing import Any, Mapping

from scripts.event_bus_smoke_gh_constants import GH_TRIGGER_AUDIT_SOURCE
from scripts.event_bus_smoke_gh_contract_keys import GH_TRIGGER_INPUTS_AUDIT_EXPECTED_KEYS


def build_initial_trigger_inputs_payload(args: Mapping[str, Any], generated_at_ms: int) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "generated_at_ms": int(generated_at_ms),
        "source": GH_TRIGGER_AUDIT_SOURCE,
        "workflow": str(args["workflow"]),
        "mode": str(args["mode"]),
        "base_url": str(args["base_url"]),
        "event_type": str(args["event_type"]),
        "limit": str(args["limit"]),
        "expected_schema_version": str(args["expected_schema_version"]),
        "expected_summary_schema_version": str(args["expected_summary_schema_version"]),
        "payload_sha256_mode": str(args["payload_sha256_mode"]),
        "result_file_stale_threshold_ms": str(args["result_file_stale_threshold_ms"]),
        "file_suffix": str(args.get("file_suffix", "")),
        "trigger_inputs_audit_file": str(args.get("trigger_inputs_audit_file", "")),
        "run_id": "",
        "run_url": "",
        "conclusion": "",
        "expected_conclusion": str(args["expected_conclusion"]),
        "completed_at_ms": 0,
        "duration_ms": 0,
    }
    _assert_payload_keys(payload)
    return payload


def finalize_trigger_inputs_payload(base_payload: Mapping[str, Any], run_id: str, run_url: str, conclusion: str, completed_at_ms: int) -> dict[str, Any]:
    payload = dict(base_payload)
    payload["run_id"] = str(run_id)
    payload["run_url"] = str(run_url)
    payload["conclusion"] = str(conclusion)
    payload["completed_at_ms"] = int(completed_at_ms)
    payload["duration_ms"] = max(int(payload["completed_at_ms"]) - int(payload["generated_at_ms"]), 0)
    _assert_payload_keys(payload)
    return payload


def _assert_payload_keys(payload: Mapping[str, Any]) -> None:
    actual = set(payload.keys())
    expected = set(GH_TRIGGER_INPUTS_AUDIT_EXPECTED_KEYS - {"payload_sha256"})
    if actual != expected:
        missing = ",".join(sorted(expected - actual))
        extra = ",".join(sorted(actual - expected))
        raise ValueError(f"trigger payload key mismatch: missing=[{missing}] extra=[{extra}]")
