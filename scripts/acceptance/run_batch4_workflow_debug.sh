#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/backend"
export PYTHONPATH=.
echo "== Batch 4: workflow debug endpoint (manual) =="
echo "With server running and valid workflow_id / execution_id / auth:"
echo "  curl -s -H \"X-User-Id: <owner>\" \\"
echo "    \"http://127.0.0.1:8000/api/v1/workflows/<wf_id>/executions/<ex_id>/debug?event_limit=20\""
echo ""
echo "Note: run curl against a running backend (conda env with FastAPI deps)."
