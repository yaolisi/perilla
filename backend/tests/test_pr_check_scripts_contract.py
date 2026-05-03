from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo


def _read_script(path: Path) -> str:
    return path.read_text(encoding="utf-8")


_JOB_HEAD = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
_JOB_BODY_LINE = re.compile(r"^    \S")


def _workflow_job_names_with_runs_on_but_no_timeout(content: str) -> list[str]:
    """扫描 GitHub Actions YAML（jobs: 段）：凡含 runs-on 的 job 须有 timeout-minutes。"""
    lines = content.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "jobs:")
    except StopIteration:
        return []
    bad: list[str] = []
    job_name: str | None = None
    has_timeout = False
    has_runson = False

    def flush() -> None:
        nonlocal job_name, has_timeout, has_runson
        if job_name and has_runson and not has_timeout:
            bad.append(job_name)
        job_name = None
        has_timeout = False
        has_runson = False

    for line in lines[start + 1 :]:
        if (
            line
            and not line.startswith(("#", " ", "\t"))
            and line.strip().endswith(":")
            and line[0].isalpha()
        ):
            break
        m_job = _JOB_HEAD.match(line)
        if m_job:
            flush()
            job_name = m_job.group(1)
            continue
        if job_name is None:
            continue
        if _JOB_BODY_LINE.match(line):
            if "timeout-minutes:" in line:
                has_timeout = True
            if "runs-on:" in line:
                has_runson = True
    flush()
    return bad


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
    assert "npm run security-guardrails-ci" in help_out


def test_makefile_pr_check_includes_helm_deploy_contract_check() -> None:
    """与 CI backend-static-analysis 对齐：合并门禁须包含 Helm 模板与 env 映射契约。"""
    makefile = _read_script(repo_root() / "Makefile")
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
            assert stripped.index("i18n-hardcoded-scan") < stripped.index("dependency-policy")
            assert stripped.index("dependency-policy") < stripped.index("lint-backend")
            assert stripped.index("test-no-fallback") < stripped.index("test-tenant-isolation")
            assert stripped.index("test-tenant-isolation") < stripped.index("helm-deploy-contract-check")
            assert stripped.index("helm-deploy-contract-check") < stripped.index(
                "backend-static-analysis-extras"
            )
            assert stripped.index("backend-static-analysis-extras") < stripped.index("test-frontend-unit")
        if stripped.startswith("pr-check-fast:"):
            assert "dependency-policy" in stripped
            assert "helm-deploy-contract-check" in stripped
            assert "backend-static-analysis-extras" in stripped
            assert "test-tenant-isolation" in stripped
            assert stripped.index("i18n-hardcoded-scan") < stripped.index("dependency-policy")
            assert stripped.index("dependency-policy") < stripped.index("lint-backend")
            assert stripped.index("test-no-fallback") < stripped.index("test-tenant-isolation")
            assert stripped.index("test-tenant-isolation") < stripped.index("helm-deploy-contract-check")
            assert stripped.index("helm-deploy-contract-check") < stripped.index(
                "backend-static-analysis-extras"
            )
            assert stripped.index("backend-static-analysis-extras") < stripped.index("test-frontend-unit")


def test_tenant_isolation_marker_collects_regression_suite() -> None:
    """Makefile test-tenant-isolation 使用 -m tenant_isolation；须能收集到非空用例，防漏标导致空跑通过。"""
    root = repo_root()
    env = os.environ.copy()
    env["PYTHONPATH"] = "backend"
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "tenant_isolation"],
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
    assert int(m.group(1)) >= 65, f"tenant_isolation marker suite unexpectedly small: {combined!r}"


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


def test_dependency_review_workflow_matches_supply_chain_gate() -> None:
    """PR 依赖审查须存在且与 critical 阈值一致（与 frontend npm audit / pip graph 对齐）。"""
    wf = _read_script(repo_root() / ".github/workflows/dependency-review.yml")
    assert "dependency-review-action" in wf
    assert "fail-on-severity: critical" in wf
    assert "pull-requests: write" in wf
    assert "workflow_dispatch:" in wf


def test_frontend_dockerfile_node_major_matches_nvmrc() -> None:
    """docker/frontend.Dockerfile 的 Node 主版本须与 .nvmrc 一致（镜像构建与 CI 对齐）。"""
    root = repo_root()
    nvm_major = int(
        (root / ".nvmrc").read_text(encoding="utf-8").strip().lstrip("v").split(".")[0]
    )
    df = (root / "docker" / "frontend.Dockerfile").read_text(encoding="utf-8")
    m = re.search(r"(?mi)^FROM\s+node:(\d+)", df)
    assert m, "docker/frontend.Dockerfile: expected FROM node:<major>-..."
    assert int(m.group(1)) == nvm_major, (
        f"Dockerfile node major {m.group(1)} != .nvmrc major {nvm_major}"
    )


def test_ci_python_versions_align_with_backend_dockerfile() -> None:
    """.github 内 setup-python 版本须与 docker/backend.Dockerfile 中 FROM python:X.Y 一致。"""
    root = repo_root()
    dockerfile = (root / "docker" / "backend.Dockerfile").read_text(encoding="utf-8")
    m = re.search(r"(?mi)^FROM\s+python:(\d+\.\d+)", dockerfile)
    assert m, "docker/backend.Dockerfile: expected FROM python:X.Y-..."
    py_expected = m.group(1)
    gh = root / ".github"
    mismatches: list[str] = []
    for path in sorted(gh.rglob("*.yml")) + sorted(gh.rglob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("python-version:"):
                continue
            vm = re.search(r'python-version:\s*["\']?([\d.]+)', stripped)
            if vm and vm.group(1) != py_expected:
                mismatches.append(f"{path.relative_to(root)}: {vm.group(1)} (!= {py_expected})")
    assert not mismatches, "python-version drift vs docker/backend.Dockerfile:\n" + "\n".join(
        mismatches
    )


def test_dependabot_config_covers_backend_frontend_actions_and_docker() -> None:
    """Dependabot 须覆盖 pip、npm、Actions、Docker 基础镜像（供应链入口）。"""
    raw = _read_script(repo_root() / ".github/dependabot.yml")
    assert 'package-ecosystem: "pip"' in raw
    assert 'directory: "/backend"' in raw
    assert 'package-ecosystem: "npm"' in raw
    assert 'directory: "/frontend"' in raw
    assert 'package-ecosystem: "github-actions"' in raw
    assert 'directory: "/"' in raw
    assert 'package-ecosystem: "docker"' in raw
    assert 'directory: "/docker"' in raw


def test_all_github_workflows_declare_top_level_concurrency() -> None:
    """每个 workflow 须有顶层 concurrency（队列去重，避免并行重复耗 Runner）。"""
    wf_dir = repo_root() / ".github" / "workflows"
    for path in sorted(wf_dir.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert re.search(r"(?m)^concurrency:\s*$", text), (
            f"missing top-level concurrency block: {path.name}"
        )


def test_github_workflow_jobs_have_timeout_when_runs_on() -> None:
    """含 runs-on 的 job 必须声明 timeout-minutes，避免挂死占用 Runner。"""
    wf_dir = repo_root() / ".github" / "workflows"
    failures: list[str] = []
    for path in sorted(wf_dir.glob("*.yml")):
        missing = _workflow_job_names_with_runs_on_but_no_timeout(path.read_text(encoding="utf-8"))
        for job in missing:
            failures.append(f"{path.name}: job `{job}`")
    assert not failures, "runs-on without timeout-minutes:\n" + "\n".join(failures)


def test_all_github_workflows_declare_permissions() -> None:
    """每个 workflow 须显式声明 permissions（GITHUB_TOKEN 最小权限），防新增裸 workflow。"""
    wf_dir = repo_root() / ".github" / "workflows"
    files = sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml"))
    assert files, "expected .github/workflows/*.yml"
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "permissions:" in text, f"missing permissions block: {path.name}"


def test_security_regression_workflow_aligns_nvmrc_before_setup_node() -> None:
    """security-regression 须在 setup-node 前跑 check-nvmrc-align（与 frontend-build 一致）。"""
    wf = _read_script(repo_root() / ".github/workflows/security-regression.yml")
    assert "scripts/check-nvmrc-align.sh" in wf
    assert "node-version-file: .nvmrc" in wf
    n = wf.find("check-nvmrc-align.sh")
    m = wf.find("Setup Node.js")
    assert n != -1 and m != -1 and n < m


def test_frontend_build_workflow_includes_i18n_and_npm_audit_critical() -> None:
    """纯前端 PR 须跑 i18n 基线与 critical 级 npm audit（与 make pr-check / release-preflight 对齐）。"""
    wf = _read_script(repo_root() / ".github/workflows/frontend-build.yml")
    assert "scripts/check-frontend-i18n-hardcoded.sh" in wf
    assert "npm audit --audit-level=critical" in wf


def test_core_ci_workflows_support_manual_dispatch() -> None:
    """主 CI 须支持 workflow_dispatch，便于在 default 分支上应急重跑全量门禁。"""
    root = repo_root()
    for fname in ("backend-static-analysis.yml", "frontend-build.yml"):
        path = root / ".github" / "workflows" / fname
        text = _read_script(path)
        assert "workflow_dispatch:" in text, f"{fname} should declare workflow_dispatch for manual runs"


def test_backend_static_analysis_triggers_on_deploy_k8s() -> None:
    """deploy、Compose、healthcheck、Dockerfile、监控目录变更须触发静态分析与合并门禁。"""
    wf = _read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    assert ".github/workflows/**" in wf
    assert "deploy/k8s/**" in wf
    assert "deploy/monitoring/**" in wf
    assert "docker-compose.yml" in wf
    assert "scripts/healthcheck.sh" in wf
    assert "docker/**" in wf
    assert "scripts/doctor.sh" in wf


def test_backend_static_analysis_includes_dependency_version_policy() -> None:
    """与 dependency-security-scan 同源策略检查须出现在主后端 CI，防 requirements 漂移。"""
    wf = _read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    assert "scripts/check-dependency-version-policy.sh" in wf
    assert "Dependency version policy" in wf
    assert "permissions:" in wf
    assert "contents: read" in wf


def test_backend_static_analysis_includes_security_guardrails_step() -> None:
    """CI 须跑 production guardrails；合成 env 与 scripts/check-security-guardrails-ci.sh 同源。"""
    root = repo_root()
    wf = _read_script(root / ".github/workflows/backend-static-analysis.yml")
    assert "scripts/check-security-guardrails-ci.sh" in wf
    ci = _read_script(root / "scripts" / "check-security-guardrails-ci.sh")
    assert "DATABASE_URL" in ci
    assert "RBAC_ADMIN_API_KEYS" in ci


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
    assert "make test-tenant-isolation" in workflow
