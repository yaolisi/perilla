from __future__ import annotations

import json
import re

import pytest

from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo


def test_root_package_json_includes_roadmap_acceptance_scripts() -> None:
    root = repo_root()
    pkg_path = root / "package.json"
    payload = json.loads(pkg_path.read_text(encoding="utf-8"))
    scripts = payload.get("scripts", {})

    assert scripts.get("roadmap-acceptance-unit") == "make roadmap-acceptance-unit"
    assert scripts.get("roadmap-acceptance-smoke") == "make roadmap-acceptance-smoke"
    assert scripts.get("roadmap-acceptance-all") == "make roadmap-acceptance-all"
    assert scripts.get("roadmap-acceptance-run-validated") == "bash scripts/acceptance/roadmap_run_validated.sh"
    assert scripts.get("roadmap-acceptance-validate-output") == "bash scripts/acceptance/roadmap_validate_output.sh"
    assert scripts.get("roadmap-release-gate") == "bash scripts/acceptance/roadmap_release_gate.sh"
    assert scripts.get("test-frontend-unit") == (
        "npm run check-nvmrc-align && npm --prefix frontend run test:unit"
    )
    assert scripts.get("test-frontend-unit-coverage") == (
        "npm run check-nvmrc-align && npm --prefix frontend run test:unit:coverage"
    )
    assert scripts.get("helm-chart-check") == "make helm-chart-check"
    assert scripts.get("helm-deploy-contract-check") == "make helm-deploy-contract-check"
    assert scripts.get("merge-gate-contract-tests") == "bash scripts/merge-gate-contract-tests.sh"
    assert scripts.get("ci") == "bash scripts/pr-check.sh"
    assert scripts.get("ci-fast") == "bash scripts/pr-check-fast.sh"
    assert scripts.get("pr-check") == "bash scripts/pr-check.sh"
    assert scripts.get("pr-check-fast") == "bash scripts/pr-check-fast.sh"
    assert scripts.get("quick-check") == "bash scripts/quick-check.sh"
    assert scripts.get("lint") == "bash scripts/lint-backend.sh"
    assert scripts.get("lint-backend") == "bash scripts/lint-backend.sh"
    assert scripts.get("test-no-fallback") == "bash scripts/test-no-fallback.sh"
    assert scripts.get("check-nvmrc-align") == "bash scripts/check-nvmrc-align.sh"
    assert scripts.get("i18n-scan-frontend") == "bash scripts/check-frontend-i18n-hardcoded.sh"
    assert scripts.get("doctor") == "bash scripts/doctor.sh"
    assert scripts.get("healthcheck") == "make healthcheck"
    assert scripts.get("security-guardrails") == "make security-guardrails"
    assert scripts.get("security-guardrails-ci") == "make security-guardrails-ci"
    assert scripts.get("help") == "make help"
    assert scripts.get("npm-scripts") == "bash scripts/npm-scripts.sh"
    assert scripts.get("npm-scripts-json") == "bash scripts/npm-scripts.sh --json"
    assert scripts.get("build-frontend") == (
        "npm run check-nvmrc-align && npm --prefix frontend run build"
    )
    assert scripts.get("local-all") == "bash run-all.sh"
    assert scripts.get("local-backend") == "bash run-backend.sh"
    assert scripts.get("local-frontend") == "bash run-frontend.sh"


def test_root_nvmrc_major_matches_package_engines_node() -> None:
    """仓库根 .nvmrc 主版本须与 package.json engines.node 一致，防 CI / 本地 Node 漂移。"""
    root = repo_root()
    nvm_raw = (root / ".nvmrc").read_text(encoding="utf-8").strip().lstrip("v")
    nvm_major = int(nvm_raw.split(".")[0])
    pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
    node_eng = str((pkg.get("engines") or {}).get("node", ""))
    m = re.search(r"\d+", node_eng)
    assert m, f"root package.json engines.node missing or unparsable: {node_eng!r}"
    eng_major = int(m.group(0))
    assert eng_major == nvm_major, (
        f"root .nvmrc major {nvm_major} != package.json engines.node major {eng_major} ({node_eng})"
    )


def test_frontend_nvmrc_major_matches_package_engines_node() -> None:
    """frontend/package.json engines.node 主版本须与仓库 .nvmrc 一致（与 CI setup-node 对齐）。"""
    root = repo_root()
    nvm_raw = (root / ".nvmrc").read_text(encoding="utf-8").strip().lstrip("v")
    nvm_major = int(nvm_raw.split(".")[0])
    pkg = json.loads((root / "frontend" / "package.json").read_text(encoding="utf-8"))
    node_eng = str((pkg.get("engines") or {}).get("node", ""))
    m = re.search(r"\d+", node_eng)
    assert m, f"frontend package.json engines.node missing or unparsable: {node_eng!r}"
    eng_major = int(m.group(0))
    assert eng_major == nvm_major, (
        f".nvmrc major {nvm_major} != frontend engines.node major {eng_major} ({node_eng})"
    )


def test_makefile_quick_check_invokes_same_entry_as_npm() -> None:
    """make quick-check 与 npm run quick-check 须共用 scripts/quick-check.sh。"""
    makefile = (repo_root() / "Makefile").read_text(encoding="utf-8")
    assert "quick-check:" in makefile
    block = makefile.split("quick-check:", 1)[1].split("\n\n", 1)[0]
    assert "scripts/quick-check.sh" in block


def test_makefile_lint_targets_match_npm_lint_scripts() -> None:
    """make lint / lint-backend 与 npm run lint* 须共用 scripts/lint-backend.sh。"""
    makefile = (repo_root() / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^lint:\s+lint-backend\s*$", makefile, re.MULTILINE)
    marker = "\nlint-backend:\n"
    idx = makefile.find(marker)
    assert idx != -1, "expected standalone lint-backend: target in Makefile"
    block = makefile[idx + len(marker) :].split("\n\n", 1)[0]
    assert "scripts/lint-backend.sh" in block


def test_makefile_test_no_fallback_matches_npm_script() -> None:
    """make test-no-fallback 须调用 scripts/test-no-fallback.sh，并保留 TEST_ARGS 透传（与 help / CI 文档一致）。"""
    makefile = (repo_root() / "Makefile").read_text(encoding="utf-8")
    marker = "\ntest-no-fallback:\n"
    idx = makefile.find(marker)
    assert idx != -1, "expected test-no-fallback: target in Makefile"
    block = makefile[idx + len(marker) :].split("\n\n", 1)[0]
    assert "scripts/test-no-fallback.sh" in block
    assert "TEST_ARGS" in block


def test_makefile_check_nvmrc_and_i18n_scan_match_npm_scripts() -> None:
    """make check-nvmrc-align / i18n-hardcoded-scan 与 npm 脚本须共用同一 bash 入口。"""
    makefile = (repo_root() / "Makefile").read_text(encoding="utf-8")

    m = "\ncheck-nvmrc-align:\n"
    idx = makefile.find(m)
    assert idx != -1, "expected check-nvmrc-align: target in Makefile"
    block = makefile[idx + len(m) :].split("\n\n", 1)[0]
    assert "scripts/check-nvmrc-align.sh" in block

    m2 = "\ni18n-hardcoded-scan:\n"
    idx2 = makefile.find(m2)
    assert idx2 != -1, "expected i18n-hardcoded-scan: target in Makefile"
    block2 = makefile[idx2 + len(m2) :].split("\n\n", 1)[0]
    assert "scripts/check-frontend-i18n-hardcoded.sh" in block2


def test_makefile_doctor_matches_npm_doctor_script() -> None:
    makefile = (repo_root() / "Makefile").read_text(encoding="utf-8")
    marker = "\ndoctor:\n"
    idx = makefile.find(marker)
    assert idx != -1, "expected doctor: target in Makefile"
    block = makefile[idx + len(marker) :].split("\n\n", 1)[0]
    assert "scripts/doctor.sh" in block


def test_makefile_help_target_aliases_npm_run_help() -> None:
    """npm run help -> make help；Makefile 须保留 help: 目标。"""
    makefile = (repo_root() / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^help:\s*$", makefile, re.MULTILINE)
    assert "\nhelp:\n\t@echo" in makefile


def test_makefile_npm_scripts_helpers_match_package_json() -> None:
    makefile = (repo_root() / "Makefile").read_text(encoding="utf-8")
    m = "\nnpm-scripts:\n"
    idx = makefile.find(m)
    assert idx != -1
    block = makefile[idx + len(m) :].split("\n\n", 1)[0]
    assert "scripts/npm-scripts.sh" in block
    m2 = "\nnpm-scripts-json:\n"
    idx2 = makefile.find(m2)
    assert idx2 != -1
    block2 = makefile[idx2 + len(m2) :].split("\n\n", 1)[0]
    assert "npm-scripts.sh" in block2 and "--json" in block2


def test_makefile_helm_chart_check_and_deploy_contract_chain() -> None:
    """helm-chart-check 与 helm-deploy-contract-check 配方须与 npm run helm-* / CI 一致。"""
    makefile = (repo_root() / "Makefile").read_text(encoding="utf-8")

    m = "\nhelm-chart-check:\n"
    idx = makefile.find(m)
    assert idx != -1
    block = makefile[idx + len(m) :].split("\n\n", 1)[0]
    assert "scripts/helm-chart-check.sh" in block

    assert re.search(
        r"^helm-deploy-contract-check:\s*helm-chart-check\s*$",
        makefile,
        re.MULTILINE,
    )
    m2 = "\nhelm-deploy-contract-check: helm-chart-check\n"
    idx2 = makefile.find(m2)
    assert idx2 != -1
    block2 = makefile[idx2 + len(m2) :].split("\n\n", 1)[0]
    assert "merge-gate-contract-tests.sh" in block2 and "-q" in block2


def test_makefile_build_frontend_matches_npm_build_frontend() -> None:
    """make build-frontend 与 npm run build-frontend：均先 nvmrc 对齐，再在 frontend 下 build。"""
    makefile = (repo_root() / "Makefile").read_text(encoding="utf-8")
    assert re.search(
        r"^build-frontend:\s*check-nvmrc-align\s*$",
        makefile,
        re.MULTILINE,
    )
    marker = "\nbuild-frontend: check-nvmrc-align\n"
    idx = makefile.find(marker)
    assert idx != -1
    block = makefile[idx + len(marker) :].split("\n\n", 1)[0]
    assert "frontend" in block and "npm run build" in block


def test_makefile_local_dev_targets_match_npm_and_runner_scripts_exist() -> None:
    """make local-* 与 npm run local-* 共用仓库根 run-*.sh；脚本文件须存在以防入口断裂。"""
    root = repo_root()
    for name in ("run-all.sh", "run-backend.sh", "run-frontend.sh"):
        assert (root / name).is_file(), f"missing repo root {name}"

    makefile = (repo_root() / "Makefile").read_text(encoding="utf-8")
    pairs = (
        ("local-all", "run-all.sh"),
        ("local-backend", "run-backend.sh"),
        ("local-frontend", "run-frontend.sh"),
    )
    for target, sh in pairs:
        marker = f"\n{target}:\n"
        idx = makefile.find(marker)
        assert idx != -1, f"missing Makefile target {target}:"
        block = makefile[idx + len(marker) :].split("\n\n", 1)[0]
        assert sh in block, f"{target} should invoke {sh}"


def test_makefile_healthcheck_and_security_guardrails_invoke_repo_scripts() -> None:
    """运维/生产门禁入口须指向真实脚本，避免 make 目标漂移或文件被删。"""
    root = repo_root()
    assert (root / "scripts" / "healthcheck.sh").is_file()
    assert (root / "scripts" / "check-security-guardrails.sh").is_file()
    assert (root / "scripts" / "check-security-guardrails-ci.sh").is_file()

    makefile = (root / "Makefile").read_text(encoding="utf-8")
    m = "\nhealthcheck:\n"
    idx = makefile.find(m)
    assert idx != -1
    block = makefile[idx + len(m) :].split("\n\n", 1)[0]
    assert "scripts/healthcheck.sh" in block

    m2 = "\nsecurity-guardrails:\n"
    idx2 = makefile.find(m2)
    assert idx2 != -1
    block2 = makefile[idx2 + len(m2) :].split("\n\n", 1)[0]
    assert "scripts/check-security-guardrails.sh" in block2

    m3 = "\nsecurity-guardrails-ci:\n"
    idx3 = makefile.find(m3)
    assert idx3 != -1
    block3 = makefile[idx3 + len(m3) :].split("\n\n", 1)[0]
    assert "scripts/check-security-guardrails-ci.sh" in block3
