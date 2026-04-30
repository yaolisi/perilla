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


@pytest.mark.parametrize("group_name,group_cfg", list(HELP_TARGET_GROUP_CONFIG.items()))
def test_help_target_groups_sanity(group_name: str, group_cfg: HelpTargetGroupConfig) -> None:
    targets = group_cfg["targets"]
    min_count = group_cfg["min_count"]
    _assert_target_group_sanity(group_name, targets, min_count)
