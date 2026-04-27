from __future__ import annotations

import subprocess


def test_make_validate_summary_schema_mode_accepts_strict() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-summary-schema-mode",
            "EVENT_BUS_SMOKE_SUMMARY_SCHEMA_MODE=strict",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_make_validate_summary_schema_mode_accepts_compatible() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-summary-schema-mode",
            "EVENT_BUS_SMOKE_SUMMARY_SCHEMA_MODE=compatible",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_make_validate_summary_schema_mode_rejects_invalid_value() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-summary-schema-mode",
            "EVENT_BUS_SMOKE_SUMMARY_SCHEMA_MODE=invalid",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "must be one of: strict,compatible" in (result.stdout + result.stderr)
