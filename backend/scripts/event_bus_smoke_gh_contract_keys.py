from __future__ import annotations

GH_CONTRACT_COMMON_KEYS = {
    "schema_version",
    "generated_at_ms",
    "source",
    "workflow",
    "base_url",
    "event_type",
    "limit",
    "expected_schema_version",
    "expected_summary_schema_version",
    "payload_sha256_mode",
    "result_file_stale_threshold_ms",
    "file_suffix",
    "payload_sha256",
}

GH_TRIGGER_ONLY_KEYS = {
    "mode",
    "trigger_inputs_audit_file",
    "run_id",
    "run_url",
    "conclusion",
    "expected_conclusion",
    "completed_at_ms",
    "duration_ms",
}

GH_SNAPSHOT_ONLY_KEYS = {
    "summary_schema_mode",
}

GH_INPUTS_SNAPSHOT_EXPECTED_KEYS = frozenset(GH_CONTRACT_COMMON_KEYS | GH_SNAPSHOT_ONLY_KEYS)
GH_TRIGGER_INPUTS_AUDIT_EXPECTED_KEYS = frozenset(GH_CONTRACT_COMMON_KEYS | GH_TRIGGER_ONLY_KEYS)
