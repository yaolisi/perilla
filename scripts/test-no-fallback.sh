#!/usr/bin/env bash
set -euo pipefail

# Allow passing extra pytest args, e.g.:
#   bash scripts/test-no-fallback.sh -k memory -x
#   make test-no-fallback TEST_ARGS="-k memory -x"
PYTHONPATH=backend pytest \
  backend/tests/test_api_error_no_fallback_smoke.py \
  backend/tests/test_memory_api_integration.py \
  backend/tests/test_sessions_api_integration.py \
  backend/tests/test_agent_sessions_api_integration.py \
  backend/tests/test_agents_api_kernel_opts_e2e.py \
  backend/tests/test_workflow_approval_api_integration.py \
  backend/tests/test_knowledge_images_api_integration.py \
  -m no_fallback -q "$@"
