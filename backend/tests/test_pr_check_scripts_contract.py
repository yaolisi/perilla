from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo


def _read_script(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pr_check_scripts_delegate_to_make_pr_check_targets() -> None:
    """scripts/pr-check*.sh 仅包装 Makefile，避免与 make pr-check 漂移。"""
    root = repo_root()
    pr_check = _read_script(root / "scripts" / "pr-check.sh")
    assert "exec make pr-check" in pr_check
    pr_fast = _read_script(root / "scripts" / "pr-check-fast.sh")
    assert "exec make pr-check-fast" in pr_fast
    makefile = _read_script(root / "Makefile")
    assert re.search(r"^ci:\s+pr-check\s*$", makefile, re.MULTILINE)
    assert re.search(r"^ci-fast:\s+pr-check-fast\s*$", makefile, re.MULTILINE)


def test_pr_check_scripts_support_roadmap_acceptance_flags() -> None:
    root = repo_root()
    pr_check = _read_script(root / "scripts" / "pr-check.sh")
    pr_check_fast = _read_script(root / "scripts" / "pr-check-fast.sh")

    assert "--with-roadmap-acceptance" in pr_check
    assert "SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK=0" in pr_check
    assert "--skip-roadmap-acceptance" in pr_check
    assert "--with-roadmap-acceptance" in pr_check_fast
    assert "SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK=0" in pr_check_fast
    assert "--skip-roadmap-acceptance" in pr_check_fast


def test_quick_check_and_doctor_scripts_mention_merge_gate_hints() -> None:
    root = repo_root()
    quick = _read_script(root / "scripts" / "quick-check.sh")
    assert "quick-check: OK" in quick
    assert "make merge-gate-contract-tests" in quick
    assert "make helm-deploy-contract-check" in quick
    doctor = _read_script(root / "scripts" / "doctor.sh")
    assert "make helm-deploy-contract-check" in doctor
    assert "merge-gate-contract-tests" in doctor


def test_makefile_has_merge_gate_contract_tests_target() -> None:
    root = repo_root()
    makefile = _read_script(root / "Makefile")
    assert "merge-gate-contract-tests:" in makefile
    block = makefile.split("merge-gate-contract-tests:", 1)[1].split("\n\n", 1)[0]
    assert "merge-gate-contract-tests.sh" in block
    help_out = subprocess.run(
        ["make", "help"],
        capture_output=True,
        text=True,
        cwd=root,
        check=True,
    ).stdout
    assert "make merge-gate-contract-tests" in help_out
    assert "npm run healthcheck" in help_out
    assert "npm run security-guardrails" in help_out


def test_makefile_pr_check_includes_helm_deploy_contract_check() -> None:
    """与 CI backend-static-analysis 对齐：合并门禁须包含 Helm 模板与 env 映射契约。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "pr-check:" in makefile
    assert "pr-check-fast:" in makefile
    assert "merge-gate-contract-tests.sh" in makefile
    for line in makefile.splitlines():
        stripped = line.strip()
        if stripped.startswith("pr-check:"):
            assert "helm-deploy-contract-check" in stripped
            assert stripped.index("test-no-fallback") < stripped.index("helm-deploy-contract-check")
        if stripped.startswith("pr-check-fast:"):
            assert "helm-deploy-contract-check" in stripped
            assert stripped.index("test-no-fallback") < stripped.index("helm-deploy-contract-check")


def test_merge_gate_contract_tests_script_paths_exist_and_unique() -> None:
    """merge-gate 脚本中的 pytest 路径须在仓库内存在且不重复（防拼写错误）。"""
    script = _read_script(repo_root() / "scripts" / "merge-gate-contract-tests.sh")
    paths = re.findall(r"backend/tests/test_\w+\.py", script)
    assert paths, "expected backend/tests/test_*.py entries in merge-gate-contract-tests.sh"
    assert len(paths) >= 15, (
        f"merge-gate-contract-tests.sh appears truncated (only {len(paths)} modules); "
        "if intentional, lower the floor in test_pr_check_scripts_contract.py"
    )
    dup = [p for p, n in Counter(paths).items() if n > 1]
    assert not dup, f"duplicate pytest paths in merge gate script: {dup}"
    root = repo_root()
    for rel in paths:
        assert (root / rel).is_file(), f"merge gate lists missing file: {rel}"


def test_backend_static_analysis_triggers_on_deploy_k8s() -> None:
    """deploy、Compose、healthcheck、Dockerfile、监控目录变更须触发静态分析与合并门禁。"""
    wf = _read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    assert "deploy/k8s/**" in wf
    assert "deploy/monitoring/**" in wf
    assert "docker-compose.yml" in wf
    assert "scripts/healthcheck.sh" in wf
    assert "docker/**" in wf
    assert "scripts/doctor.sh" in wf


def test_merge_gate_contract_tests_script_is_single_manifest() -> None:
    """Makefile 与 CI 共用 scripts/merge-gate-contract-tests.sh，避免 pytest 列表漂移。"""
    root = repo_root()
    script = _read_script(root / "scripts" / "merge-gate-contract-tests.sh")
    for name in (
        "test_repo_paths_layout_contract.py",
        "test_helm_notes_env_mapping_contract.py",
        "test_helm_deployment_env_contract.py",
        "test_helm_deployment_duplicate_env_names_contract.py",
        "test_helm_values_env_duplicate_keys_contract.py",
        "test_helm_values_critical_keys_contract.py",
        "test_helm_values_probes_metrics_contract.py",
        "test_helm_values_service_port_alignment_contract.py",
        "test_deploy_k8s_example_alignment_contract.py",
        "test_deploy_k8s_grace_budget_contract.py",
        "test_deploy_secret_env_rate_limit_trust_contract.py",
        "test_deploy_ingress_streaming_hints_contract.py",
        "test_runtime_health_paths_contract.py",
        "test_docker_compose_production_hints_contract.py",
        "test_docker_backend_image_contract.py",
        "test_backend_dockerfile_python_main_contract.py",
        "test_helm_values_security_uid_alignment_contract.py",
        "test_helm_chart_yaml_contract.py",
        "test_pr_check_scripts_contract.py",
        "test_root_package_scripts_contract.py",
    ):
        assert name in script, f"missing manifest entry: {name}"
    workflow = _read_script(root / ".github/workflows" / "backend-static-analysis.yml")
    assert "merge-gate-contract-tests.sh" in workflow
