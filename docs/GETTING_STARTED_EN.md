# perilla Detailed Guide (English)

> This document receives the detailed content from the repository `README_EN.md` and is intended for onboarding, troubleshooting, and release operations.

## Contents

- [1. Capability overview](#1-capability-overview)
- [2. Architecture and critical paths](#2-architecture-and-critical-paths)
- [3. Quick start (detailed)](#3-quick-start-detailed)
- [4. MCP integration and configuration](#4-mcp-integration-and-configuration)
- [5. Validation commands](#5-validation-commands)
- [6. Troubleshooting FAQ](#6-troubleshooting-faq)
- [7. Minimal production checklist](#7-minimal-production-checklist)
- [8. Further reading](#8-further-reading)

## 1. Capability overview

- Unified inference: `LLM`, `VLM`, `Embedding`, `ASR`, `Image Generation`
- Agent/Workflow orchestration with governance controls
- Knowledge/RAG, memory, audit, backup, and system settings
- Local-first model with a FastAPI gateway as the only control plane entry

## 2. Architecture and critical paths

- Gateway-centric flow: `UI -> FastAPI Gateway -> Runtime/Tool/Store`
- Agent flow: `Planner -> Skill/Tool -> Gateway -> Result`
- Workflow flow: `Control Plane -> Execution Kernel -> Queue/Lease -> Events`
- Image flow: `Image API -> Job Manager -> Runtime Queue -> Store/Files`

Deep architecture docs:

- `docs/architecture/ARCHITECTURE.md`
- `docs/architecture/AGENT_ARCHITECTURE.md`

## 3. Quick start (detailed)

### 3.1 Conda (recommended for dev)

```bash
conda create -n ai-inference-platform python=3.11 -y
cd backend
conda run -n ai-inference-platform pip install -r requirements.txt
cd ../frontend && npm install && cd ..
./run-all.sh
```

Defaults:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`

### 3.2 Docker (consistent runtime)

```bash
bash scripts/install.sh
# or make bootstrap
```

Operational commands:

```bash
scripts/status.sh
scripts/logs.sh
scripts/healthcheck.sh
scripts/doctor.sh
```

## 4. MCP integration and configuration

### 4.1 Backend key files

- `backend/api/mcp.py`
- `backend/core/mcp/protocol.py`
- `backend/core/mcp/client.py`
- `backend/core/mcp/http_client.py`
- `backend/core/mcp/server_manager.py`
- `backend/core/mcp/service.py`
- `backend/core/data/models/mcp_server.py`

### 4.2 Frontend key files

- `frontend/src/components/settings/SettingsMcpView.vue`
- `frontend/src/views/SettingsMcpView.vue`
- `frontend/src/services/api.ts`

### 4.3 Recommended setup flow

1. Create/edit MCP server config in `/settings/mcp`
2. Verify transport/base URL/auth fields
3. Save and validate visibility/callability in Agent views
4. Run MCP-focused tests (see next section)

## 5. Validation commands

### 5.1 Fast check

```bash
make pr-check-fast
```

### 5.2 Full check

```bash
make pr-check
```

### 5.3 EventBus-focused tests

```bash
PYTHONPATH=backend pytest -q \
  backend/tests/test_event_bus_smoke_summary_contract.py \
  backend/tests/test_event_bus_smoke_result_contract.py \
  backend/tests/test_event_bus_smoke_gh_trigger_inputs_audit_contract.py \
  backend/tests/test_event_bus_smoke_gh_inputs_snapshot_contract.py
```

### 5.4 MCP-focused tests

```bash
PYTHONPATH=backend pytest -q \
  backend/tests/test_mcp_protocol.py \
  backend/tests/test_mcp_adapter.py \
  backend/tests/test_mcp_http_client_lifecycle.py
```

### 5.5 Lint pins, merge gate, and preflight (CI-aligned)

- Install the same Ruff / Mypy versions as CI: `make install-lint-tools` (uses `backend/requirements/lint-tools.txt`).
- Run only the merge-gate pytest list: `make merge-gate-contract-tests`.
- Backend preflight without a live API (mirrors the main backend CI job order): `bash scripts/production-preflight.sh`.

## 6. Troubleshooting FAQ

### 6.1 401/403

- Verify `X-Api-Key`, `X-Tenant-Id`, CSRF token/cookie
- Validate RBAC and tenant policy in `.env`

### 6.2 Missing models

- Check `model.json` and runtime dependencies
- Inspect backend logs for provider initialization errors

### 6.3 MCP configured but unavailable

- Verify enablement and base URL reachability
- Run MCP-focused tests for protocol/lifecycle diagnostics

### 6.4 EventBus contract failures

- Validators now reject bool-as-int input (`True/False` is invalid for numeric fields)
- Distinguish type failures from semantic field mismatches

## 7. Minimal production checklist

- Before release: `make pr-check` passes
- At release: `DEBUG=false`, `SECURITY_GUARDRAILS_STRICT=true`
- After release: T+10/T+30 checks on MCP path, config refresh, EventBus validation logs
- Rollback strategy: high-risk feature commits first, then foundational/tooling changes

## 8. Further reading

- Deployment: `docs/DEPLOYMENT.md`
- Development: `docs/DEVELOPMENT_GUIDE.md`
- API: `docs/api/API_DOCUMENTATION.md`
- Local models: `docs/local_model/LOCAL_MODEL_DEPLOYMENT.md`
- Tutorials index: `tutorials/tutorial-index.md`
