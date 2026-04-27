from __future__ import annotations

import subprocess


def test_make_validate_gh_inputs_accepts_valid_defaults() -> None:
    result = subprocess.run(
        ["make", "event-bus-smoke-validate-gh-inputs"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_make_validate_gh_inputs_rejects_invalid_summary_mode() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-inputs",
            "EVENT_BUS_SMOKE_SUMMARY_SCHEMA_MODE=invalid",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "must be one of: strict,compatible" in (result.stdout + result.stderr)


def test_make_validate_gh_inputs_rejects_invalid_summary_schema_version() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-inputs",
            "EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION=0",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION must be a positive integer" in (result.stdout + result.stderr)


def test_make_validate_gh_inputs_rejects_invalid_stale_threshold() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-inputs",
            "EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS=-1",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS must be a non-negative integer" in (
        result.stdout + result.stderr
    )


def test_make_validate_gh_inputs_rejects_invalid_payload_sha256_mode() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-inputs",
            "EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE=invalid",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE must be one of: strict,off" in (result.stdout + result.stderr)


def test_make_validate_gh_inputs_rejects_invalid_expected_schema_version() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-inputs",
            "EVENT_BUS_SMOKE_SCHEMA_VERSION=0",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "EVENT_BUS_SMOKE_SCHEMA_VERSION must be a positive integer" in (result.stdout + result.stderr)
