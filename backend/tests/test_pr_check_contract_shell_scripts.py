from __future__ import annotations

import pytest

from tests.pr_check_contract import read_script
from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo

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

_ROADMAP_MAKE_WRAPPERS: tuple[tuple[str, str], ...] = (
    ("scripts/acceptance/roadmap_release_gate.sh", "roadmap-release-gate"),
    ("scripts/acceptance/roadmap_run_validated.sh", "roadmap-acceptance-run-validated"),
    (
        "scripts/acceptance/roadmap_validate_output.sh",
        "roadmap-acceptance-validate-output",
    ),
)

_GITHUB_SMART_ROUTING_GATE_SCRIPTS: tuple[str, ...] = (
    ".github/actions/smart-routing-gates/canary_admin_gate.sh",
    ".github/actions/smart-routing-gates/least_loaded_gate.sh",
)


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
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "$ROOT"' in text


def test_lint_backend_script_strict_bash_and_cwd_backend_tree() -> None:
    """lint 须在 backend/ 目录执行 ruff/mypy，但仍须由脚本解析仓库根。"""
    rel = "scripts/lint-backend.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "${ROOT}/backend"' in text


def test_check_dependency_version_policy_script_strict_bash_and_cwd_repo_root() -> None:
    """依赖策略脚本使用 ROOT_DIR 命名，仍 cd 到仓库根再读 requirements。"""
    rel = "scripts/check-dependency-version-policy.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "$ROOT_DIR"' in text


def test_helm_chart_check_script_strict_bash_and_root() -> None:
    """Helm 检查通过 dirname \"$0\" 定位仓库根（与直接 bash 路径调用一致）。"""
    rel = "scripts/helm-chart-check.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "$0")/.." && pwd)"' in text


def test_check_security_guardrails_ci_script_strict_bash_and_cwd_repo_root() -> None:
    """CI 合成 env 包装层须 cd 仓库根再 exec 真实 guardrails 脚本。"""
    rel = "scripts/check-security-guardrails-ci.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "$ROOT"' in text
    assert "exec bash scripts/check-security-guardrails.sh" in text


def test_check_security_guardrails_script_strict_bash_and_cwd_repo_root() -> None:
    """生产 guardrails 入口使用 ROOT_DIR 与 cd 仓库根。"""
    rel = "scripts/check-security-guardrails.sh"
    text = read_script(repo_root() / rel)
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
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text


def test_healthcheck_script_strict_bash_and_cwd_repo_root() -> None:
    """healthcheck 在仓库根读 compose / .env 并探测端口，使用 ROOT_DIR 与 cd。"""
    rel = "scripts/healthcheck.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "${ROOT_DIR}"' in text


def test_doctor_script_strict_bash_and_cwd_repo_root() -> None:
    """doctor 在仓库根检查 compose / 端口 / .env，与 healthcheck 同型 ROOT_DIR。"""
    rel = "scripts/doctor.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "${ROOT_DIR}"' in text


def test_check_frontend_i18n_hardcoded_script_strict_bash_and_cwd_repo_root() -> None:
    """前端 i18n 基线扫描在仓库根解析 frontend/src，须 cd 仓库根。"""
    rel = "scripts/check-frontend-i18n-hardcoded.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "$ROOT"' in text


def test_scan_dependencies_script_strict_bash_and_cwd_repo_root() -> None:
    """dependency-scan（pip-audit）须在仓库根创建临时 venv 并读 requirements。"""
    rel = "scripts/scan-dependencies.sh"
    text = read_script(repo_root() / rel)
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
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in text
    assert 'cd "${ROOT_DIR}"' in text


@pytest.mark.parametrize("rel", _ACCEPTANCE_BACKEND_ENTRY_SCRIPTS)
def test_acceptance_backend_entry_scripts_strict_bash_root_cd(rel: str) -> None:
    """acceptance 下批量 pytest/混沌入口：两层 dirname、校验 backend 存在后 cd \"$ROOT/backend\"。"""
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"' in text, rel
    assert 'if [[ ! -d "${ROOT}/backend" ]]; then' in text, rel
    assert 'cd "$ROOT/backend"' in text, rel


def test_run_roadmap_acceptance_script_strict_bash_root_cd() -> None:
    """roadmap 门禁在本仓库根跑 pytest，须两层 dirname + cd \"$ROOT\"（相对 backend/ 检查）。"""
    rel = "scripts/acceptance/run_roadmap_acceptance.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"' in text, rel
    assert 'cd "$ROOT"' in text, rel
    assert "if [[ ! -d backend ]]; then" in text, rel


def test_roadmap_runner_common_script_strict_bash_uo_and_root() -> None:
    """roadmap 包装脚本公共库：故意不用 set -e，须在仓库根执行 make；ROOT 与 cd \"$ROOT\" 固定。"""
    rel = "scripts/acceptance/roadmap_runner_common.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -uo pipefail" in text
    assert "set -euo pipefail" not in text, rel
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"' in text, rel
    assert 'cd "$ROOT"' in text, rel
    assert "run_roadmap_make_target() {" in text, rel
    assert 'make "$target"' in text, rel


@pytest.mark.parametrize("rel,expected_make_target", _ROADMAP_MAKE_WRAPPERS)
def test_roadmap_make_wrapper_scripts_source_common_and_target(
    rel: str, expected_make_target: str
) -> None:
    """roadmap_* 薄封装：与 roadmap_runner_common 同目录 source，再调用 run_roadmap_make_target。"""
    text = read_script(repo_root() / rel)
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
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    prefix = "\n".join(text.splitlines()[:12])
    assert "set -uo pipefail" in prefix, rel
    assert "set -euo pipefail" not in prefix, rel
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"' in text, rel
    assert 'cd "$ROOT"' in text, rel
    assert "if [[ ! -d backend ]]; then" in text, rel
    assert "run_batch() {" in text, rel


def test_run_backend_sh_strict_bash_script_dir_and_backend_cd() -> None:
    """仓库根 run-backend.sh：一层 dirname → backend/，校验 main.py 后 conda run 或 python3 exec。"""
    path = repo_root() / "run-backend.sh"
    text = read_script(path)
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    assert 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in text
    assert 'BACKEND_DIR="${SCRIPT_DIR}/backend"' in text
    assert 'cd "${BACKEND_DIR}"' in text
    assert "if [[ ! -f main.py ]]; then" in text
    assert "exec conda run" in text
    assert "exec python3 main.py" in text


def test_run_frontend_sh_strict_bash_script_dir_and_frontend_cd() -> None:
    """仓库根 run-frontend.sh：进入 frontend/，校验 package.json 后 exec npm run dev。"""
    path = repo_root() / "run-frontend.sh"
    text = read_script(path)
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    assert 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in text
    assert 'FRONTEND_DIR="${SCRIPT_DIR}/frontend"' in text
    assert 'cd "${FRONTEND_DIR}"' in text
    assert "if [[ ! -f package.json ]]; then" in text
    assert "exec npm run dev" in text


def test_run_all_sh_strict_bash_orchestrates_root_launchers() -> None:
    """run-all.sh 在仓库根启 run-backend / run-frontend 子脚本，带 trap 清理与 wait。"""
    path = repo_root() / "run-all.sh"
    text = read_script(path)
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    assert 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in text
    assert 'cd "$SCRIPT_DIR"' in text
    assert '"${SCRIPT_DIR}/run-backend.sh"' in text
    assert '"${SCRIPT_DIR}/run-frontend.sh"' in text
    assert "cleanup() {" in text
    assert "trap cleanup" in text
    assert text.rstrip().endswith("wait")


def test_backend_script_workflow_control_flow_regression_strict_bash_repo_root() -> (
    None
):
    """backend/scripts 工作流控制流回归：从 scripts/ 上溯两层到 monorepo 根再 pytest。"""
    rel = "backend/scripts/test_workflow_control_flow_regression.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert 'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"' in text, rel
    assert 'cd "$ROOT_DIR"' in text, rel
    assert "if [[ ! -d backend ]]; then" in text, rel
    assert "if [[ ! -f pytest.ini ]]; then" in text, rel
    assert "PYTHONPATH=backend pytest" in text, rel
    assert "backend/tests/test_workflow_control_flow_regression.py" in text, rel


def test_backend_script_tenant_security_regression_strict_bash_uo_backend_root() -> (
    None
):
    """租户安全回归：顶层 set -uo；从 backend/scripts 定位 backend 包根再批量 pytest。"""
    rel = "backend/scripts/test_tenant_security_regression.sh"
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    prefix = "\n".join(text.splitlines()[:8])
    assert "set -uo pipefail" in prefix, rel
    assert "set -euo pipefail" not in prefix, rel
    assert 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in text, rel
    assert 'BACKEND_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"' in text, rel
    assert 'cd "${BACKEND_ROOT}"' in text, rel
    assert "if [[ ! -f main.py ]]" in text, rel


@pytest.mark.parametrize("rel", _GITHUB_SMART_ROUTING_GATE_SCRIPTS)
def test_github_smart_routing_gate_scripts_strict_bash_env_and_trap(rel: str) -> None:
    """CI smart-routing 冒烟门：必需 env、临时文件与 trap；脚本内含 curl 探测。"""
    text = read_script(repo_root() / rel)
    assert text.startswith("#!/usr/bin/env bash\n"), rel
    assert "set -euo pipefail" in text
    assert ': "${BASE_URL:?}"' in text
    assert '"${ADMIN_KEY:?}"' in text
    assert "mktemp" in text
    assert "trap " in text
    assert "curl " in text
