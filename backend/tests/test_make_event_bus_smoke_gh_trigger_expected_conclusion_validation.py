from __future__ import annotations

import pytest

from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo

import hashlib
import json
import subprocess
from pathlib import Path


def _with_payload_hash(payload: dict[str, object]) -> dict[str, object]:
    core = dict(payload)
    canonical = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    core["payload_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return core


def test_make_validate_gh_trigger_expected_conclusion_accepts_empty_default() -> None:
    result = subprocess.run(
        ["make", "event-bus-smoke-validate-gh-trigger-expected-conclusion"],
        capture_output=True,
        text=True,
        cwd=repo_root(),
    )
    assert result.returncode == 0


def test_make_validate_gh_trigger_expected_conclusion_accepts_success() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-trigger-expected-conclusion",
            "EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION=success",
        ],
        capture_output=True,
        text=True,
        cwd=repo_root(),
    )
    assert result.returncode == 0


def test_make_validate_gh_trigger_expected_conclusion_accepts_failure() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-trigger-expected-conclusion",
            "EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION=failure",
        ],
        capture_output=True,
        text=True,
        cwd=repo_root(),
    )
    assert result.returncode == 0


def test_make_validate_gh_trigger_expected_conclusion_accepts_cancelled() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-trigger-expected-conclusion",
            "EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION=cancelled",
        ],
        capture_output=True,
        text=True,
        cwd=repo_root(),
    )
    assert result.returncode == 0


def test_make_validate_gh_trigger_expected_conclusion_rejects_invalid_value() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-trigger-expected-conclusion",
            "EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION=unknown",
        ],
        capture_output=True,
        text=True,
        cwd=repo_root(),
    )
    assert result.returncode != 0
    assert "EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION must be empty or one of" in (result.stdout + result.stderr)


def test_make_validate_gh_trigger_inputs_audit_rejects_expected_conclusion_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _with_payload_hash(
        {
            "schema_version": 1,
            "generated_at_ms": 1710000000000,
            "source": "event_bus_smoke_gh_trigger_watch.py",
            "workflow": "event-bus-dlq-smoke.yml",
            "mode": "strict",
            "base_url": "http://127.0.0.1:8000",
            "event_type": "agent.status.changed",
            "limit": "20",
            "expected_schema_version": "1",
            "expected_summary_schema_version": "1",
            "expected_conclusion": "success",
            "payload_sha256_mode": "strict",
            "result_file_stale_threshold_ms": "600000",
            "file_suffix": "",
            "trigger_inputs_audit_file": str(path),
            "run_id": "101",
            "run_url": "https://github.com/org/repo/actions/runs/101",
            "conclusion": "success",
            "completed_at_ms": 1710000001000,
            "duration_ms": 1000,
        }
    )
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-trigger-inputs-audit",
            f"EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE={path}",
            "EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION=failure",
        ],
        capture_output=True,
        text=True,
        cwd=repo_root(),
    )
    assert result.returncode != 0
    assert "conclusion in payload must match --expected-conclusion" in (result.stdout + result.stderr)
