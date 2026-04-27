from __future__ import annotations

import json
import subprocess


def test_make_print_gh_inputs_json_is_valid_json_with_expected_keys() -> None:
    result = subprocess.run(
        ["make", "event-bus-smoke-print-gh-inputs-json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    for key in [
        "workflow",
        "base_url",
        "event_type",
        "limit",
        "expected_schema_version",
        "expected_summary_schema_version",
        "summary_schema_mode",
        "payload_sha256_mode",
        "result_file_stale_threshold_ms",
        "file_suffix",
    ]:
        assert key in payload
