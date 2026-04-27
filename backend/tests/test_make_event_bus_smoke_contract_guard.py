from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.event_bus_smoke_error_code_guard_targets import (
    ERROR_CODE_GUARD_TEST_FILES,
    extract_error_code_guard_tests_from_text,
)
from scripts.event_bus_smoke_makefile_utils import slice_make_target


def test_make_event_bus_smoke_contract_guard_passes() -> None:
    result = subprocess.run(
        ["make", "event-bus-smoke-contract-guard"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "preflight passed" in output
    assert "[guard] preflight" in output
    assert "[guard] mapping" in output
    assert "[guard] payload" in output
    assert "[guard] validator" in output
    assert "[guard] workflow" in output


def test_make_event_bus_smoke_contract_guard_mapping_passes() -> None:
    result = subprocess.run(
        ["make", "event-bus-smoke-contract-guard-mapping"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_make_event_bus_smoke_contract_guard_payload_passes() -> None:
    result = subprocess.run(
        ["make", "event-bus-smoke-contract-guard-payload"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_make_event_bus_smoke_contract_guard_validator_passes() -> None:
    result = subprocess.run(
        ["make", "event-bus-smoke-contract-guard-validator"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_make_event_bus_smoke_contract_guard_workflow_passes() -> None:
    result = subprocess.run(
        ["make", "event-bus-smoke-contract-guard-workflow"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_contract_guard_validator_includes_all_error_code_guard_tests() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    section = slice_make_target(
        makefile,
        "event-bus-smoke-contract-guard-validator",
        "event-bus-smoke-contract-guard-workflow",
    )
    extracted = extract_error_code_guard_tests_from_text(section)
    assert extracted == ERROR_CODE_GUARD_TEST_FILES
    assert len(extracted) == len(set(extracted))


def test_smoke_unit_includes_all_error_code_guard_tests() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    section = slice_make_target(
        makefile,
        "event-bus-smoke-unit",
        "event-bus-smoke-contract-guard",
    )
    extracted = extract_error_code_guard_tests_from_text(section)
    assert extracted == ERROR_CODE_GUARD_TEST_FILES
    assert len(extracted) == len(set(extracted))


def test_makefile_invokes_scripts_package_smoke_helpers_with_pythonpath_backend() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    needles = (
        "backend/scripts/event_bus_dlq_smoke.py",
        "backend/scripts/event_bus_smoke_preflight.py",
        "backend/scripts/validate_event_bus_smoke_summary_result.py",
        "backend/scripts/validate_event_bus_smoke_gh_inputs_snapshot.py",
        "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
        "backend/scripts/event_bus_smoke_gh_trigger_watch.py",
    )
    for needle in needles:
        hits = [ln.strip() for ln in makefile.splitlines() if needle in ln]
        assert hits, f"Makefile missing invocation of {needle}"
        for ln in hits:
            compact = ln.replace("\t", "")
            assert "python backend/scripts/" in compact, ln
            assert "PYTHONPATH=backend" in ln, ln
