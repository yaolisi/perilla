from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_npm_scripts_help_prints_hints_to_stderr() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "npm-scripts.sh"

    result = subprocess.run(
        ["bash", str(script), "--help"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "usage: bash scripts/npm-scripts.sh [--json|--help]" in result.stdout
    assert "[roadmap-gate]" in result.stderr
    assert "GET/POST /api/system/roadmap/kpis" in result.stderr
    assert "GET /api/system/roadmap/quality-metrics" in result.stderr
    assert "GET /api/system/roadmap/phases/status" in result.stderr


def test_npm_scripts_unknown_flag_prints_followups_to_stderr() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "npm-scripts.sh"

    result = subprocess.run(
        ["bash", str(script), "--not-a-real-flag"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "npm-scripts.sh: unknown option: --not-a-real-flag" in result.stderr
    assert "[roadmap-gate] hint: valid options are: (default), --json, --help" in result.stderr


def test_npm_scripts_json_prints_hint_to_stderr_and_stdout_is_json() -> None:
    if shutil.which("npm") is None:
        pytest.skip("npm not available in this environment")

    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "npm-scripts.sh"

    result = subprocess.run(
        ["bash", str(script), "--json"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "[roadmap-gate]" in result.stderr
    assert "GET/POST /api/system/roadmap/kpis" in result.stderr
    assert "GET /api/system/roadmap/quality-metrics" in result.stderr
    assert "GET /api/system/roadmap/phases/status" in result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)


def test_npm_scripts_missing_package_json_prints_followups_to_stderr(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    script_src = root / "scripts" / "npm-scripts.sh"

    fake_root = tmp_path / "fake-repo-root"
    scripts_dir = fake_root / "scripts"
    scripts_dir.mkdir(parents=True)
    script_dst = scripts_dir / "npm-scripts.sh"
    script_dst.write_text(script_src.read_text(encoding="utf-8"), encoding="utf-8")

    result = subprocess.run(
        ["bash", str(script_dst), "--help"],
        cwd=str(fake_root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "npm-scripts.sh: missing package.json at repo root" in result.stderr
    assert "[roadmap-gate] hint: valid options are: (default), --json, --help" in result.stderr
    assert "[roadmap-gate] hint: roadmap gate npm scripts emit logs prefixed with [roadmap-gate]" in result.stderr
    assert "[roadmap-gate]" in result.stderr


def test_npm_scripts_missing_package_json_json_flag_still_fails_fast(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    script_src = root / "scripts" / "npm-scripts.sh"

    fake_root = tmp_path / "fake-repo-root-json"
    scripts_dir = fake_root / "scripts"
    scripts_dir.mkdir(parents=True)
    script_dst = scripts_dir / "npm-scripts.sh"
    script_dst.write_text(script_src.read_text(encoding="utf-8"), encoding="utf-8")

    result = subprocess.run(
        ["bash", str(script_dst), "--json"],
        cwd=str(fake_root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "npm-scripts.sh: missing package.json at repo root" in result.stderr
    assert "[roadmap-gate] hint: valid options are: (default), --json, --help" in result.stderr
    assert "[roadmap-gate] hint: roadmap gate npm scripts emit logs prefixed with [roadmap-gate]" in result.stderr
    assert "[roadmap-gate]" in result.stderr
    assert result.stdout.strip() == ""


def test_npm_scripts_missing_package_json_default_invocation_fails_fast(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    script_src = root / "scripts" / "npm-scripts.sh"

    fake_root = tmp_path / "fake-repo-root-default"
    scripts_dir = fake_root / "scripts"
    scripts_dir.mkdir(parents=True)
    script_dst = scripts_dir / "npm-scripts.sh"
    script_dst.write_text(script_src.read_text(encoding="utf-8"), encoding="utf-8")

    result = subprocess.run(
        ["bash", str(script_dst)],
        cwd=str(fake_root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "npm-scripts.sh: missing package.json at repo root" in result.stderr
    assert "[roadmap-gate] hint: valid options are: (default), --json, --help" in result.stderr
    assert "[roadmap-gate] hint: roadmap gate npm scripts emit logs prefixed with [roadmap-gate]" in result.stderr
    assert "[roadmap-gate]" in result.stderr
    assert result.stdout.strip() == ""


def test_npm_scripts_missing_package_json_unknown_flag_still_reports_missing_package_json(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    script_src = root / "scripts" / "npm-scripts.sh"

    fake_root = tmp_path / "fake-repo-root-unknown"
    scripts_dir = fake_root / "scripts"
    scripts_dir.mkdir(parents=True)
    script_dst = scripts_dir / "npm-scripts.sh"
    script_dst.write_text(script_src.read_text(encoding="utf-8"), encoding="utf-8")

    result = subprocess.run(
        ["bash", str(script_dst), "--not-a-real-flag"],
        cwd=str(fake_root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "npm-scripts.sh: missing package.json at repo root" in result.stderr
    assert "npm-scripts.sh: unknown option:" not in result.stderr
    assert "[roadmap-gate] hint: valid options are: (default), --json, --help" in result.stderr
    assert "[roadmap-gate] hint: roadmap gate npm scripts emit logs prefixed with [roadmap-gate]" in result.stderr
    assert result.stdout.strip() == ""
