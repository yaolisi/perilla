from __future__ import annotations

import subprocess


def test_make_print_gh_inputs_contains_expected_keys() -> None:
    result = subprocess.run(
        ["make", "event-bus-smoke-print-gh-inputs"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    output = result.stdout
    assert "workflow=" in output
    assert "base_url=" in output
    assert "event_type=" in output
    assert "limit=" in output
    assert "expected_schema_version=" in output
    assert "expected_summary_schema_version=" in output
    assert "summary_schema_mode=" in output
    assert "payload_sha256_mode=" in output
    assert "result_file_stale_threshold_ms=" in output
    assert "file_suffix=" in output
