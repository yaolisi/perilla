from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter

import pytest

from tests.pr_check_contract import (
    MERGE_GATE_CONTRACT_TEST_MODULES,
    merge_gate_pytest_modules_from_script,
    merge_gate_pytest_relative_paths,
    read_script,
)
from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo


def test_pr_check_contract_package_exports_alias_common() -> None:
    """tests.pr_check_contract 须与 common 同源，避免 __init__ 漏导出或错误包装。"""
    import tests.pr_check_contract as pkg
    import tests.pr_check_contract.common as common

    for name in pkg.__all__:
        assert hasattr(common, name), name
        assert getattr(pkg, name) is getattr(common, name), name


def test_lint_backend_script_runs_full_ruff_on_pr_check_contract_tree() -> None:
    """lint-backend 须对 pr_check 契约树跑 Ruff check + format --check（路径经数组只维护一处）。"""
    text = read_script(repo_root() / "scripts" / "lint-backend.sh")
    assert "ruff check --select=E9 ." in text
    assert "PR_CHECK_CONTRACT_RUFF_TARGETS=(" in text
    assert "tests/pr_check_contract" in text
    assert "tests/test_pr_check_contract_*.py" in text
    assert 'ruff check "${PR_CHECK_CONTRACT_RUFF_TARGETS[@]}"' in text
    assert 'ruff format --check "${PR_CHECK_CONTRACT_RUFF_TARGETS[@]}"' in text


def test_merge_gate_pr_check_contract_py_files_match_disk_and_tuple() -> None:
    """backend/tests 下 test_pr_check_contract_*.py 须与 MERGE_GATE 登记完全一致（防漏改 merge-gate / tuple）。"""
    root = repo_root()
    tests_dir = root / "backend" / "tests"
    on_disk = sorted(p.name for p in tests_dir.glob("test_pr_check_contract_*.py"))
    in_tuple = sorted(
        m
        for m in MERGE_GATE_CONTRACT_TEST_MODULES
        if m.startswith("test_pr_check_contract_")
    )
    assert on_disk == in_tuple, (
        "filesystem vs MERGE_GATE_CONTRACT_TEST_MODULES mismatch:\n"
        f"  disk:  {on_disk!r}\n"
        f"  tuple: {in_tuple!r}"
    )


def test_pr_check_contract_package_core_files_exist() -> None:
    """tests.pr_check_contract 包须保留（MERGE_GATE 与 Ruff 目标均依赖）。"""
    root = repo_root()
    pkg = root / "backend" / "tests" / "pr_check_contract"
    assert pkg.is_dir(), "expected backend/tests/pr_check_contract/"
    assert (pkg / "__init__.py").is_file()
    assert (pkg / "common.py").is_file()


def test_lint_tools_requirements_pins_ruff_and_mypy() -> None:
    """lint-tools 须固定 ruff/mypy 版本，供 CI 与本地 lint-backend 兜底 pip 安装。"""
    text = read_script(repo_root() / "backend/requirements/lint-tools.txt")
    assert "ruff==" in text
    assert "mypy==" in text


def test_lint_backend_script_installs_lint_tools_when_ruff_or_mypy_missing() -> None:
    """lint-backend 缺 ruff 或 mypy 时须从 requirements/lint-tools.txt 安装。"""
    text = read_script(repo_root() / "scripts" / "lint-backend.sh")
    assert "requirements/lint-tools.txt" in text
    assert "pip install -q -r requirements/lint-tools.txt" in text


def test_pr_check_scripts_delegate_to_make_pr_check_targets() -> None:
    """scripts/pr-check*.sh 仅包装 Makefile，避免与 make pr-check 漂移。"""
    root = repo_root()
    pr_check = read_script(root / "scripts" / "pr-check.sh")
    assert "exec make pr-check" in pr_check
    pr_fast = read_script(root / "scripts" / "pr-check-fast.sh")
    assert "exec make pr-check-fast" in pr_fast
    makefile = read_script(root / "Makefile")
    assert re.search(r"^ci:\s+pr-check\s*$", makefile, re.MULTILINE)
    assert re.search(r"^ci-fast:\s+pr-check-fast\s*$", makefile, re.MULTILINE)


def test_pr_check_scripts_headers_reference_lint_tools_pins() -> None:
    """PR 入口脚本头注释须指向 CI 同源 lint-tools（供查阅）。"""
    needle = "backend/requirements/lint-tools.txt"
    for rel in ("scripts/pr-check.sh", "scripts/pr-check-fast.sh"):
        text = read_script(repo_root() / rel)
        assert needle in text, rel


def test_pr_check_scripts_support_roadmap_acceptance_flags() -> None:
    root = repo_root()
    pr_check = read_script(root / "scripts" / "pr-check.sh")
    pr_check_fast = read_script(root / "scripts" / "pr-check-fast.sh")

    assert "--with-roadmap-acceptance" in pr_check
    assert "SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK=0" in pr_check
    assert "--skip-roadmap-acceptance" in pr_check
    assert "--with-roadmap-acceptance" in pr_check_fast
    assert "SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK=0" in pr_check_fast
    assert "--skip-roadmap-acceptance" in pr_check_fast


def test_quick_check_and_doctor_scripts_mention_merge_gate_hints() -> None:
    root = repo_root()
    quick = read_script(root / "scripts" / "quick-check.sh")
    assert "quick-check: OK" in quick
    assert "install-lint-tools" in quick
    assert "make merge-gate-contract-tests" in quick
    assert "make helm-deploy-contract-check" in quick
    assert "docker-build-all" in quick
    assert "docker-image-build" in quick
    doctor = read_script(root / "scripts" / "doctor.sh")
    assert "install-lint-tools" in doctor
    assert "lint-tools.txt" in doctor
    assert "make helm-deploy-contract-check" in doctor
    assert "merge-gate-contract-tests" in doctor
    assert "docker-build-all" in doctor
    assert "docker-image-build" in doctor


def test_makefile_has_merge_gate_contract_tests_target() -> None:
    root = repo_root()
    makefile = read_script(root / "Makefile")
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
    assert "make install-lint-tools" in help_out
    assert "npm run install-lint-tools" in help_out
    assert "npm run healthcheck" in help_out
    assert "npm run security-guardrails" in help_out
    assert "npm run security-guardrails-ci" in help_out


def test_makefile_pr_check_includes_helm_deploy_contract_check() -> None:
    """与 CI backend-static-analysis 对齐：合并门禁须包含 Helm 模板与 env 映射契约。"""
    makefile = read_script(repo_root() / "Makefile")
    assert "pr-check:" in makefile
    assert "pr-check-fast:" in makefile
    assert "merge-gate-contract-tests.sh" in makefile
    for line in makefile.splitlines():
        stripped = line.strip()
        if stripped.startswith("pr-check:"):
            assert "dependency-policy" in stripped
            assert "helm-deploy-contract-check" in stripped
            assert "backend-static-analysis-extras" in stripped
            assert "test-tenant-isolation" in stripped
            assert stripped.index("i18n-hardcoded-scan") < stripped.index(
                "dependency-policy"
            )
            assert stripped.index("dependency-policy") < stripped.index("lint-backend")
            assert stripped.index("test-no-fallback") < stripped.index(
                "test-tenant-isolation"
            )
            assert stripped.index("test-tenant-isolation") < stripped.index(
                "helm-deploy-contract-check"
            )
            assert stripped.index("helm-deploy-contract-check") < stripped.index(
                "backend-static-analysis-extras"
            )
            assert stripped.index("backend-static-analysis-extras") < stripped.index(
                "test-frontend-unit"
            )
        if stripped.startswith("pr-check-fast:"):
            assert "dependency-policy" in stripped
            assert "helm-deploy-contract-check" in stripped
            assert "backend-static-analysis-extras" in stripped
            assert "test-tenant-isolation" in stripped
            assert stripped.index("i18n-hardcoded-scan") < stripped.index(
                "dependency-policy"
            )
            assert stripped.index("dependency-policy") < stripped.index("lint-backend")
            assert stripped.index("test-no-fallback") < stripped.index(
                "test-tenant-isolation"
            )
            assert stripped.index("test-tenant-isolation") < stripped.index(
                "helm-deploy-contract-check"
            )
            assert stripped.index("helm-deploy-contract-check") < stripped.index(
                "backend-static-analysis-extras"
            )
            assert stripped.index("backend-static-analysis-extras") < stripped.index(
                "test-frontend-unit"
            )


def test_tenant_isolation_marker_collects_regression_suite() -> None:
    """Makefile test-tenant-isolation 使用 -m tenant_isolation；须能收集到非空用例，防漏标导致空跑通过。"""
    root = repo_root()
    env = os.environ.copy()
    env["PYTHONPATH"] = "backend"
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-m",
            "tenant_isolation",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    combined = r.stdout + r.stderr
    assert r.returncode == 0, combined
    m = re.search(r"(\d+)/\d+ tests collected", combined)
    if not m:
        m = re.search(r"(\d+) tests collected", combined)
    assert m is not None, combined
    assert int(m.group(1)) >= 65, (
        f"tenant_isolation marker suite unexpectedly small: {combined!r}"
    )


def test_merge_gate_contract_tests_script_paths_exist_and_unique() -> None:
    """merge-gate 脚本中的 pytest 路径须在仓库内存在且不重复（防拼写错误）。"""
    script = read_script(repo_root() / "scripts" / "merge-gate-contract-tests.sh")
    paths = merge_gate_pytest_relative_paths(script)
    assert paths, (
        "expected backend/tests/test_*.py entries in merge-gate-contract-tests.sh"
    )
    assert len(paths) == len(MERGE_GATE_CONTRACT_TEST_MODULES), (
        f"merge-gate lists {len(paths)} modules, MERGE_GATE_CONTRACT_TEST_MODULES has "
        f"{len(MERGE_GATE_CONTRACT_TEST_MODULES)}; sync script and tuple"
    )
    dup = [p for p, n in Counter(paths).items() if n > 1]
    assert not dup, f"duplicate pytest paths in merge gate script: {dup}"
    root = repo_root()
    for rel in paths:
        assert (root / rel).is_file(), f"merge gate lists missing file: {rel}"


def test_merge_gate_contract_tests_script_is_single_manifest() -> None:
    """Makefile 与 CI 共用 scripts/merge-gate-contract-tests.sh，避免 pytest 列表漂移。"""
    root = repo_root()
    script = read_script(root / "scripts" / "merge-gate-contract-tests.sh")
    for name in MERGE_GATE_CONTRACT_TEST_MODULES:
        assert name in script, f"missing manifest entry: {name}"
    workflow = read_script(root / ".github/workflows" / "backend-static-analysis.yml")
    assert "merge-gate-contract-tests.sh" in workflow
    assert "make test-tenant-isolation" in workflow


def test_merge_gate_contract_tests_script_pytest_list_matches_manifest_tuple() -> None:
    """脚本内 pytest 路径须与 MERGE_GATE_CONTRACT_TEST_MODULES 完全一致（含顺序），防止只改一端。"""
    script = read_script(repo_root() / "scripts" / "merge-gate-contract-tests.sh")
    found = merge_gate_pytest_modules_from_script(script)
    assert found == list(MERGE_GATE_CONTRACT_TEST_MODULES), (
        "merge-gate-contract-tests.sh pytest modules drift vs MERGE_GATE_CONTRACT_TEST_MODULES:\n"
        f"  script: {found!r}\n"
        f"  tuple:  {list(MERGE_GATE_CONTRACT_TEST_MODULES)!r}"
    )


def test_merge_gate_contract_tests_script_invokes_pytest_with_arg_forwarding() -> None:
    """须 export PYTHONPATH、exec pytest 续行、末尾保留 \"$@\" 以透传 -q 等 pytest 参数。"""
    script = read_script(repo_root() / "scripts" / "merge-gate-contract-tests.sh")
    assert "export PYTHONPATH=backend" in script
    assert re.search(r"(?m)^exec pytest \\\s*$", script)
    assert re.search(r'(?m)^\s+"\$@"\s*$', script)


def test_test_no_fallback_script_two_phase_pytest_and_arg_forwarding() -> None:
    """PR 门禁核心：先 no_fallback+strict-markers 批量用例，再单独跑 production_readiness；两段均 \"$@\"。"""
    rel = "scripts/test-no-fallback.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert "if [[ ! -d backend ]]; then" in text
    assert "if [[ ! -f pytest.ini ]]; then" in text
    assert len(text.split("PYTHONPATH=backend pytest")) == 3
    assert '-m no_fallback --strict-markers -q "$@"' in text
    assert "backend/tests/test_api_error_no_fallback_smoke.py" in text
    assert "backend/tests/test_production_readiness_baseline.py" in text
    assert text.rstrip().endswith('-q "$@"')


def test_production_preflight_script_aligns_documented_backend_gate_chain() -> None:
    """production-preflight 的 make/bash 顺序与头注释中「对拍 backend-static-analysis」一致。"""
    rel = "scripts/production-preflight.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "$ROOT"' in text
    assert "make dependency-policy" in text
    assert "bash scripts/quick-check.sh" in text
    assert "bash scripts/test-no-fallback.sh -q" in text
    assert "make test-tenant-isolation" in text
    assert "bash scripts/helm-chart-check.sh" in text
    assert "bash scripts/merge-gate-contract-tests.sh -q" in text
    assert "make backend-static-analysis-extras" in text
    assert "install-lint-tools" in text


def test_release_preflight_script_chains_production_preflight_and_frontend_gates() -> (
    None
):
    """release-preflight 先跑 production-preflight，再对齐 frontend-build（i18n、Vitest、prod build）。"""
    rel = "scripts/release-preflight.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "$ROOT"' in text
    assert "bash scripts/production-preflight.sh" in text
    assert "bash scripts/check-frontend-i18n-hardcoded.sh" in text
    assert "make test-frontend-unit" in text
    assert "make build-frontend" in text
