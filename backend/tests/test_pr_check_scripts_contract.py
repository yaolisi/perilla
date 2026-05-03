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

# 须与 scripts/merge-gate-contract-tests.sh 内 pytest 列表顺序完全一致（双向契约见下方测试）。
MERGE_GATE_CONTRACT_TEST_MODULES: tuple[str, ...] = (
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
    "test_audit_log_events_path_coverage.py",
    "test_deploy_ingress_streaming_hints_contract.py",
    "test_runtime_health_paths_contract.py",
    "test_docker_compose_production_hints_contract.py",
    "test_docker_backend_image_contract.py",
    "test_backend_dockerfile_python_main_contract.py",
    "test_helm_values_security_uid_alignment_contract.py",
    "test_helm_chart_yaml_contract.py",
    "test_pr_check_scripts_contract.py",
    "test_root_package_scripts_contract.py",
    "test_npm_scripts_roadmap_hint_contract.py",
)


def _read_script(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# merge-gate-contract-tests.sh：仅匹配「两空格 + backend/tests/test_*.py + 行尾反斜杠」的 pytest 参数行，忽略注释与文案。
_MERGE_GATE_PYTEST_ARG_LINE = re.compile(r"^\s+(backend/tests/test_\w+\.py)\s*\\\s*$")


def _merge_gate_pytest_relative_paths(script: str) -> list[str]:
    """解析合并门禁脚本中的 pytest 路径列表（顺序与脚本一致）。"""
    out: list[str] = []
    for line in script.splitlines():
        m = _MERGE_GATE_PYTEST_ARG_LINE.match(line)
        if m:
            out.append(m.group(1))
    return out


def _merge_gate_pytest_modules_from_script(script: str) -> list[str]:
    """同上，返回各模块文件名（test_*.py）。"""
    return [Path(p).name for p in _merge_gate_pytest_relative_paths(script)]


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
    assert "docker-build-all" in quick
    assert "docker-image-build" in quick
    doctor = _read_script(root / "scripts" / "doctor.sh")
    assert "make helm-deploy-contract-check" in doctor
    assert "merge-gate-contract-tests" in doctor
    assert "docker-build-all" in doctor
    assert "docker-image-build" in doctor


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
    paths = _merge_gate_pytest_relative_paths(script)
    assert paths, "expected backend/tests/test_*.py entries in merge-gate-contract-tests.sh"
    assert len(paths) == len(MERGE_GATE_CONTRACT_TEST_MODULES), (
        f"merge-gate lists {len(paths)} modules, MERGE_GATE_CONTRACT_TEST_MODULES has "
        f"{len(MERGE_GATE_CONTRACT_TEST_MODULES)}; sync script and tuple"
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


def test_docker_image_build_workflow_aligns_makefile_smoke() -> None:
    """docker-image-build 须与 Makefile docker-build-* 同源命令；含 Trivy 与 main 推 GHCR。"""
    root = repo_root()
    wf = _read_script(root / ".github/workflows/docker-image-build.yml")
    assert "workflow_dispatch:" in wf
    assert "docker build -f docker/backend.Dockerfile" in wf
    assert "docker build -f docker/frontend.Dockerfile" in wf
    assert "perilla-backend:ci" in wf
    assert "perilla-frontend:ci" in wf
    assert "packages: write" in wf
    assert "ghcr.io" in wf
    assert "aquasec/trivy:" in wf
    assert "docker/login-action" in wf
    assert "DOCKER_BUILDKIT" in wf
    assert "GITHUB_STEP_SUMMARY" in wf


def test_core_ci_workflows_support_manual_dispatch() -> None:
    """主 CI / 供应链 / 镜像构建须支持 workflow_dispatch，便于应急重跑。"""
    root = repo_root()
    for fname in (
        "backend-static-analysis.yml",
        "frontend-build.yml",
        "dependency-security-scan.yml",
        "docker-image-build.yml",
    ):
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


def test_backend_static_analysis_test_no_fallback_step_uses_repo_root_entry() -> None:
    """主后端 CI 须在仓库根执行 scripts/test-no-fallback.sh -q，与 make / npm run test-no-fallback 同源。"""
    wf = _read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    assert "Run test-no-fallback suite" in wf
    anchor = wf.find("Run test-no-fallback suite")
    assert anchor != -1
    window = wf[anchor : anchor + 400]
    assert "bash scripts/test-no-fallback.sh -q" in window
    assert "working-directory: ${{ github.workspace }}" in window


def test_workflow_control_flow_regression_workflow_runs_script_from_backend_cwd() -> None:
    """workflow-control-flow-regression 默认 cwd=backend，./scripts/... 对应仓库内 backend/scripts/...。"""
    wf = _read_script(
        repo_root() / ".github/workflows/workflow-control-flow-regression.yml"
    )
    assert "working-directory: backend" in wf
    assert "chmod +x scripts/test_workflow_control_flow_regression.sh" in wf
    assert "./scripts/test_workflow_control_flow_regression.sh" in wf


def test_backend_static_analysis_merge_gate_step_uses_repo_root_entry() -> None:
    """主后端 CI 须在仓库根执行 merge-gate-contract-tests.sh -q（与 make helm-deploy-contract-check 等同源列表）。"""
    wf = _read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    assert "Helm & merge gate contract tests" in wf
    anchor = wf.find("Helm & merge gate contract tests")
    assert anchor != -1
    window = wf[anchor : anchor + 400]
    assert "bash scripts/merge-gate-contract-tests.sh -q" in window
    assert "working-directory: ${{ github.workspace }}" in window


def test_dependency_security_scan_workflow_invokes_policy_and_scan_scripts() -> None:
    """dependency-security-scan 在仓库根 chmod + 执行 policy 与 pip-audit 封装脚本。"""
    wf = _read_script(
        repo_root() / ".github/workflows/dependency-security-scan.yml"
    )
    assert "chmod +x scripts/check-dependency-version-policy.sh" in wf
    assert "./scripts/check-dependency-version-policy.sh" in wf
    assert "chmod +x scripts/scan-dependencies.sh" in wf
    assert "./scripts/scan-dependencies.sh" in wf


def test_tenant_security_regression_workflow_runs_script_from_backend_cwd() -> None:
    """tenant-security-regression 与 workflow-control-flow 同型：cwd=backend 下跑 backend/scripts 入口。"""
    wf = _read_script(
        repo_root() / ".github/workflows/tenant-security-regression.yml"
    )
    assert "working-directory: backend" in wf
    assert "chmod +x scripts/test_tenant_security_regression.sh" in wf
    assert "./scripts/test_tenant_security_regression.sh" in wf


def test_security_regression_workflow_runs_acceptance_suite_from_repo_root() -> None:
    """security-regression 在仓库根 chmod + 执行 run_security_regression.sh（聚合 acceptance 批次）。"""
    wf = _read_script(repo_root() / ".github/workflows/security-regression.yml")
    assert "Run security regression suite" in wf
    anchor = wf.find("Run security regression suite")
    assert anchor != -1
    window = wf[anchor : anchor + 620]
    assert "chmod +x scripts/acceptance/run_security_regression.sh" in window
    assert "./scripts/acceptance/run_security_regression.sh" in window
    assert "chmod +x scripts/acceptance/run_batch1_rbac.sh" in window


def test_smart_routing_gates_composite_action_runs_bundled_gate_scripts() -> None:
    """composite action 须调用包内 canary / least_loaded 脚本（与 gate .sh 契约一致）。"""
    action = _read_script(
        repo_root() / ".github/actions/smart-routing-gates/action.yml"
    )
    assert 'bash "${GITHUB_ACTION_PATH}/canary_admin_gate.sh"' in action
    assert 'bash "${GITHUB_ACTION_PATH}/least_loaded_gate.sh"' in action


def test_knowledge_rag_ci_workflow_runs_smoke_script_from_backend_cwd() -> None:
    """knowledge-rag-ci 在 backend cwd 下执行 scripts/knowledge_acceptance_smoke.py。"""
    wf = _read_script(repo_root() / ".github/workflows/knowledge-rag-ci.yml")
    assert "Run knowledge acceptance smoke" in wf
    anchor = wf.find("Run knowledge acceptance smoke")
    assert anchor != -1
    window = wf[anchor : anchor + 700]
    assert "working-directory: backend" in window
    assert "scripts/knowledge_acceptance_smoke.py" in window


def test_monitoring_alerting_e2e_workflow_invokes_make_and_compose_overlays() -> None:
    """monitoring-alerting-e2e 经 make monitoring-e2e-clean；失败时 dump 与 compose 监控叠加文件一致。"""
    wf = _read_script(
        repo_root() / ".github/workflows/monitoring-alerting-e2e.yml"
    )
    assert "make monitoring-e2e-clean" in wf
    assert "docker-compose.yml" in wf
    assert "deploy/monitoring/docker-compose.monitoring.yml" in wf


def test_continuous_batch_ci_workflow_invokes_make_cb_targets() -> None:
    """continuous-batch-ci：单元阶段 cb-fast；workflow_dispatch gate 阶段 cb-pipeline。"""
    wf = _read_script(repo_root() / ".github/workflows/continuous-batch-ci.yml")
    assert "make cb-fast" in wf
    assert "make cb-pipeline" in wf


def test_backend_static_analysis_tenant_isolation_step_uses_make_target() -> None:
    """Tenant isolation 须在仓库根执行 make test-tenant-isolation（与 Makefile / marker 契约一致）。"""
    wf = _read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    assert "Tenant isolation suite" in wf
    anchor = wf.find("Tenant isolation suite")
    assert anchor != -1
    window = wf[anchor : anchor + 280]
    assert "make test-tenant-isolation" in window
    assert "working-directory: ${{ github.workspace }}" in window


def test_backend_static_analysis_dependency_policy_and_lint_steps_use_workspace_scripts() -> None:
    """policy / lint-backend 步骤须在 github.workspace 下调 bash scripts/*（默认 job cwd 为 backend）。"""
    wf = _read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    pol_a = wf.find("Dependency version policy (FastAPI / SQLAlchemy pins)")
    assert pol_a != -1
    pol_w = wf[pol_a : pol_a + 320]
    assert "bash scripts/check-dependency-version-policy.sh" in pol_w
    assert "working-directory: ${{ github.workspace }}" in pol_w

    lint_a = wf.find("Ruff + Mypy (lint-backend)")
    assert lint_a != -1
    lint_w = wf[lint_a : lint_a + 280]
    assert "bash scripts/lint-backend.sh" in lint_w
    assert "working-directory: ${{ github.workspace }}" in lint_w


def test_backend_static_analysis_infra_checks_follow_merge_gate_order() -> None:
    """compose → 监控 → k8s → hadolint → guardrails 须在 jobs 段内按文档顺序出现。"""
    wf = _read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    body = wf.split("jobs:", 1)[1]
    compose = body.find("bash scripts/compose-config-check.sh")
    mon = body.find("bash scripts/monitoring-config-check.sh")
    k8s = body.find("bash scripts/k8s-manifest-check.sh")
    hado = body.find("bash scripts/dockerfile-hadolint-check.sh")
    guard = body.find("bash scripts/check-security-guardrails-ci.sh")
    assert all(i != -1 for i in (compose, mon, k8s, hado, guard))
    assert compose < mon < k8s < hado < guard


def test_backend_static_analysis_orders_toolchain_and_helm_before_gates() -> None:
    """jobs 段：nvmrc 对齐 → setup-python → dependency-policy → lint-backend；Helm 安装早于 helm-chart-check。"""
    wf = _read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    body = wf.split("jobs:", 1)[1]
    nvmrc = body.find("bash scripts/check-nvmrc-align.sh")
    setup_py = body.find("uses: actions/setup-python@v5")
    policy = body.find("bash scripts/check-dependency-version-policy.sh")
    lint = body.find("bash scripts/lint-backend.sh")
    assert all(i != -1 for i in (nvmrc, setup_py, policy, lint))
    assert nvmrc < setup_py < policy < lint

    helm_tool = body.find("azure/setup-helm@v4")
    helm_check = body.find("bash scripts/helm-chart-check.sh")
    assert helm_tool != -1 and helm_check != -1 and helm_tool < helm_check


def test_backend_static_analysis_orders_lint_tests_helm_merge_gate_compose() -> None:
    """lint → no-fallback → tenant → helm 模板 → 合并门禁 pytest → compose 叠加（与 pr-check 阶段顺序一致）。"""
    wf = _read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    body = wf.split("jobs:", 1)[1]
    lint = body.find("bash scripts/lint-backend.sh")
    no_fb = body.find("bash scripts/test-no-fallback.sh")
    tenant = body.find("make test-tenant-isolation")
    helm_c = body.find("bash scripts/helm-chart-check.sh")
    merge_g = body.find("bash scripts/merge-gate-contract-tests.sh")
    compose = body.find("bash scripts/compose-config-check.sh")
    assert all(i != -1 for i in (lint, no_fb, tenant, helm_c, merge_g, compose))
    assert lint < no_fb < tenant < helm_c < merge_g < compose


def test_event_bus_dlq_smoke_workflow_invokes_make_smoke_chain() -> None:
    """event-bus-dlq-smoke 的门禁链与 Makefile event-bus-smoke-* 目标对齐。"""
    wf = _read_script(repo_root() / ".github/workflows/event-bus-dlq-smoke.yml")
    assert "make event-bus-smoke-validate-schema-version" in wf
    assert "make event-bus-smoke-preflight" in wf
    assert "make event-bus-smoke-unit" in wf
    assert "make event-bus-smoke-contract-guard" in wf
    assert "make event-bus-smoke-run-validated" in wf
    assert "make event-bus-smoke-pytest" in wf
    assert "make event-bus-smoke-summary-contract" in wf


def test_smart_routing_experiment_promote_workflow_invokes_make_smart_routing_targets() -> None:
    """smart-routing-experiment-promote 通过 Makefile smart-routing-* 编排实验与扫描/压测。"""
    wf = _read_script(
        repo_root() / ".github/workflows/smart-routing-experiment-promote.yml"
    )
    assert "make smart-routing-all-checks" in wf
    assert "make smart-routing-experiment" in wf
    assert "make smart-routing-param-scan" in wf
    assert "make smart-routing-load-test" in wf


def test_frontend_build_workflow_orders_nvmrc_i18n_before_node_and_audit() -> None:
    """frontend-build：nvmrc 对齐须早于 setup-node；i18n 基线须早于 npm audit。"""
    wf = _read_script(repo_root() / ".github/workflows/frontend-build.yml")
    body = wf.split("jobs:", 1)[1]
    nvmrc = body.find("bash scripts/check-nvmrc-align.sh")
    setup_node = body.find("actions/setup-node@v4")
    assert nvmrc != -1 and setup_node != -1 and nvmrc < setup_node
    i18n = body.find("bash scripts/check-frontend-i18n-hardcoded.sh")
    audit = body.find("npm audit --audit-level=critical")
    assert i18n != -1 and audit != -1 and i18n < audit


def test_smart_routing_gates_matrix_workflow_uses_composite_action() -> None:
    """smart-routing-gates-matrix 通过本地 composite action 跑 canary / least_loaded 门。"""
    wf = _read_script(
        repo_root() / ".github/workflows/smart-routing-gates-matrix.yml"
    )
    assert "uses: ./.github/actions/smart-routing-gates" in wf
    assert "workflow_dispatch:" in wf
    assert "vars.SMART_ROUTING_BASE_URL" in wf


def test_knowledge_rag_ci_workflow_runs_default_pytest_suites_from_backend() -> None:
    """knowledge-rag-ci 默认 job 在 backend 下跑 knowledge 相关 pytest 文件列表。"""
    wf = _read_script(repo_root() / ".github/workflows/knowledge-rag-ci.yml")
    assert "Run knowledge test suites" in wf
    anchor = wf.find("Run knowledge test suites")
    assert anchor != -1
    window = wf[anchor : anchor + 500]
    assert "working-directory: backend" in window
    assert "tests/test_knowledge_base_store.py" in window


def test_merge_gate_contract_tests_script_is_single_manifest() -> None:
    """Makefile 与 CI 共用 scripts/merge-gate-contract-tests.sh，避免 pytest 列表漂移。"""
    root = repo_root()
    script = _read_script(root / "scripts" / "merge-gate-contract-tests.sh")
    for name in MERGE_GATE_CONTRACT_TEST_MODULES:
        assert name in script, f"missing manifest entry: {name}"
    workflow = _read_script(root / ".github/workflows" / "backend-static-analysis.yml")
    assert "merge-gate-contract-tests.sh" in workflow
    assert "make test-tenant-isolation" in workflow


def test_merge_gate_contract_tests_script_pytest_list_matches_manifest_tuple() -> None:
    """脚本内 pytest 路径须与 MERGE_GATE_CONTRACT_TEST_MODULES 完全一致（含顺序），防止只改一端。"""
    script = _read_script(repo_root() / "scripts" / "merge-gate-contract-tests.sh")
    found = _merge_gate_pytest_modules_from_script(script)
    assert found == list(MERGE_GATE_CONTRACT_TEST_MODULES), (
        "merge-gate-contract-tests.sh pytest modules drift vs MERGE_GATE_CONTRACT_TEST_MODULES:\n"
        f"  script: {found!r}\n"
        f"  tuple:  {list(MERGE_GATE_CONTRACT_TEST_MODULES)!r}"
    )


def test_merge_gate_contract_tests_script_invokes_pytest_with_arg_forwarding() -> None:
    """须 export PYTHONPATH、exec pytest 续行、末尾保留 \"$@\" 以透传 -q 等 pytest 参数。"""
    script = _read_script(repo_root() / "scripts" / "merge-gate-contract-tests.sh")
    assert "export PYTHONPATH=backend" in script
    assert re.search(r"(?m)^exec pytest \\\s*$", script)
    assert re.search(r'(?m)^\s+"\$@"\s*$', script)


def test_test_no_fallback_script_two_phase_pytest_and_arg_forwarding() -> None:
    """PR 门禁核心：先 no_fallback+strict-markers 批量用例，再单独跑 production_readiness；两段均 \"$@\"。"""
    rel = "scripts/test-no-fallback.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'if [[ ! -d backend ]]; then' in text
    assert 'if [[ ! -f pytest.ini ]]; then' in text
    assert len(text.split("PYTHONPATH=backend pytest")) == 3
    assert "-m no_fallback --strict-markers -q \"$@\"" in text
    assert "backend/tests/test_api_error_no_fallback_smoke.py" in text
    assert "backend/tests/test_production_readiness_baseline.py" in text
    assert text.rstrip().endswith('-q "$@"')


def test_makefile_test_no_fallback_and_workflow_control_flow_delegate_to_scripts() -> None:
    """make test-no-fallback / test-workflow-control-flow 须固定委托 bash 脚本，便于与 CI 入口对齐。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "@bash scripts/test-no-fallback.sh $(TEST_ARGS)" in makefile
    assert "@bash backend/scripts/test_workflow_control_flow_regression.sh" in makefile


def test_production_preflight_script_aligns_documented_backend_gate_chain() -> None:
    """production-preflight 的 make/bash 顺序与头注释中「对拍 backend-static-analysis」一致。"""
    rel = "scripts/production-preflight.sh"
    text = _read_script(repo_root() / rel)
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


def test_release_preflight_script_chains_production_preflight_and_frontend_gates() -> None:
    """release-preflight 先跑 production-preflight，再对齐 frontend-build（i18n、Vitest、prod build）。"""
    rel = "scripts/release-preflight.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "$ROOT"' in text
    assert "bash scripts/production-preflight.sh" in text
    assert "bash scripts/check-frontend-i18n-hardcoded.sh" in text
    assert "make test-frontend-unit" in text
    assert "make build-frontend" in text


def test_makefile_production_and_release_preflight_delegate_to_scripts() -> None:
    """Makefile production-preflight / release-preflight 须委托仓库根 bash 脚本。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "@bash scripts/production-preflight.sh" in makefile
    assert "@bash scripts/release-preflight.sh" in makefile


def test_makefile_ci_targets_alias_pr_check_recipes() -> None:
    """make ci / ci-fast 仅为 pr-check / pr-check-fast 别名（与 package.json 中 npm run ci* 一致）。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert re.search(r"^ci:\s*pr-check\s*$", makefile, re.MULTILINE)
    assert re.search(r"^ci-fast:\s*pr-check-fast\s*$", makefile, re.MULTILINE)


def test_makefile_quick_check_delegates_to_script() -> None:
    """make quick-check 须委托 scripts/quick-check.sh（最小 nvmrc + lint）。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "@bash scripts/quick-check.sh" in makefile


def test_quick_check_script_runs_nvmrc_align_and_lint_backend() -> None:
    """quick-check 仅跑 nvmrc 对齐 + lint-backend，并在输出中提示 merge-gate / docker 冒烟路径。"""
    rel = "scripts/quick-check.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert "bash scripts/check-nvmrc-align.sh" in text
    assert "bash scripts/lint-backend.sh" in text
    assert "merge-gate-contract-tests" in text
    assert "docker-build-all" in text or "docker-image-build" in text


def test_makefile_helm_deploy_contract_and_merge_gate_targets_invoke_manifest_script() -> None:
    """helm-deploy-contract-check 依赖 helm-chart-check 并跑 merge-gate -q；merge-gate-contract-tests 仅 manifest。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert re.search(
        r"^helm-deploy-contract-check:\s*helm-chart-check\s*$",
        makefile,
        re.MULTILINE,
    )
    assert "helm-deploy-contract-check: helm-chart-check\n\t@bash scripts/merge-gate-contract-tests.sh -q" in makefile
    assert "merge-gate-contract-tests:\n\t@bash scripts/merge-gate-contract-tests.sh" in makefile


def test_makefile_pr_check_includes_build_frontend_pr_check_fast_skips_it() -> None:
    """pr-check 配方含 build-frontend；pr-check-fast 不含（与 help 文案一致）。"""
    makefile = _read_script(repo_root() / "Makefile")
    pr = re.search(r"^pr-check:.*$", makefile, re.MULTILINE)
    pr_fast = re.search(r"^pr-check-fast:.*$", makefile, re.MULTILINE)
    assert pr is not None and "build-frontend" in pr.group(0)
    assert pr_fast is not None and "build-frontend" not in pr_fast.group(0)


def test_makefile_backend_static_analysis_extras_matches_ci_infra_tail() -> None:
    """backend-static-analysis-extras 的依赖顺序与主后端 CI 中 merge gate 之后五步一致。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert re.search(
        r"^backend-static-analysis-extras:\s*"
        r"compose-config-check\s+monitoring-config-check\s+k8s-manifest-check\s+"
        r"dockerfile-hadolint-check\s+security-guardrails-ci\s*$",
        makefile,
        re.MULTILINE,
    )


def test_makefile_dependency_policy_and_scan_delegate_to_scripts() -> None:
    """dependency-policy / dependency-scan 须委托对应 bash 脚本（与 dependency-security-scan workflow 同源）。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "dependency-policy:\n\t@bash scripts/check-dependency-version-policy.sh" in makefile
    assert "dependency-scan:\n\t@bash scripts/scan-dependencies.sh" in makefile


def test_makefile_ci_related_targets_delegate_to_scripts_under_scripts_dir() -> None:
    """pr-check / backend-static-analysis-extras 所用 Makefile 目标须 bash scripts/*（与 workflow / shell 契约一致）。"""
    makefile = _read_script(repo_root() / "Makefile")
    blocks = (
        ("security-guardrails:\n\t@bash scripts/check-security-guardrails.sh"),
        ("security-guardrails-ci:\n\t@bash scripts/check-security-guardrails-ci.sh"),
        ("check-nvmrc-align:\n\t@bash scripts/check-nvmrc-align.sh"),
        ("i18n-hardcoded-scan:\n\t@bash scripts/check-frontend-i18n-hardcoded.sh"),
        ("helm-chart-check:\n\t@bash scripts/helm-chart-check.sh"),
        ("compose-config-check:\n\t@bash scripts/compose-config-check.sh"),
        ("monitoring-config-check:\n\t@bash scripts/monitoring-config-check.sh"),
        ("k8s-manifest-check:\n\t@bash scripts/k8s-manifest-check.sh"),
        ("dockerfile-hadolint-check:\n\t@bash scripts/dockerfile-hadolint-check.sh"),
    )
    for block in blocks:
        assert block in makefile, f"missing Makefile fragment: {block!r}"


def test_makefile_healthcheck_doctor_and_lint_delegate_to_scripts() -> None:
    """healthcheck / doctor / lint-backend 委托 scripts；lint 为 lint-backend 别名。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "healthcheck:\n\t@bash scripts/healthcheck.sh" in makefile
    assert "doctor:\n\t@bash scripts/doctor.sh" in makefile
    assert "lint-backend:\n\t@bash scripts/lint-backend.sh" in makefile
    assert re.search(r"^lint:\s*lint-backend\s*$", makefile, re.MULTILINE)


def test_makefile_docker_build_targets_use_buildkit_and_smoke_tags() -> None:
    """docker-build-* 与 docker-image-build / 文档冒烟一致：BuildKit、docker/*.Dockerfile、本地 tag。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "DOCKER_BUILDKIT=1" in makefile
    assert "docker/backend.Dockerfile" in makefile and "perilla-backend:local" in makefile
    assert "docker/frontend.Dockerfile" in makefile and "perilla-frontend:local" in makefile
    assert re.search(
        r"^docker-build-all:\s*docker-build-backend\s+docker-build-frontend\s*$",
        makefile,
        re.MULTILINE,
    )


def test_makefile_npm_scripts_targets_delegate_to_wrapper() -> None:
    """make npm-scripts / npm-scripts-json 须委托 scripts/npm-scripts.sh（与 package.json / CI grep 约定一致）。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "npm-scripts:\n\t@bash scripts/npm-scripts.sh" in makefile
    assert "npm-scripts-json:\n\t@bash scripts/npm-scripts.sh --json" in makefile


def test_npm_scripts_sh_dispatches_default_json_help_and_unknown() -> None:
    """npm-scripts.sh：ROOT + roadmap gate 前缀；case 分支 exec npm run / npm pkg get / usage。"""
    rel = "scripts/npm-scripts.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert "ROADMAP_GATE_LOG_PREFIX" in text
    assert 'case "${1:-}" in' in text
    assert "exec npm run" in text
    assert "npm pkg get scripts" in text
    assert "--help" in text


def test_makefile_bootstrap_install_and_env_init_delegate_to_scripts() -> None:
    """install / env-init 委托 scripts；bootstrap → env-init + doctor + install；bootstrap-prod 加强 doctor。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "install:\n\t@bash scripts/install.sh" in makefile
    assert "env-init:\n\t@bash scripts/env-init.sh" in makefile
    assert "install-prod:\n\t@bash scripts/install-prod.sh" in makefile
    assert (
        "bootstrap:\n"
        "\t@$(MAKE) env-init\n"
        "\t@$(MAKE) doctor\n"
        "\t@$(MAKE) install\n"
    ) in makefile
    assert (
        "bootstrap-prod:\n"
        "\t@$(MAKE) env-init\n"
        "\t@DOCTOR_STRICT_WARNINGS=1 $(MAKE) doctor\n"
        "\t@$(MAKE) install-prod\n"
    ) in makefile


def test_makefile_local_dev_and_install_variants_delegate_to_entry_scripts() -> None:
    """local-* 委托仓库根 run-*.sh；GPU / prod-soft 安装委托 scripts/*。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "local-all:\n\t@bash run-all.sh" in makefile
    assert "local-backend:\n\t@bash run-backend.sh" in makefile
    assert "local-frontend:\n\t@bash run-frontend.sh" in makefile
    assert "install-gpu:\n\t@bash scripts/install-gpu.sh" in makefile
    assert (
        "install-prod-soft:\n\t@DOCTOR_STRICT_WARNINGS=0 bash scripts/install-prod.sh"
        in makefile
    )


def test_makefile_compose_ops_targets_delegate_to_scripts() -> None:
    """docker-compose 运维入口（含 gpu/prod、reset）须委托 scripts/*（与 shell 契约一致）。"""
    makefile = _read_script(repo_root() / "Makefile")
    blocks = (
        "up:\n\t@bash scripts/up.sh",
        "down:\n\t@bash scripts/down.sh",
        "up-gpu:\n\t@bash scripts/up-gpu.sh",
        "down-gpu:\n\t@bash scripts/down-gpu.sh",
        "up-prod:\n\t@bash scripts/up-prod.sh",
        "down-prod:\n\t@bash scripts/down-prod.sh",
        "status:\n\t@bash scripts/status.sh",
        "logs:\n\t@bash scripts/logs.sh",
        "reset:\n\t@bash scripts/reset.sh",
    )
    for block in blocks:
        assert block in makefile, f"missing Makefile fragment: {block!r}"


def test_makefile_monitoring_stack_targets_use_compose_overlay_paths() -> None:
    """up/down/status-monitoring 须使用 base + monitoring 叠加 compose（与 compose-config-check / CI 一致）。"""
    makefile = _read_script(repo_root() / "Makefile")
    overlay = (
        "docker compose -f docker-compose.yml "
        "-f deploy/monitoring/docker-compose.monitoring.yml"
    )
    assert (
        f"up-monitoring:\n\t@{overlay} up -d" in makefile
    ), "expected up-monitoring with compose overlay"
    assert (
        f"down-monitoring:\n\t@{overlay} down" in makefile
    ), "expected down-monitoring with compose overlay"
    assert (
        f"status-monitoring:\n\t@{overlay} ps" in makefile
    ), "expected status-monitoring with compose overlay"


def test_makefile_roadmap_acceptance_all_and_unit_match_scripts_and_pytest_list() -> None:
    """roadmap-acceptance-all 委托 acceptance 脚本；unit 目标固定四条 pytest 路径 + -k roadmap。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "bash scripts/acceptance/run_roadmap_acceptance.sh" in makefile
    for path in (
        "backend/tests/test_roadmap_service.py",
        "backend/tests/test_system_api_integration.py",
        "backend/tests/test_roadmap_acceptance_smoke.py",
        "backend/tests/test_roadmap_openapi_contract.py",
    ):
        assert path in makefile, f"Makefile missing roadmap unit path: {path}"
    assert "-q -k roadmap" in makefile


def test_makefile_monitoring_smoke_invokes_backend_monitoring_script() -> None:
    """monitoring-smoke 须调用仓库内 backend/scripts/monitoring_smoke.py（与 workflow / 本地探测一致）。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "monitoring-smoke:" in makefile
    assert "backend/scripts/monitoring_smoke.py" in makefile


def test_makefile_tenant_workflow_and_smart_routing_test_entrypoints() -> None:
    """tenant_isolation / workflow 回归 / smart-routing 冒烟与 Makefile 配方一致。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert (
        "test-tenant-isolation:\n"
        "\t@PYTHONPATH=backend pytest -m tenant_isolation -q $(TEST_ARGS)"
    ) in makefile
    assert (
        "test-workflow-control-flow:\n"
        "\t@bash backend/scripts/test_workflow_control_flow_regression.sh"
    ) in makefile
    assert "smart-routing-smoke:" in makefile
    for path in (
        "backend/tests/test_smart_routing_script_utils.py",
        "backend/tests/test_model_router_smart_routing.py",
        "backend/tests/test_smart_routing_validation.py",
    ):
        assert path in makefile, f"missing smart-routing pytest path: {path}"


def test_makefile_cb_fast_runs_cb_tests_then_cb_doctor() -> None:
    """cb-fast 固定先 cb-tests 再 cb-doctor（与 continuous-batch-ci 默认 job 一致）。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert (
        "cb-fast:\n"
        "\t@$(MAKE) cb-tests\n"
        "\t@$(MAKE) cb-doctor\n"
    ) in makefile


def test_makefile_cb_tests_lists_continuous_batch_pytest_modules() -> None:
    """cb-tests 固定四条 continuous batch 契约测试（与 continuous-batch-ci、脚本实现对齐）。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "cb-tests:" in makefile
    for path in (
        "backend/tests/test_continuous_batch_tooling.py",
        "backend/tests/test_continuous_batch_run_all.py",
        "backend/tests/test_continuous_batch_latest_report.py",
        "backend/tests/test_continuous_batch_doctor.py",
    ):
        assert path in makefile, f"Makefile cb-tests missing: {path}"


def test_makefile_roadmap_acceptance_smoke_invokes_backend_cli_script() -> None:
    """roadmap-acceptance-smoke 须调用 backend/scripts/roadmap_acceptance_smoke.py。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "roadmap-acceptance-smoke:" in makefile
    assert "backend/scripts/roadmap_acceptance_smoke.py" in makefile


def test_makefile_roadmap_acceptance_validate_output_invokes_backend_validator() -> None:
    """roadmap-acceptance-validate-output 须调用 validate_roadmap_acceptance_result.py。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "roadmap-acceptance-validate-output:" in makefile
    assert "backend/scripts/validate_roadmap_acceptance_result.py" in makefile


def test_makefile_event_bus_smoke_runs_backend_dlq_smoke_script() -> None:
    """event-bus-smoke 须调用 backend/scripts/event_bus_dlq_smoke.py。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "event-bus-smoke:" in makefile
    assert "backend/scripts/event_bus_dlq_smoke.py" in makefile


def test_makefile_event_bus_smoke_pytest_runs_external_smoke_test() -> None:
    """event-bus-smoke-pytest 须用 pytest.smoke.ini 跑 test_event_bus_smoke_external。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "event-bus-smoke-pytest:" in makefile
    block = makefile.split("event-bus-smoke-pytest:", 1)[1].split("\n\n", 1)[0]
    assert "pytest.smoke.ini" in block
    assert "backend/tests/test_event_bus_smoke_external.py" in block


def test_makefile_event_bus_smoke_contract_invokes_validate_result_script() -> None:
    """event-bus-smoke-contract 须调用 validate_event_bus_smoke_result.py。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "event-bus-smoke-contract:" in makefile
    assert "backend/scripts/validate_event_bus_smoke_result.py" in makefile


def test_makefile_event_bus_smoke_summary_contract_invokes_validate_summary_script() -> None:
    """event-bus-smoke-summary-contract 须调用 validate_event_bus_smoke_summary_result.py。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "event-bus-smoke-summary-contract:" in makefile
    assert "backend/scripts/validate_event_bus_smoke_summary_result.py" in makefile


def test_makefile_event_bus_smoke_contract_guard_status_json_invokes_print_script() -> None:
    """event-bus-smoke-contract-guard-status-json 须调用 print_event_bus_smoke_contract_guard_status.py。"""
    makefile = _read_script(repo_root() / "Makefile")
    assert "event-bus-smoke-contract-guard-status-json:" in makefile
    assert "backend/scripts/print_event_bus_smoke_contract_guard_status.py" in makefile


@pytest.mark.parametrize(
    "rel",
    (
        "scripts/quick-check.sh",
        "scripts/production-preflight.sh",
        "scripts/release-preflight.sh",
        "scripts/pr-check.sh",
        "scripts/pr-check-fast.sh",
        "scripts/merge-gate-contract-tests.sh",
        "scripts/test-no-fallback.sh",
        "scripts/check-nvmrc-align.sh",
        "scripts/compose-config-check.sh",
        "scripts/npm-scripts.sh",
    ),
)
def test_gate_shell_scripts_strict_bash_and_cwd_repo_root(rel: str) -> None:
    """CI / 预检常用入口须 bash shebang、set -euo、ROOT 解析仓库根并 cd \"$ROOT\"（与 lint-backend 等 cd backend 的脚本区分）。"""
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "$ROOT"' in text


def test_lint_backend_script_strict_bash_and_cwd_backend_tree() -> None:
    """lint 须在 backend/ 目录执行 ruff/mypy，但仍须由脚本解析仓库根。"""
    rel = "scripts/lint-backend.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "${ROOT}/backend"' in text


def test_check_dependency_version_policy_script_strict_bash_and_cwd_repo_root() -> None:
    """依赖策略脚本使用 ROOT_DIR 命名，仍 cd 到仓库根再读 requirements。"""
    rel = "scripts/check-dependency-version-policy.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "$ROOT_DIR"' in text


def test_helm_chart_check_script_strict_bash_and_root() -> None:
    """Helm 检查通过 dirname \"$0\" 定位仓库根（与直接 bash 路径调用一致）。"""
    rel = "scripts/helm-chart-check.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "$0")/.." && pwd)"' in text


def test_check_security_guardrails_ci_script_strict_bash_and_cwd_repo_root() -> None:
    """CI 合成 env 包装层须 cd 仓库根再 exec 真实 guardrails 脚本。"""
    rel = "scripts/check-security-guardrails-ci.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "$ROOT"' in text
    assert "exec bash scripts/check-security-guardrails.sh" in text


def test_check_security_guardrails_script_strict_bash_and_cwd_repo_root() -> None:
    """生产 guardrails 入口使用 ROOT_DIR 与 cd 仓库根。"""
    rel = "scripts/check-security-guardrails.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "$ROOT_DIR"' in text


@pytest.mark.parametrize(
    "rel",
    (
        "scripts/monitoring-config-check.sh",
        "scripts/k8s-manifest-check.sh",
        "scripts/dockerfile-hadolint-check.sh",
    ),
)
def test_backend_static_analysis_extra_checks_strict_bash_and_root(rel: str) -> None:
    """Compose 之后的监控 / K8s / Dockerfile 校验脚本用 ROOT 拼绝对路径，不要求 cd 仓库根。"""
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text


def test_healthcheck_script_strict_bash_and_cwd_repo_root() -> None:
    """healthcheck 在仓库根读 compose / .env 并探测端口，使用 ROOT_DIR 与 cd。"""
    rel = "scripts/healthcheck.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "${ROOT_DIR}"' in text


def test_doctor_script_strict_bash_and_cwd_repo_root() -> None:
    """doctor 在仓库根检查 compose / 端口 / .env，与 healthcheck 同型 ROOT_DIR。"""
    rel = "scripts/doctor.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "${ROOT_DIR}"' in text


def test_check_frontend_i18n_hardcoded_script_strict_bash_and_cwd_repo_root() -> None:
    """前端 i18n 基线扫描在仓库根解析 frontend/src，须 cd 仓库根。"""
    rel = "scripts/check-frontend-i18n-hardcoded.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "$ROOT"' in text


def test_scan_dependencies_script_strict_bash_and_cwd_repo_root() -> None:
    """dependency-scan（pip-audit）须在仓库根创建临时 venv 并读 requirements。"""
    rel = "scripts/scan-dependencies.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "$ROOT_DIR"' in text


@pytest.mark.parametrize(
    "rel",
    (
        "scripts/env-init.sh",
        "scripts/up.sh",
        "scripts/install.sh",
        "scripts/down.sh",
        "scripts/status.sh",
        "scripts/logs.sh",
        "scripts/up-gpu.sh",
        "scripts/up-prod.sh",
        "scripts/down-gpu.sh",
        "scripts/down-prod.sh",
        "scripts/install-gpu.sh",
        "scripts/install-prod.sh",
        "scripts/reset.sh",
    ),
)
def test_local_ops_compose_scripts_strict_bash_and_root_dir_cd(rel: str) -> None:
    """仓库根 docker-compose 运维脚本（含 gpu/prod、reset）须 ROOT_DIR + cd \"${ROOT_DIR}\"。"""
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "${ROOT_DIR}"' in text


_ACCEPTANCE_BACKEND_ENTRY_SCRIPTS: tuple[str, ...] = (
    "scripts/acceptance/run_all_unit_tests.sh",
    "scripts/acceptance/run_batch1_rbac.sh",
    "scripts/acceptance/run_batch2_audit.sh",
    "scripts/acceptance/run_batch3_trace.sh",
    "scripts/acceptance/run_batch4_workflow_debug.sh",
    "scripts/acceptance/run_batch5_web_security.sh",
    "scripts/acceptance/run_chaos_report_summary.sh",
    "scripts/acceptance/run_chaos_semi_integration.sh",
    "scripts/acceptance/run_chaos_system_injection.sh",
)


@pytest.mark.parametrize("rel", _ACCEPTANCE_BACKEND_ENTRY_SCRIPTS)
def test_acceptance_backend_entry_scripts_strict_bash_root_cd(rel: str) -> None:
    """acceptance 下批量 pytest/混沌入口：两层 dirname、校验 backend 存在后 cd \"$ROOT/backend\"。"""
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert (
        'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"' in text
    ), rel
    assert 'if [[ ! -d "${ROOT}/backend" ]]; then' in text, rel
    assert 'cd "$ROOT/backend"' in text, rel


def test_run_roadmap_acceptance_script_strict_bash_root_cd() -> None:
    """roadmap 门禁在本仓库根跑 pytest，须两层 dirname + cd \"$ROOT\"（相对 backend/ 检查）。"""
    rel = "scripts/acceptance/run_roadmap_acceptance.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert (
        'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"' in text
    ), rel
    assert 'cd "$ROOT"' in text, rel
    assert 'if [[ ! -d backend ]]; then' in text, rel


def test_roadmap_runner_common_script_strict_bash_uo_and_root() -> None:
    """roadmap 包装脚本公共库：故意不用 set -e，须在仓库根执行 make；ROOT 与 cd \"$ROOT\" 固定。"""
    rel = "scripts/acceptance/roadmap_runner_common.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -uo pipefail" in text
    assert "set -euo pipefail" not in text, rel
    assert (
        'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"' in text
    ), rel
    assert 'cd "$ROOT"' in text, rel
    assert "run_roadmap_make_target() {" in text, rel
    assert 'make "$target"' in text, rel


_ROADMAP_MAKE_WRAPPERS: tuple[tuple[str, str], ...] = (
    ("scripts/acceptance/roadmap_release_gate.sh", "roadmap-release-gate"),
    ("scripts/acceptance/roadmap_run_validated.sh", "roadmap-acceptance-run-validated"),
    ("scripts/acceptance/roadmap_validate_output.sh", "roadmap-acceptance-validate-output"),
)


@pytest.mark.parametrize("rel,expected_make_target", _ROADMAP_MAKE_WRAPPERS)
def test_roadmap_make_wrapper_scripts_source_common_and_target(
    rel: str, expected_make_target: str
) -> None:
    """roadmap_* 薄封装：与 roadmap_runner_common 同目录 source，再调用 run_roadmap_make_target。"""
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -uo pipefail" in text
    assert (
        'source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/roadmap_runner_common.sh"'
        in text
    ), rel
    assert f'ROADMAP_MAKE_TARGET="{expected_make_target}"' in text, rel
    assert 'run_roadmap_make_target "$ROADMAP_MAKE_TARGET" "$@"' in text, rel


def test_run_security_regression_script_strict_bash_uo_root_cd() -> None:
    """安全回归汇总：顶层 set -uo（批量 tolerate 失败）；ROOT + cd \"$ROOT\" + 相对 backend/；内含 run_batch。"""
    rel = "scripts/acceptance/run_security_regression.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    prefix = "\n".join(text.splitlines()[:12])
    assert "set -uo pipefail" in prefix, rel
    assert "set -euo pipefail" not in prefix, rel
    assert (
        'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"' in text
    ), rel
    assert 'cd "$ROOT"' in text, rel
    assert 'if [[ ! -d backend ]]; then' in text, rel
    assert "run_batch() {" in text, rel


def test_run_backend_sh_strict_bash_script_dir_and_backend_cd() -> None:
    """仓库根 run-backend.sh：一层 dirname → backend/，校验 main.py 后 conda run 或 python3 exec。"""
    path = repo_root() / "run-backend.sh"
    text = _read_script(path)
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    assert (
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in text
    )
    assert 'BACKEND_DIR="${SCRIPT_DIR}/backend"' in text
    assert 'cd "${BACKEND_DIR}"' in text
    assert "if [[ ! -f main.py ]]; then" in text
    assert "exec conda run" in text
    assert "exec python3 main.py" in text


def test_run_frontend_sh_strict_bash_script_dir_and_frontend_cd() -> None:
    """仓库根 run-frontend.sh：进入 frontend/，校验 package.json 后 exec npm run dev。"""
    path = repo_root() / "run-frontend.sh"
    text = _read_script(path)
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    assert (
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in text
    )
    assert 'FRONTEND_DIR="${SCRIPT_DIR}/frontend"' in text
    assert 'cd "${FRONTEND_DIR}"' in text
    assert "if [[ ! -f package.json ]]; then" in text
    assert "exec npm run dev" in text


def test_run_all_sh_strict_bash_orchestrates_root_launchers() -> None:
    """run-all.sh 在仓库根启 run-backend / run-frontend 子脚本，带 trap 清理与 wait。"""
    path = repo_root() / "run-all.sh"
    text = _read_script(path)
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    assert (
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in text
    )
    assert 'cd "$SCRIPT_DIR"' in text
    assert '"${SCRIPT_DIR}/run-backend.sh"' in text
    assert '"${SCRIPT_DIR}/run-frontend.sh"' in text
    assert "cleanup() {" in text
    assert "trap cleanup" in text
    assert text.rstrip().endswith("wait")


def test_backend_script_workflow_control_flow_regression_strict_bash_repo_root() -> None:
    """backend/scripts 工作流控制流回归：从 scripts/ 上溯两层到 monorepo 根再 pytest。"""
    rel = "backend/scripts/test_workflow_control_flow_regression.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert (
        'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"' in text
    ), rel
    assert 'cd "$ROOT_DIR"' in text, rel
    assert 'if [[ ! -d backend ]]; then' in text, rel
    assert 'if [[ ! -f pytest.ini ]]; then' in text, rel
    assert "PYTHONPATH=backend pytest" in text, rel
    assert "backend/tests/test_workflow_control_flow_regression.py" in text, rel


def test_backend_script_tenant_security_regression_strict_bash_uo_backend_root() -> None:
    """租户安全回归：顶层 set -uo；从 backend/scripts 定位 backend 包根再批量 pytest。"""
    rel = "backend/scripts/test_tenant_security_regression.sh"
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    prefix = "\n".join(text.splitlines()[:8])
    assert "set -uo pipefail" in prefix, rel
    assert "set -euo pipefail" not in prefix, rel
    assert (
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in text
    ), rel
    assert 'BACKEND_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"' in text, rel
    assert 'cd "${BACKEND_ROOT}"' in text, rel
    assert "if [[ ! -f main.py ]]" in text, rel


_GITHUB_SMART_ROUTING_GATE_SCRIPTS: tuple[str, ...] = (
    ".github/actions/smart-routing-gates/canary_admin_gate.sh",
    ".github/actions/smart-routing-gates/least_loaded_gate.sh",
)


@pytest.mark.parametrize("rel", _GITHUB_SMART_ROUTING_GATE_SCRIPTS)
def test_github_smart_routing_gate_scripts_strict_bash_env_and_trap(rel: str) -> None:
    """CI smart-routing 冒烟门：必需 env、临时文件与 trap；脚本内含 curl 探测。"""
    text = _read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert ': "${BASE_URL:?}"' in text
    assert '"${ADMIN_KEY:?}"' in text
    assert "mktemp" in text
    assert "trap " in text
    assert "curl " in text
