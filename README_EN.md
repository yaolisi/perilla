# perilla — 5-Minute Quick Start

**Local-first, gateway-centric**: the Vue UI is a console only, and all model/tool traffic goes through the FastAPI gateway.

[中文 README](README.md)

---

## Contents (reader-tiered)

- [1) 5-minute startup](#1-5-minute-startup)
- [2) Beginner path (learn-use-debug)](#2-beginner-path-learn-use-debug)
- [3) Developer path (build-test-release)](#3-developer-path-build-test-release)
- [4) Ops path (security-release-incident)](#4-ops-path-security-release-incident)
- [5) Detailed docs (moved to docs/)](#5-detailed-docs-moved-to-docs)
- [6) Command quick reference](#6-command-quick-reference)

---

## 1) 5-minute startup

### Requirements

- Python 3.11+
- Node.js 18+
- Conda (recommended)

### Start with Conda

```bash
conda create -n ai-inference-platform python=3.11 -y
cd backend
conda run -n ai-inference-platform pip install -r requirements.txt
cd ../frontend && npm install && cd ..
./run-all.sh
```

Default endpoints:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`

### Health checks

```bash
curl -s http://127.0.0.1:8000/api/health | jq .
curl -s http://127.0.0.1:8000/api/health/ready | jq .
```

---

## 2) Beginner path (learn-use-debug)

1. 10-minute start: `tutorials/tutorial-quickstart.md`
2. Hands-on walkthrough: `tutorials/tutorial-beginner-playbook.md`
3. Debug handbook: `tutorials/tutorial-debug-playbook.md`
4. Full tutorial index: `tutorials/tutorial-index.md`

Suggested first UI path:

- `/models` -> `/chat` -> `/images` -> `/agents` -> `/workflow`

---

## 3) Developer path (build-test-release)

### Core docs

- Development guide: `docs/DEVELOPMENT_GUIDE.md`
- Architecture: `docs/architecture/ARCHITECTURE.md`
- Agent architecture: `docs/architecture/AGENT_ARCHITECTURE.md`

### MCP anchors

- Chinese detailed MCP section: [`docs/GETTING_STARTED_ZH.md#4-mcp-集成与配置`](docs/GETTING_STARTED_ZH.md#4-mcp-%E9%9B%86%E6%88%90%E4%B8%8E%E9%85%8D%E7%BD%AE)
- English detailed MCP section: [`docs/GETTING_STARTED_EN.md#4-mcp-integration-and-configuration`](docs/GETTING_STARTED_EN.md#4-mcp-integration-and-configuration)

---

## 4) Ops path (security-release-incident)

- Deployment: `docs/DEPLOYMENT.md`
- Security baseline: `tutorials/tutorial-security-baseline.md`
- Release checklist: `tutorials/tutorial-ops-checklist.md`
- Incident runbook: `tutorials/tutorial-incident-runbook.md`

Production defaults to enforce:

- `DEBUG=false`
- `SECURITY_GUARDRAILS_STRICT=true`

---

## 5) Detailed docs (moved to docs/)

To keep this README short, detailed sections are moved to:

- Chinese deep guide: `docs/GETTING_STARTED_ZH.md`
- English deep guide: `docs/GETTING_STARTED_EN.md`

Useful anchors:

- Validation commands: [`#5-validation-commands`](docs/GETTING_STARTED_EN.md#5-validation-commands)
- Troubleshooting FAQ: [`#6-troubleshooting-faq`](docs/GETTING_STARTED_EN.md#6-troubleshooting-faq)
- Production checklist: [`#7-minimal-production-checklist`](docs/GETTING_STARTED_EN.md#7-minimal-production-checklist)

### Multi-tenant HTTP (summary)

When **`TENANT_ENFORCEMENT_ENABLED`** / **`TENANT_API_KEY_BINDING_ENABLED`** are on, requests under these URL prefixes must include an explicit tenant header (default name **`X-Tenant-Id`**, configurable via **`TENANT_HEADER_NAME`**):

- `/api/v1/workflows`, `/api/v1/audit`, `/api/system`
- `/v1/chat`, `/api/sessions`, `/api/memory`
- `/api/knowledge-bases`, `/api/agent-sessions`, `/v1/vlm`

The canonical list is **`backend/middleware/tenant_paths.py`** (`is_tenant_enforcement_protected_path`). Persistence layers scope Workflow, sessions, knowledge bases, memory, governance audit, and related data by **tenant_id**; control-plane resolution follows middleware-injected tenant id (see **`backend/core/utils/tenant_request.py`**). Full narrative: **`tutorials/tutorial.md`** (multi-tenancy section).

### Naming and migration boundaries (folder vs Redis)

- **Checkout folder vs package name**: Your working copy directory may still be named `openvitamin_enhanced_docker` from history; the root `package.json` `name` is `perilla-enhanced-docker`. Runtime branding follows settings/UI (`settings.app_name`, etc.). **Renaming the folder is optional**; if you do, update scripts, CI, and docs that hard-code paths.

- **Redis keys vs Pub/Sub channels**: When startup migration is enabled (`redis_legacy_openvitamin_prefix_migrate_on_startup` in settings), only Redis **keys** are scanned/renamed from legacy `openvitamin:*` to the configured prefixes (inference cache, KB snapshot, etc.). **Channel names are not keys** and are not migrated; the event bus uses the configured `event_bus_channel_prefix` for subscribe/publish going forward.

- **Prometheus**: If `metrics_legacy_openvitamin_names_enabled` is true, the process registers both `perilla_*` and legacy `openvitamin_*` metric names in parallel for dashboard transition; set false to export only `perilla_*`.

---

## 6) Command quick reference

```bash
make pr-check-fast
make pr-check
scripts/status.sh
scripts/logs.sh
scripts/healthcheck.sh
```

EventBus-focused:

```bash
PYTHONPATH=backend pytest -q \
  backend/tests/test_event_bus_smoke_summary_contract.py \
  backend/tests/test_event_bus_smoke_result_contract.py
```

---

## Contact

- WeChat: fengzhizi715, virus_gene
- Email: fengzhizi715@126.com, yaolisi@hotmail.com

---

## Contributing and license

- Contributing: `CONTRIBUTING.md`
- Planned license: Apache License 2.0
