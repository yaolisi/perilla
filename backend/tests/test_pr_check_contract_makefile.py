from __future__ import annotations

import re

import pytest

from tests.pr_check_contract import read_script
from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo


def test_makefile_install_lint_tools_targets_requirements_file() -> None:
    """install-lint-tools 须委托 pip 安装 backend/requirements/lint-tools.txt（与 CI 同源 pin）。"""
    makefile = read_script(repo_root() / "Makefile")
    assert (
        "install-lint-tools:\n\t@pip install -r backend/requirements/lint-tools.txt"
        in makefile
    )


def test_makefile_test_no_fallback_and_workflow_control_flow_delegate_to_scripts() -> (
    None
):
    """make test-no-fallback / test-workflow-control-flow 须固定委托 bash 脚本，便于与 CI 入口对齐。"""
    makefile = read_script(repo_root() / "Makefile")
    assert "@bash scripts/test-no-fallback.sh $(TEST_ARGS)" in makefile
    assert "@bash backend/scripts/test_workflow_control_flow_regression.sh" in makefile


def test_makefile_production_and_release_preflight_delegate_to_scripts() -> None:
    """Makefile production-preflight / release-preflight 须委托仓库根 bash 脚本。"""
    makefile = read_script(repo_root() / "Makefile")
    assert "@bash scripts/production-preflight.sh" in makefile
    assert "@bash scripts/release-preflight.sh" in makefile


def test_makefile_ci_targets_alias_pr_check_recipes() -> None:
    """make ci / ci-fast 仅为 pr-check / pr-check-fast 别名（与 package.json 中 npm run ci* 一致）。"""
    makefile = read_script(repo_root() / "Makefile")
    assert re.search(r"^ci:\s*pr-check\s*$", makefile, re.MULTILINE)
    assert re.search(r"^ci-fast:\s*pr-check-fast\s*$", makefile, re.MULTILINE)


def test_makefile_quick_check_delegates_to_script() -> None:
    """make quick-check 须委托 scripts/quick-check.sh（最小 nvmrc + lint）。"""
    makefile = read_script(repo_root() / "Makefile")
    assert "@bash scripts/quick-check.sh" in makefile


def test_quick_check_script_runs_nvmrc_align_and_lint_backend() -> None:
    """quick-check 仅跑 nvmrc 对齐 + lint-backend，并在输出中提示 merge-gate / docker 冒烟路径。"""
    rel = "scripts/quick-check.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert "bash scripts/check-nvmrc-align.sh" in text
    assert "bash scripts/lint-backend.sh" in text
    assert "install-lint-tools" in text
    assert "merge-gate-contract-tests" in text
    assert "docker-build-all" in text or "docker-image-build" in text


def test_makefile_helm_deploy_contract_and_merge_gate_targets_invoke_manifest_script() -> (
    None
):
    """helm-deploy-contract-check 依赖 helm-chart-check 并跑 merge-gate -q；merge-gate-contract-tests 仅 manifest。"""
    makefile = read_script(repo_root() / "Makefile")
    assert re.search(
        r"^helm-deploy-contract-check:\s*helm-chart-check\s*$",
        makefile,
        re.MULTILINE,
    )
    assert (
        "helm-deploy-contract-check: helm-chart-check\n\t@bash scripts/merge-gate-contract-tests.sh -q"
        in makefile
    )
    assert (
        "merge-gate-contract-tests:\n\t@bash scripts/merge-gate-contract-tests.sh"
        in makefile
    )


def test_makefile_pr_check_includes_build_frontend_pr_check_fast_skips_it() -> None:
    """pr-check 配方含 build-frontend；pr-check-fast 不含（与 help 文案一致）。"""
    makefile = read_script(repo_root() / "Makefile")
    pr = re.search(r"^pr-check:.*$", makefile, re.MULTILINE)
    pr_fast = re.search(r"^pr-check-fast:.*$", makefile, re.MULTILINE)
    assert pr is not None and "build-frontend" in pr.group(0)
    assert pr_fast is not None and "build-frontend" not in pr_fast.group(0)


def test_makefile_backend_static_analysis_extras_matches_ci_infra_tail() -> None:
    """backend-static-analysis-extras 的依赖顺序与主后端 CI 中 merge gate 之后五步一致。"""
    makefile = read_script(repo_root() / "Makefile")
    assert re.search(
        r"^backend-static-analysis-extras:\s*"
        r"compose-config-check\s+monitoring-config-check\s+k8s-manifest-check\s+"
        r"dockerfile-hadolint-check\s+security-guardrails-ci\s*$",
        makefile,
        re.MULTILINE,
    )


def test_makefile_dependency_policy_and_scan_delegate_to_scripts() -> None:
    """dependency-policy / dependency-scan 须委托对应 bash 脚本（与 dependency-security-scan workflow 同源）。"""
    makefile = read_script(repo_root() / "Makefile")
    assert (
        "dependency-policy:\n\t@bash scripts/check-dependency-version-policy.sh"
        in makefile
    )
    assert "dependency-scan:\n\t@bash scripts/scan-dependencies.sh" in makefile


def test_makefile_ci_related_targets_delegate_to_scripts_under_scripts_dir() -> None:
    """pr-check / backend-static-analysis-extras 所用 Makefile 目标须 bash scripts/*（与 workflow / shell 契约一致）。"""
    makefile = read_script(repo_root() / "Makefile")
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
    makefile = read_script(repo_root() / "Makefile")
    assert "healthcheck:\n\t@bash scripts/healthcheck.sh" in makefile
    assert "doctor:\n\t@bash scripts/doctor.sh" in makefile
    assert "lint-backend:\n\t@bash scripts/lint-backend.sh" in makefile
    assert re.search(r"^lint:\s*lint-backend\s*$", makefile, re.MULTILINE)


def test_makefile_docker_build_targets_use_buildkit_and_smoke_tags() -> None:
    """docker-build-* 与 docker-image-build / 文档冒烟一致：BuildKit、docker/*.Dockerfile、本地 tag。"""
    makefile = read_script(repo_root() / "Makefile")
    assert "DOCKER_BUILDKIT=1" in makefile
    assert (
        "docker/backend.Dockerfile" in makefile and "perilla-backend:local" in makefile
    )
    assert (
        "docker/frontend.Dockerfile" in makefile
        and "perilla-frontend:local" in makefile
    )
    assert re.search(
        r"^docker-build-all:\s*docker-build-backend\s+docker-build-frontend\s*$",
        makefile,
        re.MULTILINE,
    )


def test_makefile_npm_scripts_targets_delegate_to_wrapper() -> None:
    """make npm-scripts / npm-scripts-json 须委托 scripts/npm-scripts.sh（与 package.json / CI grep 约定一致）。"""
    makefile = read_script(repo_root() / "Makefile")
    assert "npm-scripts:\n\t@bash scripts/npm-scripts.sh" in makefile
    assert "npm-scripts-json:\n\t@bash scripts/npm-scripts.sh --json" in makefile


def test_npm_scripts_sh_dispatches_default_json_help_and_unknown() -> None:
    """npm-scripts.sh：ROOT + roadmap gate 前缀；case 分支 exec npm run / npm pkg get / usage。"""
    rel = "scripts/npm-scripts.sh"
    text = read_script(repo_root() / rel)
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
    makefile = read_script(repo_root() / "Makefile")
    assert "install:\n\t@bash scripts/install.sh" in makefile
    assert "env-init:\n\t@bash scripts/env-init.sh" in makefile
    assert "install-prod:\n\t@bash scripts/install-prod.sh" in makefile
    assert (
        "bootstrap:\n\t@$(MAKE) env-init\n\t@$(MAKE) doctor\n\t@$(MAKE) install\n"
    ) in makefile
    assert (
        "bootstrap-prod:\n"
        "\t@$(MAKE) env-init\n"
        "\t@DOCTOR_STRICT_WARNINGS=1 $(MAKE) doctor\n"
        "\t@$(MAKE) install-prod\n"
    ) in makefile


def test_makefile_local_dev_and_install_variants_delegate_to_entry_scripts() -> None:
    """local-* 委托仓库根 run-*.sh；GPU / prod-soft 安装委托 scripts/*。"""
    makefile = read_script(repo_root() / "Makefile")
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
    makefile = read_script(repo_root() / "Makefile")
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
    makefile = read_script(repo_root() / "Makefile")
    overlay = (
        "docker compose -f docker-compose.yml "
        "-f deploy/monitoring/docker-compose.monitoring.yml"
    )
    assert f"up-monitoring:\n\t@{overlay} up -d" in makefile, (
        "expected up-monitoring with compose overlay"
    )
    assert f"down-monitoring:\n\t@{overlay} down" in makefile, (
        "expected down-monitoring with compose overlay"
    )
    assert f"status-monitoring:\n\t@{overlay} ps" in makefile, (
        "expected status-monitoring with compose overlay"
    )


def test_makefile_roadmap_acceptance_all_and_unit_match_scripts_and_pytest_list() -> (
    None
):
    """roadmap-acceptance-all 委托 acceptance 脚本；unit 目标固定四条 pytest 路径 + -k roadmap。"""
    makefile = read_script(repo_root() / "Makefile")
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
    makefile = read_script(repo_root() / "Makefile")
    assert "monitoring-smoke:" in makefile
    assert "backend/scripts/monitoring_smoke.py" in makefile


def test_makefile_tenant_workflow_and_smart_routing_test_entrypoints() -> None:
    """tenant_isolation / workflow 回归 / smart-routing 冒烟与 Makefile 配方一致。"""
    makefile = read_script(repo_root() / "Makefile")
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
    makefile = read_script(repo_root() / "Makefile")
    assert ("cb-fast:\n\t@$(MAKE) cb-tests\n\t@$(MAKE) cb-doctor\n") in makefile


def test_makefile_cb_tests_lists_continuous_batch_pytest_modules() -> None:
    """cb-tests 固定四条 continuous batch 契约测试（与 continuous-batch-ci、脚本实现对齐）。"""
    makefile = read_script(repo_root() / "Makefile")
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
    makefile = read_script(repo_root() / "Makefile")
    assert "roadmap-acceptance-smoke:" in makefile
    assert "backend/scripts/roadmap_acceptance_smoke.py" in makefile


def test_makefile_roadmap_acceptance_validate_output_invokes_backend_validator() -> (
    None
):
    """roadmap-acceptance-validate-output 须调用 validate_roadmap_acceptance_result.py。"""
    makefile = read_script(repo_root() / "Makefile")
    assert "roadmap-acceptance-validate-output:" in makefile
    assert "backend/scripts/validate_roadmap_acceptance_result.py" in makefile


def test_makefile_event_bus_smoke_runs_backend_dlq_smoke_script() -> None:
    """event-bus-smoke 须调用 backend/scripts/event_bus_dlq_smoke.py。"""
    makefile = read_script(repo_root() / "Makefile")
    assert "event-bus-smoke:" in makefile
    assert "backend/scripts/event_bus_dlq_smoke.py" in makefile


def test_makefile_event_bus_smoke_pytest_runs_external_smoke_test() -> None:
    """event-bus-smoke-pytest 须用 pytest.smoke.ini 跑 test_event_bus_smoke_external。"""
    makefile = read_script(repo_root() / "Makefile")
    assert "event-bus-smoke-pytest:" in makefile
    block = makefile.split("event-bus-smoke-pytest:", 1)[1].split("\n\n", 1)[0]
    assert "pytest.smoke.ini" in block
    assert "backend/tests/test_event_bus_smoke_external.py" in block


def test_makefile_event_bus_smoke_contract_invokes_validate_result_script() -> None:
    """event-bus-smoke-contract 须调用 validate_event_bus_smoke_result.py。"""
    makefile = read_script(repo_root() / "Makefile")
    assert "event-bus-smoke-contract:" in makefile
    assert "backend/scripts/validate_event_bus_smoke_result.py" in makefile


def test_makefile_event_bus_smoke_summary_contract_invokes_validate_summary_script() -> (
    None
):
    """event-bus-smoke-summary-contract 须调用 validate_event_bus_smoke_summary_result.py。"""
    makefile = read_script(repo_root() / "Makefile")
    assert "event-bus-smoke-summary-contract:" in makefile
    assert "backend/scripts/validate_event_bus_smoke_summary_result.py" in makefile


def test_makefile_event_bus_smoke_contract_guard_status_json_invokes_print_script() -> (
    None
):
    """event-bus-smoke-contract-guard-status-json 须调用 print_event_bus_smoke_contract_guard_status.py。"""
    makefile = read_script(repo_root() / "Makefile")
    assert "event-bus-smoke-contract-guard-status-json:" in makefile
    assert "backend/scripts/print_event_bus_smoke_contract_guard_status.py" in makefile
