from __future__ import annotations

import subprocess


def test_make_validate_stale_threshold_ms_accepts_non_negative_integer() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-stale-threshold-ms",
            "EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS=600000",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_make_validate_stale_threshold_ms_rejects_non_numeric_value() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-stale-threshold-ms",
            "EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS=abc",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "must be a non-negative integer" in (result.stdout + result.stderr)


def test_make_validate_stale_threshold_ms_accepts_zero() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-stale-threshold-ms",
            "EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS=0",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_make_validate_stale_threshold_ms_rejects_negative_value() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-stale-threshold-ms",
            "EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS=-1",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "must be a non-negative integer" in (result.stdout + result.stderr)
