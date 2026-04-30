from __future__ import annotations

import subprocess

import pytest
from typing import Dict, List, TypedDict


class HelpTargetGroupConfig(TypedDict):
    targets: List[str]
    min_count: int


HELP_TARGET_GROUP_CONFIG: Dict[str, HelpTargetGroupConfig] = {
    "event_bus_smoke": {
        "targets": [
            "event-bus-smoke-fast",
            "event-bus-smoke-contract-guard",
            "event-bus-smoke-contract-guard-preflight",
            "event-bus-smoke-contract-guard-mapping",
            "event-bus-smoke-contract-guard-payload",
            "event-bus-smoke-contract-guard-validator",
            "event-bus-smoke-contract-guard-workflow",
            "event-bus-smoke-contract-guard-status-json",
            "event-bus-smoke-run-validated",
            "event-bus-smoke-summary-contract",
            "event-bus-smoke-gh-strict",
            "event-bus-smoke-gh-compatible",
            "event-bus-smoke-gh-watch-latest",
            "event-bus-smoke-gh-strict-watch",
            "event-bus-smoke-gh-compatible-watch",
        ],
        "min_count": 6,
    },
    "continuous_batching": {
        "targets": [
            "cb-doctor",
            "cb-benchmark",
            "cb-grid",
            "cb-recommend",
            "cb-gate",
            "cb-triage",
            "cb-tests",
            "cb-fast",
            "cb-pipeline",
            "cb-all",
            "cb-release-check",
        ],
        "min_count": 6,
    },
    "roadmap_acceptance": {
        "targets": [
            "roadmap-acceptance-unit",
            "roadmap-acceptance-smoke",
            "roadmap-acceptance-all",
            "roadmap-acceptance-validate-schema-version",
            "roadmap-acceptance-validate-output",
            "roadmap-acceptance-run-validated",
            "roadmap-release-gate",
            "ROADMAP_ACCEPTANCE_IN_PR_CHECK=1",
            "pr-check-fast",
        ],
        "min_count": 3,
    },
}


def _make_help_output() -> str:
    result = subprocess.run(
        ["make", "help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    return result.stdout


def _assert_targets_present(output: str, targets: list[str]) -> None:
    for target in targets:
        assert target in output


def _assert_target_group_sanity(group_name: str, targets: list[str], min_count: int) -> None:
    assert targets, f"{group_name} targets must not be empty"
    normalized = [t.strip() for t in targets]
    assert all(normalized), f"{group_name} targets must not contain blank entries"
    assert len(normalized) == len(set(normalized)), f"{group_name} targets must be unique"
    assert len(targets) >= min_count, f"{group_name} must keep at least {min_count} help targets"
    for target in targets:
        assert " " not in target, f"{group_name} target must not contain spaces: {target}"
        assert target == target.strip(), f"{group_name} target must not have surrounding spaces: {target!r}"


def test_make_help_contains_event_bus_smoke_entrypoints() -> None:
    output = _make_help_output()
    _assert_targets_present(output, HELP_TARGET_GROUP_CONFIG["event_bus_smoke"]["targets"])


def test_make_help_contains_cb_entrypoints() -> None:
    output = _make_help_output()
    _assert_targets_present(output, HELP_TARGET_GROUP_CONFIG["continuous_batching"]["targets"])


def test_make_help_mentions_roadmap_exit_code_semantics() -> None:
    output = _make_help_output()
    assert "Exit code semantics: 2=parameter/input error, 1=contract/business failure" in output


def test_make_help_mentions_roadmap_quality_metrics_read_api() -> None:
    output = _make_help_output()
    assert (
        "API GET /api/system/roadmap/quality-metrics (platform admin): merged metrics, explicit_metric_keys, phase3_kpi_inference_probe"
        in output
    )


def test_make_help_mentions_roadmap_kpis_api() -> None:
    output = _make_help_output()
    assert (
        "API GET/POST /api/system/roadmap/kpis (platform admin): merged north-star KPI thresholds"
        in output
    )


def test_make_help_mentions_roadmap_phase_status_api() -> None:
    output = _make_help_output()
    assert (
        "API GET /api/system/roadmap/phases/status (platform admin): snapshot, north_star, phase_gate, go_no_go"
        in output
    )


def test_make_help_mentions_roadmap_log_prefix_semantics() -> None:
    output = _make_help_output()
    assert "Logs prefixed with [roadmap-gate] for CI grep/filter" in output
    assert (
        "scripts/acceptance/run_roadmap_acceptance.sh: phase lines on stderr, prefixed by ROADMAP_GATE_LOG_PREFIX"
        in output
    )
    assert (
        "npm run roadmap-acceptance-validate-output / roadmap-acceptance-run-validated / roadmap-release-gate → scripts/acceptance/*.sh (stderr hints; export ROADMAP_GATE_LOG_PREFIX to customize)"
        in output
    )


@pytest.mark.parametrize("group_name,group_cfg", list(HELP_TARGET_GROUP_CONFIG.items()))
def test_help_target_groups_sanity(group_name: str, group_cfg: HelpTargetGroupConfig) -> None:
    targets = group_cfg["targets"]
    min_count = group_cfg["min_count"]
    _assert_target_group_sanity(group_name, targets, min_count)
