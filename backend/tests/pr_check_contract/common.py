from __future__ import annotations

import re
from pathlib import Path

# 须与 scripts/merge-gate-contract-tests.sh 内 pytest 列表顺序完全一致（双向契约见 entrypoints 测试）。
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
    "test_pr_check_contract_entrypoints.py",
    "test_pr_check_contract_github_workflows.py",
    "test_pr_check_contract_makefile.py",
    "test_pr_check_contract_shell_scripts.py",
    "test_root_package_scripts_contract.py",
    "test_npm_scripts_roadmap_hint_contract.py",
)


def read_script(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# merge-gate-contract-tests.sh：仅匹配「两空格 + backend/tests/test_*.py + 行尾反斜杠」的 pytest 参数行，忽略注释与文案。
_MERGE_GATE_PYTEST_ARG_LINE = re.compile(r"^\s+(backend/tests/test_\w+\.py)\s*\\\s*$")


def merge_gate_pytest_relative_paths(script: str) -> list[str]:
    """解析合并门禁脚本中的 pytest 路径列表（顺序与脚本一致）。"""
    out: list[str] = []
    for line in script.splitlines():
        m = _MERGE_GATE_PYTEST_ARG_LINE.match(line)
        if m:
            out.append(m.group(1))
    return out


def merge_gate_pytest_modules_from_script(script: str) -> list[str]:
    """同上，返回各模块文件名（test_*.py）。"""
    return [Path(p).name for p in merge_gate_pytest_relative_paths(script)]


_JOB_HEAD = re.compile(r"^ {2}([A-Za-z0-9_-]+):\s*$")
_JOB_BODY_LINE = re.compile(r"^ {4}\S")


def _gha_jobs_scan_should_stop(line: str) -> bool:
    """jobs: 块结束后通常出现顶层键（如 permissions / defaults），用于停止扫描。"""
    return bool(
        line
        and not line.startswith(("#", " ", "\t"))
        and line.strip().endswith(":")
        and line[0].isalpha()
    )


def _gha_job_body_refresh_flags(
    line: str, has_timeout: bool, has_runson: bool
) -> tuple[bool, bool]:
    if not _JOB_BODY_LINE.match(line):
        return has_timeout, has_runson
    if "timeout-minutes:" in line:
        has_timeout = True
    if "runs-on:" in line:
        has_runson = True
    return has_timeout, has_runson


def workflow_job_names_with_runs_on_but_no_timeout(content: str) -> list[str]:
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
        if _gha_jobs_scan_should_stop(line):
            break
        m_job = _JOB_HEAD.match(line)
        if m_job:
            flush()
            job_name = m_job.group(1)
            continue
        if job_name is None:
            continue
        has_timeout, has_runson = _gha_job_body_refresh_flags(
            line, has_timeout, has_runson
        )
    flush()
    return bad
