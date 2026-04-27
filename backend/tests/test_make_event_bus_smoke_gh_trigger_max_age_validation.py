from __future__ import annotations

import subprocess


def test_make_validate_gh_trigger_max_age_accepts_empty_default() -> None:
    result = subprocess.run(
        ["make", "event-bus-smoke-validate-gh-trigger-max-age-ms"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_make_validate_gh_trigger_max_age_accepts_non_negative_integer() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-trigger-max-age-ms",
            "EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS=600000",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_make_validate_gh_trigger_max_age_rejects_negative() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-trigger-max-age-ms",
            "EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS=-1",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS must be empty or a non-negative integer" in (
        result.stdout + result.stderr
    )


def test_make_validate_gh_trigger_max_age_rejects_non_numeric() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-trigger-max-age-ms",
            "EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS=abc",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS must be empty or a non-negative integer" in (
        result.stdout + result.stderr
    )
