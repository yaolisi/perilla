from __future__ import annotations

import pytest

from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo

import subprocess


def test_make_validate_summary_schema_version_accepts_positive_integer() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-summary-schema-version",
            "EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION=2",
        ],
        capture_output=True,
        text=True,
        cwd=repo_root(),
    )
    assert result.returncode == 0


def test_make_validate_summary_schema_version_rejects_zero() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-summary-schema-version",
            "EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION=0",
        ],
        capture_output=True,
        text=True,
        cwd=repo_root(),
    )
    assert result.returncode != 0
    assert "must be a positive integer" in (result.stdout + result.stderr)


def test_make_validate_summary_schema_version_rejects_non_numeric() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-summary-schema-version",
            "EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION=abc",
        ],
        capture_output=True,
        text=True,
        cwd=repo_root(),
    )
    assert result.returncode != 0
    assert "must be a positive integer" in (result.stdout + result.stderr)
