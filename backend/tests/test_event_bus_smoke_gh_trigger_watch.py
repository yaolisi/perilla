from __future__ import annotations

import json
import subprocess
from collections import deque
from pathlib import Path

import scripts.event_bus_smoke_gh_trigger_watch as mod
from scripts.event_bus_smoke_gh_constants import ALLOWED_GH_RUN_CONCLUSIONS, GH_TRIGGER_AUDIT_SOURCE
from scripts.event_bus_smoke_gh_contract_keys import GH_TRIGGER_INPUTS_AUDIT_EXPECTED_KEYS
from scripts.event_bus_smoke_json_integrity import canonical_json_sha256

from tests.repo_paths import repo_run_python


def _argv() -> list[str]:
    return [
        "prog",
        "--workflow",
        "event-bus-dlq-smoke.yml",
        "--mode",
        "strict",
        "--base-url",
        "http://127.0.0.1:8000",
        "--event-type",
        "agent.status.changed",
        "--limit",
        "20",
        "--expected-schema-version",
        "1",
        "--expected-summary-schema-version",
        "1",
        "--payload-sha256-mode",
        "strict",
        "--result-file-stale-threshold-ms",
        "600000",
        "--file-suffix",
        "run-1",
        "--expected-conclusion",
        "success",
    ]


def test_main_success(monkeypatch, capsys) -> None:
    calls: list[list[str]] = []
    queue = deque(
        [
            subprocess.CompletedProcess(["gh"], 0, stdout="100\n", stderr=""),
            subprocess.CompletedProcess(["gh"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["gh"], 0, stdout="101\n", stderr=""),
            subprocess.CompletedProcess(["gh"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["gh"], 0, stdout="https://example/run/101\n", stderr=""),
            subprocess.CompletedProcess(["gh"], 0, stdout="success\n", stderr=""),
        ]
    )

    def fake_run(_cmd, **_kwargs):
        calls.append(list(_cmd))
        return queue.popleft()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.sys, "argv", _argv())
    rc = mod.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Watching triggered run id: 101" in out
    assert "Run URL: https://example/run/101" in out
    assert "Conclusion: success" in out
    inputs_line = next(line for line in out.splitlines() if line.startswith("Trigger inputs JSON: "))
    payload = json.loads(inputs_line.removeprefix("Trigger inputs JSON: "))
    assert set(payload.keys()) == set(GH_TRIGGER_INPUTS_AUDIT_EXPECTED_KEYS - {"payload_sha256"})
    assert payload["payload_sha256_mode"] == "strict"
    assert payload["workflow"] == "event-bus-dlq-smoke.yml"
    assert payload["expected_conclusion"] == "success"
    trigger_cmd = next(cmd for cmd in calls if cmd[:3] == ["gh", "workflow", "run"])
    assert "payload_sha256_mode=strict" in trigger_cmd


def test_watch_reuses_shared_allowed_conclusions() -> None:
    assert tuple(mod.ALLOWED_GH_RUN_CONCLUSIONS) == tuple(ALLOWED_GH_RUN_CONCLUSIONS)


def test_main_writes_trigger_inputs_audit_file(monkeypatch, capsys, tmp_path: Path) -> None:
    queue = deque(
        [
            subprocess.CompletedProcess(["gh"], 0, stdout="100\n", stderr=""),
            subprocess.CompletedProcess(["gh"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["gh"], 0, stdout="101\n", stderr=""),
            subprocess.CompletedProcess(["gh"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["gh"], 0, stdout="https://example/run/101\n", stderr=""),
            subprocess.CompletedProcess(["gh"], 0, stdout="success\n", stderr=""),
        ]
    )

    def fake_run(_cmd, **_kwargs):
        return queue.popleft()

    audit_file = tmp_path / "audit" / "trigger-inputs.json"
    argv = _argv() + ["--trigger-inputs-audit-file", str(audit_file)]
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.sys, "argv", argv)
    rc = mod.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert f"Trigger inputs audit file: {audit_file}" in out
    payload = json.loads(audit_file.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert isinstance(payload["generated_at_ms"], int) and payload["generated_at_ms"] > 0
    assert payload["source"] == GH_TRIGGER_AUDIT_SOURCE
    assert payload["workflow"] == "event-bus-dlq-smoke.yml"
    assert payload["payload_sha256_mode"] == "strict"
    assert payload["expected_conclusion"] == "success"
    assert payload["run_id"] == "101"
    assert payload["run_url"] == "https://example/run/101"
    assert payload["conclusion"] == "success"
    assert isinstance(payload["completed_at_ms"], int) and payload["completed_at_ms"] > 0
    assert isinstance(payload["duration_ms"], int) and payload["duration_ms"] >= 0
    assert payload["duration_ms"] == payload["completed_at_ms"] - payload["generated_at_ms"]
    digest = payload.pop("payload_sha256")
    assert digest == canonical_json_sha256(payload)


def test_write_trigger_inputs_audit_file_preserves_provided_generated_at_ms(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit" / "manual-write.json"
    payload = {
        "schema_version": 1,
        "generated_at_ms": 1710000000000,
        "source": GH_TRIGGER_AUDIT_SOURCE,
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
        "file_suffix": "run-1",
        "trigger_inputs_audit_file": str(audit_file),
        "run_id": "101",
        "run_url": "https://example/run/101",
        "conclusion": "success",
        "completed_at_ms": 1710000001000,
        "duration_ms": 1000,
    }
    mod._write_trigger_inputs_audit_file(str(audit_file), payload)
    written = json.loads(audit_file.read_text(encoding="utf-8"))
    assert written["generated_at_ms"] == 1710000000000
    digest = written.pop("payload_sha256")
    assert digest == canonical_json_sha256(written)
    assert not list(audit_file.parent.glob(f"{audit_file.name}.tmp-*"))


def test_main_returns_2_when_run_id_unchanged(monkeypatch, capsys) -> None:
    queue = deque(
        [
            subprocess.CompletedProcess(["gh"], 0, stdout="101\n", stderr=""),
            subprocess.CompletedProcess(["gh"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["gh"], 0, stdout="101\n", stderr=""),
        ]
    )

    def fake_run(_cmd, **_kwargs):
        return queue.popleft()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.sys, "argv", _argv())
    rc = mod.main()
    out = capsys.readouterr().out
    assert rc == 2
    assert "Latest run id unchanged after trigger" in out


def test_main_returns_2_when_new_run_missing(monkeypatch, capsys) -> None:
    queue = deque(
        [
            subprocess.CompletedProcess(["gh"], 0, stdout="100\n", stderr=""),
            subprocess.CompletedProcess(["gh"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["gh"], 0, stdout="null\n", stderr=""),
        ]
    )

    def fake_run(_cmd, **_kwargs):
        return queue.popleft()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.sys, "argv", _argv())
    rc = mod.main()
    out = capsys.readouterr().out
    assert rc == 2
    assert "No run found after trigger" in out


def test_main_returns_2_when_trigger_command_fails(monkeypatch, capsys) -> None:
    queue = deque(
        [
            subprocess.CompletedProcess(["gh"], 0, stdout="100\n", stderr=""),
            subprocess.CompletedProcess(["gh"], 1, stdout="", stderr="trigger failed"),
        ]
    )

    def fake_run(_cmd, **_kwargs):
        return queue.popleft()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.sys, "argv", _argv())
    rc = mod.main()
    out = capsys.readouterr().out
    assert rc == 2
    assert "trigger failed" in out


def test_cli_help_returns_0() -> None:
    result = repo_run_python(
        "backend/scripts/event_bus_smoke_gh_trigger_watch.py",
        ["--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Trigger and watch latest EventBus smoke workflow run" in result.stdout


def test_cli_returns_2_when_required_args_missing() -> None:
    result = repo_run_python(
        "backend/scripts/event_bus_smoke_gh_trigger_watch.py",
        [],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "required" in result.stderr.lower()


def test_cli_returns_2_when_mode_invalid() -> None:
    result = repo_run_python(
        "backend/scripts/event_bus_smoke_gh_trigger_watch.py",
        [
            "--workflow",
            "event-bus-dlq-smoke.yml",
            "--mode",
            "invalid",
            "--base-url",
            "http://127.0.0.1:8000",
            "--event-type",
            "agent.status.changed",
            "--limit",
            "20",
            "--expected-schema-version",
            "1",
            "--expected-summary-schema-version",
            "1",
            "--payload-sha256-mode",
            "bad",
            "--result-file-stale-threshold-ms",
            "600000",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stderr.lower()
