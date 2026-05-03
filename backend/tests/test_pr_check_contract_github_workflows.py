from __future__ import annotations

import re

import pytest

from tests.pr_check_contract import (
    read_script,
    workflow_job_names_with_runs_on_but_no_timeout,
)
from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo


def _collect_backend_static_analysis_on_paths(wf: str, event: str) -> list[str]:
    """解析 backend-static-analysis.yml 中 `on.<event>.paths` 的 glob 列表（顺序敏感）。"""
    lines = wf.splitlines()
    head = f"  {event}:"
    start = next((i for i, ln in enumerate(lines) if ln == head), None)
    assert start is not None, f"missing {head} in backend-static-analysis.yml"
    i = start + 1
    while i < len(lines):
        if lines[i].strip() == "paths:":
            i += 1
            break
        i += 1
    else:
        raise AssertionError(f"no paths: block under {head}")

    out: list[str] = []
    while i < len(lines):
        line = lines[i]
        if line and line[0] not in " \t#" and line.strip().endswith(":"):
            break
        if (
            line.startswith("  ")
            and not line.startswith("    ")
            and line.rstrip().endswith(":")
        ):
            break
        m = re.match(r'^\s+-\s+"([^"]+)"\s*$', line)
        if m:
            out.append(m.group(1))
        i += 1
    return out


def test_dependency_review_workflow_matches_supply_chain_gate() -> None:
    """PR 依赖审查须存在且与 critical 阈值一致（与 frontend npm audit / pip graph 对齐）。"""
    wf = read_script(repo_root() / ".github/workflows/dependency-review.yml")
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
                mismatches.append(
                    f"{path.relative_to(root)}: {vm.group(1)} (!= {py_expected})"
                )
    assert not mismatches, (
        "python-version drift vs docker/backend.Dockerfile:\n" + "\n".join(mismatches)
    )


def test_dependabot_config_covers_backend_frontend_actions_and_docker() -> None:
    """Dependabot 须覆盖 pip、npm、Actions、Docker 基础镜像（供应链入口）。"""
    raw = read_script(repo_root() / ".github/dependabot.yml")
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
        missing = workflow_job_names_with_runs_on_but_no_timeout(
            path.read_text(encoding="utf-8")
        )
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
    wf = read_script(repo_root() / ".github/workflows/security-regression.yml")
    assert "scripts/check-nvmrc-align.sh" in wf
    assert "node-version-file: .nvmrc" in wf
    n = wf.find("check-nvmrc-align.sh")
    m = wf.find("Setup Node.js")
    assert n != -1 and m != -1 and n < m


def test_frontend_build_workflow_includes_i18n_and_npm_audit_critical() -> None:
    """纯前端 PR 须跑 i18n 基线与 critical 级 npm audit（与 make pr-check / release-preflight 对齐）。"""
    wf = read_script(repo_root() / ".github/workflows/frontend-build.yml")
    assert "scripts/check-frontend-i18n-hardcoded.sh" in wf
    assert "npm audit --audit-level=critical" in wf


def test_docker_image_build_workflow_aligns_makefile_smoke() -> None:
    """docker-image-build 须与 Makefile docker-build-* 同源命令；含 Trivy 与 main 推 GHCR。"""
    root = repo_root()
    wf = read_script(root / ".github/workflows/docker-image-build.yml")
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
        text = read_script(path)
        assert "workflow_dispatch:" in text, (
            f"{fname} should declare workflow_dispatch for manual runs"
        )


def test_backend_static_analysis_triggers_on_deploy_k8s() -> None:
    """deploy、Compose、healthcheck、Dockerfile、监控目录变更须触发静态分析与合并门禁。"""
    wf = read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    assert ".github/workflows/**" in wf
    assert "deploy/k8s/**" in wf
    assert "deploy/monitoring/**" in wf
    assert "docker-compose.yml" in wf
    assert "scripts/healthcheck.sh" in wf
    assert "docker/**" in wf
    assert "scripts/doctor.sh" in wf


def test_backend_static_analysis_pr_and_push_path_filters_match() -> None:
    """PR 与 main/master push 的路径过滤须一致，避免只在一侧触发 CI。"""
    wf = read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    pr_paths = _collect_backend_static_analysis_on_paths(wf, "pull_request")
    push_paths = _collect_backend_static_analysis_on_paths(wf, "push")
    assert pr_paths == push_paths, (
        "pull_request.paths vs push.paths mismatch:\n"
        f"  only in PR:   {sorted(set(pr_paths) - set(push_paths))!r}\n"
        f"  only in push: {sorted(set(push_paths) - set(pr_paths))!r}"
    )


def test_backend_static_analysis_includes_dependency_version_policy() -> None:
    """与 dependency-security-scan 同源策略检查须出现在主后端 CI，防 requirements 漂移。"""
    wf = read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    assert "scripts/check-dependency-version-policy.sh" in wf
    assert "Dependency version policy" in wf
    assert "permissions:" in wf
    assert "contents: read" in wf


def test_backend_static_analysis_includes_security_guardrails_step() -> None:
    """CI 须跑 production guardrails；合成 env 与 scripts/check-security-guardrails-ci.sh 同源。"""
    root = repo_root()
    wf = read_script(root / ".github/workflows/backend-static-analysis.yml")
    assert "scripts/check-security-guardrails-ci.sh" in wf
    ci = read_script(root / "scripts" / "check-security-guardrails-ci.sh")
    assert "DATABASE_URL" in ci
    assert "RBAC_ADMIN_API_KEYS" in ci


def test_backend_static_analysis_test_no_fallback_step_uses_repo_root_entry() -> None:
    """主后端 CI 须在仓库根执行 scripts/test-no-fallback.sh -q，与 make / npm run test-no-fallback 同源。"""
    wf = read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    assert "Run test-no-fallback suite" in wf
    anchor = wf.find("Run test-no-fallback suite")
    assert anchor != -1
    window = wf[anchor : anchor + 400]
    assert "bash scripts/test-no-fallback.sh -q" in window
    assert "working-directory: ${{ github.workspace }}" in window


def test_workflow_control_flow_regression_workflow_runs_script_from_backend_cwd() -> (
    None
):
    """workflow-control-flow-regression 默认 cwd=backend，./scripts/... 对应仓库内 backend/scripts/...。"""
    wf = read_script(
        repo_root() / ".github/workflows/workflow-control-flow-regression.yml"
    )
    assert "working-directory: backend" in wf
    assert "chmod +x scripts/test_workflow_control_flow_regression.sh" in wf
    assert "./scripts/test_workflow_control_flow_regression.sh" in wf


def test_backend_static_analysis_merge_gate_step_uses_repo_root_entry() -> None:
    """主后端 CI 须在仓库根执行 merge-gate-contract-tests.sh -q（与 make helm-deploy-contract-check 等同源列表）。"""
    wf = read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    assert "Helm & merge gate contract tests" in wf
    anchor = wf.find("Helm & merge gate contract tests")
    assert anchor != -1
    window = wf[anchor : anchor + 400]
    assert "bash scripts/merge-gate-contract-tests.sh -q" in window
    assert "working-directory: ${{ github.workspace }}" in window


def test_dependency_security_scan_workflow_invokes_policy_and_scan_scripts() -> None:
    """dependency-security-scan 在仓库根 chmod + 执行 policy 与 pip-audit 封装脚本。"""
    wf = read_script(repo_root() / ".github/workflows/dependency-security-scan.yml")
    assert "chmod +x scripts/check-dependency-version-policy.sh" in wf
    assert "./scripts/check-dependency-version-policy.sh" in wf
    assert "chmod +x scripts/scan-dependencies.sh" in wf
    assert "./scripts/scan-dependencies.sh" in wf


def test_tenant_security_regression_workflow_runs_script_from_backend_cwd() -> None:
    """tenant-security-regression 与 workflow-control-flow 同型：cwd=backend 下跑 backend/scripts 入口。"""
    wf = read_script(repo_root() / ".github/workflows/tenant-security-regression.yml")
    assert "working-directory: backend" in wf
    assert "chmod +x scripts/test_tenant_security_regression.sh" in wf
    assert "./scripts/test_tenant_security_regression.sh" in wf


def test_security_regression_workflow_runs_acceptance_suite_from_repo_root() -> None:
    """security-regression 在仓库根 chmod + 执行 run_security_regression.sh（聚合 acceptance 批次）。"""
    wf = read_script(repo_root() / ".github/workflows/security-regression.yml")
    assert "Run security regression suite" in wf
    anchor = wf.find("Run security regression suite")
    assert anchor != -1
    window = wf[anchor : anchor + 620]
    assert "chmod +x scripts/acceptance/run_security_regression.sh" in window
    assert "./scripts/acceptance/run_security_regression.sh" in window
    assert "chmod +x scripts/acceptance/run_batch1_rbac.sh" in window


def test_smart_routing_gates_composite_action_runs_bundled_gate_scripts() -> None:
    """composite action 须调用包内 canary / least_loaded 脚本（与 gate .sh 契约一致）。"""
    action = read_script(repo_root() / ".github/actions/smart-routing-gates/action.yml")
    assert 'bash "${GITHUB_ACTION_PATH}/canary_admin_gate.sh"' in action
    assert 'bash "${GITHUB_ACTION_PATH}/least_loaded_gate.sh"' in action


def test_knowledge_rag_ci_workflow_runs_smoke_script_from_backend_cwd() -> None:
    """knowledge-rag-ci 在 backend cwd 下执行 scripts/knowledge_acceptance_smoke.py。"""
    wf = read_script(repo_root() / ".github/workflows/knowledge-rag-ci.yml")
    assert "Run knowledge acceptance smoke" in wf
    anchor = wf.find("Run knowledge acceptance smoke")
    assert anchor != -1
    window = wf[anchor : anchor + 700]
    assert "working-directory: backend" in window
    assert "scripts/knowledge_acceptance_smoke.py" in window


def test_monitoring_alerting_e2e_workflow_invokes_make_and_compose_overlays() -> None:
    """monitoring-alerting-e2e 经 make monitoring-e2e-clean；失败时 dump 与 compose 监控叠加文件一致。"""
    wf = read_script(repo_root() / ".github/workflows/monitoring-alerting-e2e.yml")
    assert "make monitoring-e2e-clean" in wf
    assert "docker-compose.yml" in wf
    assert "deploy/monitoring/docker-compose.monitoring.yml" in wf


def test_continuous_batch_ci_workflow_invokes_make_cb_targets() -> None:
    """continuous-batch-ci：单元阶段 cb-fast；workflow_dispatch gate 阶段 cb-pipeline。"""
    wf = read_script(repo_root() / ".github/workflows/continuous-batch-ci.yml")
    assert "make cb-fast" in wf
    assert "make cb-pipeline" in wf


def test_backend_static_analysis_tenant_isolation_step_uses_make_target() -> None:
    """Tenant isolation 须在仓库根执行 make test-tenant-isolation（与 Makefile / marker 契约一致）。"""
    wf = read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    assert "Tenant isolation suite" in wf
    anchor = wf.find("Tenant isolation suite")
    assert anchor != -1
    window = wf[anchor : anchor + 280]
    assert "make test-tenant-isolation" in window
    assert "working-directory: ${{ github.workspace }}" in window


def test_backend_static_analysis_dependency_policy_and_lint_steps_use_workspace_scripts() -> (
    None
):
    """policy / lint-backend 步骤须在 github.workspace 下调 bash scripts/*（默认 job cwd 为 backend）。"""
    wf = read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
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
    wf = read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
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
    wf = read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
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
    wf = read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
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
    wf = read_script(repo_root() / ".github/workflows/event-bus-dlq-smoke.yml")
    assert "make event-bus-smoke-validate-schema-version" in wf
    assert "make event-bus-smoke-preflight" in wf
    assert "make event-bus-smoke-unit" in wf
    assert "make event-bus-smoke-contract-guard" in wf
    assert "make event-bus-smoke-run-validated" in wf
    assert "make event-bus-smoke-pytest" in wf
    assert "make event-bus-smoke-summary-contract" in wf


def test_smart_routing_experiment_promote_workflow_invokes_make_smart_routing_targets() -> (
    None
):
    """smart-routing-experiment-promote 通过 Makefile smart-routing-* 编排实验与扫描/压测。"""
    wf = read_script(
        repo_root() / ".github/workflows/smart-routing-experiment-promote.yml"
    )
    assert "make smart-routing-all-checks" in wf
    assert "make smart-routing-experiment" in wf
    assert "make smart-routing-param-scan" in wf
    assert "make smart-routing-load-test" in wf


def test_frontend_build_workflow_orders_nvmrc_i18n_before_node_and_audit() -> None:
    """frontend-build：nvmrc 对齐须早于 setup-node；i18n 基线须早于 npm audit。"""
    wf = read_script(repo_root() / ".github/workflows/frontend-build.yml")
    body = wf.split("jobs:", 1)[1]
    nvmrc = body.find("bash scripts/check-nvmrc-align.sh")
    setup_node = body.find("actions/setup-node@v4")
    assert nvmrc != -1 and setup_node != -1 and nvmrc < setup_node
    i18n = body.find("bash scripts/check-frontend-i18n-hardcoded.sh")
    audit = body.find("npm audit --audit-level=critical")
    assert i18n != -1 and audit != -1 and i18n < audit


def test_smart_routing_gates_matrix_workflow_uses_composite_action() -> None:
    """smart-routing-gates-matrix 通过本地 composite action 跑 canary / least_loaded 门。"""
    wf = read_script(repo_root() / ".github/workflows/smart-routing-gates-matrix.yml")
    assert "uses: ./.github/actions/smart-routing-gates" in wf
    assert "workflow_dispatch:" in wf
    assert "vars.SMART_ROUTING_BASE_URL" in wf


def test_knowledge_rag_ci_workflow_runs_default_pytest_suites_from_backend() -> None:
    """knowledge-rag-ci 默认 job 在 backend 下跑 knowledge 相关 pytest 文件列表。"""
    wf = read_script(repo_root() / ".github/workflows/knowledge-rag-ci.yml")
    assert "Run knowledge test suites" in wf
    anchor = wf.find("Run knowledge test suites")
    assert anchor != -1
    window = wf[anchor : anchor + 500]
    assert "working-directory: backend" in window
    assert "tests/test_knowledge_base_store.py" in window


def test_backend_static_analysis_pip_install_uses_lint_tools_requirements() -> None:
    """主后端 CI 须用 requirements/lint-tools.txt 固定 ruff/mypy（与 lint-backend.sh 同源）。"""
    wf = read_script(repo_root() / ".github/workflows/backend-static-analysis.yml")
    assert "backend/requirements/lint-tools.txt" in wf
    assert "pip install -r requirements/base.txt -r requirements/lint-tools.txt" in wf
    assert "pip install -r requirements/base.txt ruff mypy" not in wf
    anchor = wf.find("cache-dependency-path:")
    assert anchor != -1
    cache_block = wf[anchor : anchor + 280]
    assert "backend/requirements/base.txt" in cache_block
    assert "backend/requirements/lint-tools.txt" in cache_block


def test_workflows_invoking_lint_backend_pin_lint_tools() -> None:
    """凡在 CI 中执行 lint-backend.sh 的 workflow 须出现 lint-tools.txt（防复制 job 时漏装工具）。"""
    wf_dir = repo_root() / ".github" / "workflows"
    run_needle = "bash scripts/lint-backend.sh"
    for path in sorted(wf_dir.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if run_needle not in text:
            continue
        assert "lint-tools.txt" in text, (
            f"{path.name}: runs lint-backend.sh but missing lint-tools.txt "
            "(pip install or cache-dependency-path)"
        )
