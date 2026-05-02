#!/usr/bin/env bash
# Helm / Makefile / package.json 合并门禁契约测试（单一列表：Makefile 与 CI 共用）。
# 用法：bash scripts/merge-gate-contract-tests.sh [pytest 额外参数，如 -q]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH=backend
exec pytest \
  backend/tests/test_repo_paths_layout_contract.py \
  backend/tests/test_helm_notes_env_mapping_contract.py \
  backend/tests/test_helm_deployment_env_contract.py \
  backend/tests/test_helm_deployment_duplicate_env_names_contract.py \
  backend/tests/test_helm_values_env_duplicate_keys_contract.py \
  backend/tests/test_helm_values_critical_keys_contract.py \
  backend/tests/test_helm_values_probes_metrics_contract.py \
  backend/tests/test_helm_values_service_port_alignment_contract.py \
  backend/tests/test_deploy_k8s_example_alignment_contract.py \
  backend/tests/test_deploy_k8s_grace_budget_contract.py \
  backend/tests/test_deploy_secret_env_rate_limit_trust_contract.py \
  backend/tests/test_audit_log_events_path_coverage.py \
  backend/tests/test_deploy_ingress_streaming_hints_contract.py \
  backend/tests/test_runtime_health_paths_contract.py \
  backend/tests/test_docker_compose_production_hints_contract.py \
  backend/tests/test_docker_backend_image_contract.py \
  backend/tests/test_backend_dockerfile_python_main_contract.py \
  backend/tests/test_helm_values_security_uid_alignment_contract.py \
  backend/tests/test_helm_chart_yaml_contract.py \
  backend/tests/test_pr_check_scripts_contract.py \
  backend/tests/test_root_package_scripts_contract.py \
  "$@"
