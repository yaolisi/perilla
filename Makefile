.PHONY: help npm-scripts npm-scripts-json bootstrap bootstrap-prod env-init local-all local-backend local-frontend install install-gpu install-prod install-prod-soft up up-gpu up-prod up-monitoring down down-gpu down-prod down-monitoring status status-monitoring logs healthcheck monitoring-smoke monitoring-e2e monitoring-e2e-clean monitoring-all ops-drill-guide doctor security-guardrails lint lint-backend helm-chart-check helm-deploy-contract-check compose-config-check monitoring-config-check k8s-manifest-check dockerfile-hadolint-check merge-gate-contract-tests check-nvmrc-align test-frontend-unit test-frontend-unit-coverage build-frontend pr-check pr-check-fast ci ci-fast quick-check production-preflight release-preflight dependency-policy dependency-scan test-no-fallback test-workflow-control-flow test-tenant-isolation roadmap-acceptance-unit roadmap-acceptance-smoke roadmap-acceptance-all roadmap-acceptance-validate-schema-version roadmap-acceptance-validate-output roadmap-acceptance-run-validated roadmap-release-gate smart-routing-smoke smart-routing-all-checks smart-routing-load-test smart-routing-experiment smart-routing-param-scan cb-doctor cb-benchmark cb-grid cb-recommend cb-snapshot cb-rollback cb-tier cb-gate cb-triage cb-tests cb-fast cb-latest-report cb-pipeline cb-all cb-release-check event-bus-smoke event-bus-smoke-pytest event-bus-smoke-unit event-bus-smoke-contract-guard event-bus-smoke-contract event-bus-smoke-summary-contract event-bus-smoke-gh-strict event-bus-smoke-gh-compatible event-bus-smoke-gh-watch-latest event-bus-smoke-gh-strict-watch event-bus-smoke-gh-compatible-watch event-bus-smoke-print-gh-inputs event-bus-smoke-print-gh-inputs-json event-bus-smoke-write-gh-inputs-json-file event-bus-smoke-validate-gh-inputs-snapshot event-bus-smoke-validate-gh-trigger-inputs-audit event-bus-smoke-validate-schema-version event-bus-smoke-validate-result-file event-bus-smoke-validate-contract-input event-bus-smoke-validate-json-output event-bus-smoke-validate-file-suffix event-bus-smoke-preflight event-bus-smoke-fast event-bus-smoke-run-validated event-bus-smoke-all drill-alerting reset

CB_BASE_URL ?= http://127.0.0.1:8000
CB_MODEL ?= ollama:deepseek-r1:32b
CB_REQUESTS ?= 120
CB_TIMEOUT ?= 120
CB_CONCURRENCY ?= 10
CB_BATCH_WAIT_MS ?= 12
CB_BATCH_MAX_SIZE ?= 8
CB_CONCURRENCY_LIST ?= 10,20,30
CB_WAIT_MS_LIST ?= 4,8,12,16
CB_MAX_SIZE_LIST ?= 4,8,12
CB_TOP_K ?= 5
CB_MIN_THROUGHPUT_RATIO ?= 1.5
CB_MAX_FIRST_RESPONSE_RATIO ?= 0.3333
CB_MIN_SUCCESS_RATE ?= 0.99
CB_LAST_N ?= 10
EVENT_BUS_BASE_URL ?= http://127.0.0.1:8000
EVENT_BUS_SMOKE_EVENT_TYPE ?= agent.status.changed
EVENT_BUS_SMOKE_LIMIT ?= 20
EVENT_BUS_SMOKE_SCHEMA_VERSION ?= 1
EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION ?= 1
EVENT_BUS_SMOKE_SUMMARY_SCHEMA_MODE ?= strict
EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE ?= strict
EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS ?= 600000
EVENT_BUS_SMOKE_RESULT_FILE ?= event-bus-smoke-result.json
EVENT_BUS_SMOKE_FILE_SUFFIX ?=
EVENT_BUS_SMOKE_GH_WORKFLOW ?= event-bus-dlq-smoke.yml
EVENT_BUS_SMOKE_GH_INPUTS_JSON_FILE ?= event-bus-smoke-gh-inputs.json
EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE ?=
EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_VERSION ?= 1
EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_MODE ?= strict
EVENT_BUS_SMOKE_GH_TRIGGER_MODE ?=
EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_WORKFLOW ?=
EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_BASE_URL ?=
EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_EVENT_TYPE ?=
EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_LIMIT ?=
EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_STALE_THRESHOLD_MS ?=
EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_SUMMARY_SCHEMA_VERSION ?=
EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_RESULT_SCHEMA_VERSION ?=
EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_FILE_SUFFIX ?=
EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION ?=
EVENT_BUS_SMOKE_GH_TRIGGER_MAX_DURATION_MS ?=
EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS ?=
EVENT_BUS_SMOKE_CONTRACT_GUARD_LOG_FILE ?= event-bus-smoke-contract-guard.log
EVENT_BUS_SMOKE_EFFECTIVE_RESULT_FILE = $(or $(EVENT_BUS_SMOKE_JSON_OUTPUT),$(if $(EVENT_BUS_SMOKE_FILE_SUFFIX),event-bus-smoke-result-$(EVENT_BUS_SMOKE_FILE_SUFFIX).json,$(EVENT_BUS_SMOKE_RESULT_FILE)))
ALERT_DRILL_BACKEND_URL ?= http://127.0.0.1:8000
ALERT_DRILL_ALERTMANAGER_URL ?= http://127.0.0.1:9093
ALERT_DRILL_ROUNDS ?= 30
ALERT_DRILL_CONCURRENCY ?= 4
ALERT_DRILL_SCRAPE_WAIT_SECONDS ?= 45
ALERT_DRILL_RECOVERY_TIMEOUT_SECONDS ?= 900
ALERT_DRILL_POLL_INTERVAL_SECONDS ?= 15
ALERT_DRILL_ALERTS ?= perillaInferenceErrorRateHigh,perillaAgentFailureRateHigh,perillaInferenceP95TooHigh
MONITORING_PROMETHEUS_URL ?= http://127.0.0.1:9090
MONITORING_ALERTMANAGER_URL ?= http://127.0.0.1:9093
MONITORING_GRAFANA_URL ?= http://127.0.0.1:3000
ROADMAP_BASE_URL ?= http://127.0.0.1:8000
ROADMAP_RUN_LIVE_SMOKE ?= 0
# 设为 1 时，`make pr-check` / `pr-check-fast` 跳过 roadmap-acceptance-unit（默认运行以更贴近生产合并门禁）。
SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK ?= 0
ROADMAP_OUTPUT_JSON ?=
ROADMAP_OUTPUT_SCHEMA_VERSION ?= 1
ROADMAP_GATE_LOG_PREFIX ?= [roadmap-gate]

.PHONY: event-bus-smoke-validate-summary-schema-mode
.PHONY: event-bus-smoke-validate-payload-sha256-mode
.PHONY: event-bus-smoke-validate-summary-schema-version
.PHONY: event-bus-smoke-validate-gh-trigger-inputs-audit-schema-version
.PHONY: event-bus-smoke-validate-gh-trigger-inputs-audit-schema-mode
.PHONY: event-bus-smoke-validate-gh-trigger-expected-conclusion
.PHONY: event-bus-smoke-validate-gh-inputs
.PHONY: event-bus-smoke-contract-guard
.PHONY: event-bus-smoke-contract-guard-preflight
.PHONY: event-bus-smoke-contract-guard-mapping
.PHONY: event-bus-smoke-contract-guard-payload
.PHONY: event-bus-smoke-contract-guard-validator
.PHONY: event-bus-smoke-contract-guard-workflow
.PHONY: event-bus-smoke-contract-guard-status-json
.PHONY: i18n-hardcoded-scan

help:
	@echo "perilla Docker helper targets:"
	@echo "Quick ref (CI parity): make quick-check | make release-preflight | make ci-fast | make npm-scripts"
	@echo "  npm run help       - Same as make help (requires make in PATH)"
	@echo "  make npm-scripts   - List root package.json scripts (scripts/npm-scripts.sh; any cwd)"
	@echo "  npm run npm-scripts"
	@echo "                   - Same listing (run from repo root; or bash scripts/npm-scripts.sh from any cwd)"
	@echo "  bash scripts/npm-scripts.sh --json"
	@echo "                   - Same scripts as JSON (npm pkg get scripts)"
	@echo "  bash scripts/npm-scripts.sh --help"
	@echo "                   - Options for this helper"
	@echo "  make npm-scripts-json"
	@echo "                   - Same as scripts/npm-scripts.sh --json"
	@echo "  npm run npm-scripts-json"
	@echo "                   - Same from repo root"
	@echo "  make bootstrap     - First-time setup (env-init + doctor + install)"
	@echo "  make bootstrap-prod"
	@echo "                   - First-time prod setup (env-init + strict doctor + install-prod)"
	@echo "  make env-init      - Initialize .env from .env.example"
	@echo "  bash run-all.sh    - Local dev (backend+frontend); cwd-independent via script paths"
	@echo "  bash run-backend.sh / bash run-frontend.sh"
	@echo "                   - Split backend (conda/python) vs frontend (npm dev)"
	@echo "  npm run local-all / local-backend / local-frontend"
	@echo "                   - Same (run from repo root where package.json lives)"
	@echo "  make local-all / local-backend / local-frontend"
	@echo "                   - Same as bash run-all.sh etc. (from repo root)"
	@echo "  make install       - Build and start base profile"
	@echo "  make install-gpu   - Build and start GPU profile"
	@echo "  make install-prod  - Build and start production profile"
	@echo "  make install-prod-soft"
	@echo "                   - Build/start prod profile with relaxed doctor warnings"
	@echo "  make up            - Start base profile"
	@echo "  make up-gpu        - Start GPU profile"
	@echo "  make up-prod       - Start production profile"
	@echo "  make up-monitoring - Start monitoring stack (Prometheus/Grafana/Alertmanager)"
	@echo "  make down          - Stop base profile"
	@echo "  make down-gpu      - Stop GPU profile"
	@echo "  make down-prod     - Stop production profile"
	@echo "  make down-monitoring"
	@echo "                   - Stop monitoring stack"
	@echo "  make status        - Show status in all profile views"
	@echo "  make status-monitoring"
	@echo "                   - Show monitoring stack status"
	@echo "  make monitoring-smoke"
	@echo "                   - Run monitoring API smoke checks"
	@echo "  make monitoring-e2e"
	@echo "                   - Start monitoring and run full alerting E2E drill"
	@echo "  make monitoring-e2e-clean"
	@echo "                   - Run monitoring-e2e and always stop monitoring stack"
	@echo "  make monitoring-all"
	@echo "                   - Print runbook and run full monitoring E2E clean flow"
	@echo "  make ops-drill-guide"
	@echo "                   - Print local/CI monitoring drill runbook"
	@echo "  make logs          - Tail logs"
	@echo "  make healthcheck   - Run health checks"
	@echo "  npm run healthcheck"
	@echo "                   - Same as make healthcheck"
	@echo "  make doctor        - Run environment diagnostics (incl. check-nvmrc-align)"
	@echo "  npm run doctor     - Same (DOCTOR_STRICT_WARNINGS=1 npm run doctor for strict)"
	@echo "  make security-guardrails"
	@echo "                   - Enforce production security config gate (needs conda/backend deps or PERILLA_PYTHON)"
	@echo "  npm run security-guardrails"
	@echo "                   - Same as make security-guardrails"
	@echo "  make lint-backend"
	@echo "                   - Ruff (E9) + Mypy sample (CI backend-static-analysis; step 1 of pr-check)"
	@echo "  make lint"
	@echo "                   - Alias for make lint-backend"
	@echo "  make helm-chart-check"
	@echo "                   - helm lint + helm template（deploy/helm/perilla-backend；无本地 helm 时可 Docker；均无则跳过）"
	@echo "  make compose-config-check"
	@echo "                   - docker compose config（base、prod、可选 monitoring 叠加；无 compose/daemon 则跳过）"
	@echo "  make monitoring-config-check"
	@echo "                   - promtool / amtool 校验 Prometheus 与 Alertmanager 配置（无 Docker 且无本地工具则跳过）"
	@echo "  make k8s-manifest-check"
	@echo "                   - kubeconform 校验 deploy/k8s 示例清单（无 Docker 且无 kubeconform 则跳过）"
	@echo "  make dockerfile-hadolint-check"
	@echo "                   - hadolint 校验 docker/*.Dockerfile（无 Docker 且无 hadolint 则跳过）"
	@echo "  make helm-deploy-contract-check"
	@echo "                   - helm-chart-check + scripts/merge-gate-contract-tests.sh（pr-check / CI backend-static-analysis）"
	@echo "  make merge-gate-contract-tests"
	@echo "                   - 仅运行合并门禁 pytest（不跑 helm lint；与 npm run merge-gate-contract-tests 一致）"
	@echo "  npm run lint-backend"
	@echo "                   - Same as scripts/lint-backend.sh (pip ruff/mypy on PATH)"
	@echo "  npm run lint"
	@echo "                   - Alias for npm run lint-backend"
	@echo "  make test-no-fallback"
	@echo "                   - API no-fallback tests + production readiness baseline (CI backend-static-analysis; step 2 of pr-check)"
	@echo "                   - scripts/test-no-fallback.sh cd to repo root (invoke by path from any cwd)"
	@echo "  make test-no-fallback TEST_ARGS=\"-k memory -x\""
	@echo "                   - Same suite with extra pytest args"
	@echo "                   - TEST_ARGS applies to make pr-check|ci|pr-check-fast|ci-fast (no-fallback step)"
	@echo "  npm run test-no-fallback -- -k memory -x"
	@echo "                   - Same suite without make (pytest args after --)"
	@echo "  make check-nvmrc-align"
	@echo "                   - cmp .nvmrc vs frontend/.nvmrc (also first step of pr-check / pr-check-fast; before frontend targets)"
	@echo "  npm run check-nvmrc-align"
	@echo "                   - Same check without make"
	@echo "  make test-frontend-unit"
	@echo "                   - Vitest (frontend/npm run test:unit; CI frontend-build; step 3 of pr-check)"
	@echo "  npm run test-frontend-unit"
	@echo "                   - Same from repo root (check-nvmrc-align, then npm --prefix frontend)"
	@echo "  make test-frontend-unit-coverage"
	@echo "                   - Vitest + v8 coverage (workflow/logs/useLogs; not part of pr-check)"
	@echo "  npm run test-frontend-unit-coverage"
	@echo "                   - Same from repo root (check-nvmrc-align, then npm --prefix frontend)"
	@echo "  make build-frontend"
	@echo "                   - Vue prod build (CI frontend-build; step 4 of pr-check)"
	@echo "  npm run build-frontend"
	@echo "                   - Same from repo root (check-nvmrc-align, then npm --prefix frontend)"
	@echo "  make quick-check"
	@echo "                   - check-nvmrc-align + lint-backend only (no pytest / frontend)"
	@echo "  bash scripts/quick-check.sh"
	@echo "                   - Same from any cwd (no make needed)"
	@echo "  npm run quick-check"
	@echo "                   - Same without make"
	@echo "  make production-preflight"
	@echo "                   - Backend deploy slice: quick-check + no-fallback + tenant + helm + merge-gate + compose + monitoring + k8s-manifest-check + dockerfile-hadolint-check（对齐 CI backend-static-analysis；无前端）"
	@echo "  bash scripts/production-preflight.sh"
	@echo "                   - Same from any cwd"
	@echo "  npm run production-preflight"
	@echo "                   - Same without make"
	@echo "  make release-preflight"
	@echo "                   - production-preflight + i18n scan + Vitest + prod build（compose 已在 production-preflight；无 roadmap）"
	@echo "  bash scripts/release-preflight.sh"
	@echo "                   - Same from any cwd"
	@echo "  npm run release-preflight"
	@echo "                   - Same without make"
	@echo "  make pr-check"
	@echo "                   - check-nvmrc-align, then lint + no-fallback + helm-deploy-contract-check + vitest + build + roadmap-acceptance-unit"
	@echo "  make ci"
	@echo "                   - Alias for make pr-check"
	@echo "  SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK=1 make pr-check"
	@echo "                   - Same as pr-check but skip roadmap-acceptance-unit (optional)"
	@echo "  make pr-check-fast"
	@echo "                   - Same as pr-check but skips build-frontend (faster local loop; includes helm-deploy-contract-check + roadmap-acceptance-unit)"
	@echo "  make ci-fast"
	@echo "                   - Alias for make pr-check-fast"
	@echo "  SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK=1 make pr-check-fast"
	@echo "                   - Same as pr-check-fast but skip roadmap-acceptance-unit (optional)"
	@echo "  bash scripts/pr-check.sh / scripts/pr-check-fast.sh"
	@echo "                   - Same as make pr-check / pr-check-fast (any cwd; optional pytest args)"
	@echo "  npm run ci / npm run ci-fast"
	@echo "                   - Same as npm run pr-check / pr-check-fast"
	@echo "  npm run pr-check-fast -- -k test_agents -x"
	@echo "                   - Same from repo root (npm forwards args after -- to the script)"
	@echo "  bash scripts/pr-check-fast.sh -k test_agents -x"
	@echo "                   - Example: narrow no-fallback step only (rest of pr-check unchanged)"
	@echo "  make dependency-policy"
	@echo "                   - Enforce dependency version lock policy"
	@echo "  make dependency-scan"
	@echo "                   - Run third-party dependency vulnerability scan"
	@echo "  DOCTOR_STRICT_WARNINGS=1 make doctor"
	@echo "                   - Treat warnings as failures"
	@echo "  make test-workflow-control-flow"
	@echo "                   - Run workflow control-flow regression suite"
	@echo "  make test-tenant-isolation"
	@echo "                   - Run pytest -m tenant_isolation (MCP / store / middleware tenant suite)"
	@echo "  make roadmap-acceptance-unit"
	@echo "                   - Run roadmap-focused pytest suite"
	@echo "  make roadmap-acceptance-smoke ROADMAP_BASE_URL=http://127.0.0.1:8000 [ROADMAP_API_KEY=...]"
	@echo "                   - Run live roadmap API smoke against running backend"
	@echo "  make roadmap-acceptance-all ROADMAP_RUN_LIVE_SMOKE=1 [ROADMAP_API_KEY=...]"
	@echo "                   - Run roadmap pytest suite + optional live smoke"
	@echo "                   - scripts/acceptance/run_roadmap_acceptance.sh: phase lines on stderr, prefixed by ROADMAP_GATE_LOG_PREFIX"
	@echo "  make roadmap-acceptance-smoke ROADMAP_REQUIRE_GO=1 ROADMAP_MIN_READINESS_AVG=0.8 ROADMAP_MAX_LOWEST_READINESS_SCORE=0.7"
	@echo "                   - Run roadmap smoke with strict release-gate thresholds"
	@echo "  make roadmap-release-gate ROADMAP_BASE_URL=http://127.0.0.1:8000 [ROADMAP_API_KEY=...]"
	@echo "                   - Run one-command strict release gate (live smoke + readiness thresholds)"
	@echo "  make roadmap-release-gate ROADMAP_OUTPUT_JSON=roadmap-release-gate-result.json"
	@echo "                   - Persist machine-readable release gate result JSON"
	@echo "  make roadmap-acceptance-all ROADMAP_RUN_LIVE_SMOKE=1 ROADMAP_OUTPUT_JSON=roadmap-gate.json ROADMAP_OUTPUT_SCHEMA_VERSION=1"
	@echo "                   - Run live smoke and validate output JSON contract"
	@echo "  make roadmap-acceptance-validate-output ROADMAP_OUTPUT_JSON=roadmap-gate.json ROADMAP_OUTPUT_SCHEMA_VERSION=1"
	@echo "                   - Validate an existing roadmap gate output JSON artifact"
	@echo "                   - Exit code semantics: 2=parameter/input error, 1=contract/business failure"
	@echo "  make roadmap-acceptance-validate-schema-version ROADMAP_OUTPUT_SCHEMA_VERSION=1"
	@echo "                   - Validate output schema version variable is positive integer"
	@echo "  make roadmap-acceptance-run-validated ROADMAP_RUN_LIVE_SMOKE=1 ROADMAP_OUTPUT_JSON=roadmap-gate.json"
	@echo "                   - One-command run+validate flow for roadmap acceptance output"
	@echo "                   - Logs prefixed with [roadmap-gate] for CI grep/filter"
	@echo "                   - npm run roadmap-acceptance-validate-output / roadmap-acceptance-run-validated / roadmap-release-gate → scripts/acceptance/*.sh (stderr hints; export ROADMAP_GATE_LOG_PREFIX to customize)"
	@echo "                   - API GET/POST /api/system/roadmap/kpis (platform admin): merged north-star KPI thresholds"
	@echo "                   - API GET /api/system/roadmap/quality-metrics (platform admin): merged metrics, explicit_metric_keys, phase3_kpi_inference_probe"
	@echo "                   - API GET /api/system/roadmap/phases/status (platform admin): snapshot, north_star, phase_gate, go_no_go"
	@echo "                   - API POST /api/system/roadmap/phase-gates (platform admin): merge persisted phase gate overrides"
	@echo "                   - API GET /api/system/roadmap/monthly-review (platform admin): paginated reviews, filters + meta"
	@echo "                   - API POST /api/system/roadmap/monthly-review (platform admin): append gated snapshot review"
	@echo "  make smart-routing-smoke"
	@echo "                   - Run smart routing script/unit smoke tests"
	@echo "  make smart-routing-all-checks"
	@echo "                   - Run full smart routing regression checks"
	@echo "  make smart-routing-load-test MODEL=... BASE_URL=..."
	@echo "                   - Run smart routing load test script"
	@echo "  make smart-routing-experiment MODEL=... CANDIDATE=..."
	@echo "                   - Run one-click experiment (baseline vs candidate)"
	@echo "  make smart-routing-param-scan MODEL=... CANDIDATE=..."
	@echo "                   - Run parameter scan for candidate policy"
	@echo "  make cb-benchmark MODEL=... BASE_URL=..."
	@echo "                   - Run sync/batch/async benchmark for continuous batching"
	@echo "  make cb-doctor [CHECK_API=1]"
	@echo "                   - Validate continuous batch tooling prerequisites"
	@echo "  make cb-grid MODEL=... BASE_URL=..."
	@echo "                   - Run continuous batch parameter grid search"
	@echo "  make cb-recommend"
	@echo "                   - Build recommended continuous batch config from grid summary"
	@echo "  make cb-snapshot / make cb-rollback SNAPSHOT=..."
	@echo "                   - Snapshot/rollback continuous batch config"
	@echo "  make cb-tier"
	@echo "                   - Auto-advice strict/balanced/lenient gate tier"
	@echo "  make cb-gate"
	@echo "                   - Run acceptance gate from latest grid summary"
	@echo "  make cb-triage RUN_DIR=..."
	@echo "                   - Diagnose gate failures and output action suggestions"
	@echo "  make cb-tests"
	@echo "                   - Run continuous batch tooling unit tests"
	@echo "  make cb-fast"
	@echo "                   - Fast verification: cb-tests + cb-doctor"
	@echo "  make cb-latest-report"
	@echo "                   - Show latest pipeline run summary quickly"
	@echo "  make cb-pipeline MODEL=... BASE_URL=... [APPLY=1] [AUTO_TIER=1]"
	@echo "                   - One-shot pipeline: snapshot -> grid -> recommend -> optional apply -> gate"
	@echo "  make cb-pipeline ... SKIP_DOCTOR=1"
	@echo "                   - Skip preflight doctor when already checked upstream"
	@echo "  make cb-all MODEL=... BASE_URL=... [CHECK_API=1] [AUTO_TIER=1] [AUTO_TRIAGE=1]"
	@echo "                   - Unified entry: cb-tests -> cb-doctor -> cb-pipeline"
	@echo "  make cb-release-check MODEL=... BASE_URL=..."
	@echo "                   - Release gate: cb-fast + cb-all"
	@echo "  make cb-pipeline ... AUTO_TRIAGE=1"
	@echo "                   - Auto-run triage suggestions when gate fails"
	@echo "  EVENT_BUS_SMOKE_ADMIN_TOKEN=... make event-bus-smoke"
	@echo "                   - Run EventBus DLQ smoke script against target backend"
	@echo "  EVENT_BUS_SMOKE_ADMIN_TOKEN=... EVENT_BUS_SMOKE_JSON_OUTPUT=event-bus-smoke-result.json make event-bus-smoke"
	@echo "                   - Run EventBus DLQ smoke script and write structured JSON output"
	@echo "  EVENT_BUS_SMOKE_EVENT_TYPE=mcp.streamable.server_rpc EVENT_BUS_SMOKE_ADMIN_TOKEN=... make event-bus-smoke"
	@echo "                   - DLQ smoke with MCP Streamable HTTP server-push event_type (vs default agent.status.changed)"
	@echo "  EVENT_BUS_SMOKE_RESULT_FILE=custom-smoke-result.json make event-bus-smoke-contract"
	@echo "                   - Validate contract using a custom default result filename"
	@echo "  EVENT_BUS_SMOKE_ADMIN_TOKEN=... make event-bus-smoke-pytest"
	@echo "                   - Run pytest external smoke wrapper for EventBus DLQ"
	@echo "  make event-bus-smoke-unit"
	@echo "                   - Run local unit regression tests for EventBus smoke script"
	@echo "  make event-bus-smoke-contract-guard"
	@echo "                   - Run preflight + contract mapping/payload/validator guard checks"
	@echo "  make event-bus-smoke-contract-guard-preflight"
	@echo "                   - Run contract guard preflight layer only"
	@echo "  make event-bus-smoke-contract-guard-mapping"
	@echo "                   - Run contract guard mapping layer only"
	@echo "  make event-bus-smoke-contract-guard-payload"
	@echo "                   - Run contract guard payload layer only"
	@echo "  make event-bus-smoke-contract-guard-validator"
	@echo "                   - Run contract guard validator layer only"
	@echo "  make event-bus-smoke-contract-guard-workflow"
	@echo "                   - Run contract guard workflow layer only"
	@echo "  make event-bus-smoke-contract-guard-status-json [EVENT_BUS_SMOKE_CONTRACT_GUARD_LOG_FILE=event-bus-smoke-contract-guard.log]"
	@echo "                   - Print contract guard layered status in JSON"
	@echo "  make event-bus-smoke-contract [SMOKE_RESULT=event-bus-smoke-result.json]"
	@echo "                   - Validate EventBus smoke JSON contract for a result file"
	@echo "  EVENT_BUS_SMOKE_SCHEMA_VERSION=2 make event-bus-smoke-contract"
	@echo "                   - Validate contract with custom expected schema_version"
	@echo "  EVENT_BUS_SMOKE_SUMMARY_JSON_FILE=event-bus-smoke-summary.json make event-bus-smoke-summary-contract"
	@echo "                   - Validate summary JSON contract artifact"
	@echo "  EVENT_BUS_SMOKE_SUMMARY_SCHEMA_MODE=compatible make event-bus-smoke-summary-contract"
	@echo "                   - Validate summary JSON in backward-compatible mode"
	@echo "  EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE=off make event-bus-smoke-summary-contract"
	@echo "                   - Validate summary JSON while skipping payload sha256 check"
	@echo "  make event-bus-smoke-gh-strict"
	@echo "                   - Trigger GitHub workflow with strict summary schema validation"
	@echo "  make event-bus-smoke-gh-compatible EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION=2"
	@echo "                   - Trigger GitHub workflow with compatible summary schema rehearsal"
	@echo "  make event-bus-smoke-gh-watch-latest"
	@echo "                   - Watch latest Event Bus smoke workflow run and print URL"
	@echo "  make event-bus-smoke-print-gh-inputs"
	@echo "                   - Print effective GitHub workflow input values before trigger"
	@echo "  make event-bus-smoke-print-gh-inputs-json"
	@echo "                   - Print effective GitHub workflow input values in JSON"
	@echo "  make event-bus-smoke-write-gh-inputs-json-file"
	@echo "                   - Write effective GitHub workflow input JSON snapshot to file"
	@echo "  make event-bus-smoke-validate-gh-inputs-snapshot"
	@echo "                   - Validate GitHub workflow input JSON snapshot contract"
	@echo "  EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS=300000 make event-bus-smoke-gh-strict"
	@echo "                   - Trigger workflow with custom stale-threshold input"
	@echo "  make event-bus-smoke-gh-strict-watch"
	@echo "                   - Trigger strict mode run and wait for this run to finish"
	@echo "  EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE=.tmp/gh-trigger-inputs.json make event-bus-smoke-gh-strict-watch"
	@echo "                   - Persist trigger-watch inputs JSON to local audit file"
	@echo "  EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE=.tmp/gh-trigger-inputs.json make event-bus-smoke-validate-gh-trigger-inputs-audit"
	@echo "                   - Validate local trigger-watch inputs audit JSON contract"
	@echo "  EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_MODE=compatible EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_VERSION=2 make event-bus-smoke-validate-gh-trigger-inputs-audit"
	@echo "                   - Validate trigger-watch audit JSON in backward-compatible mode"
	@echo "  EVENT_BUS_SMOKE_GH_TRIGGER_MAX_DURATION_MS=300000 make event-bus-smoke-validate-gh-trigger-inputs-audit"
	@echo "                   - Enforce trigger-watch audit max duration threshold (ms)"
	@echo "  EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS=600000 make event-bus-smoke-validate-gh-trigger-inputs-audit"
	@echo "                   - Enforce trigger-watch audit max age threshold (ms)"
	@echo "  EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION=success make event-bus-smoke-validate-gh-trigger-inputs-audit"
	@echo "                   - Enforce expected workflow run conclusion in trigger-watch audit"
	@echo "  EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION=cancelled make event-bus-smoke-gh-strict-watch"
	@echo "                   - Override default expected conclusion(success) for watch validation"
	@echo "  make event-bus-smoke-gh-compatible-watch EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION=2"
	@echo "                   - Trigger compatible rehearsal run and wait for this run to finish"
	@echo "  EVENT_BUS_SMOKE_SCHEMA_VERSION=1 make event-bus-smoke-validate-schema-version"
	@echo "                   - Validate schema version variable before smoke contract flow"
	@echo "  EVENT_BUS_SMOKE_RESULT_FILE=event-bus-smoke-result.json make event-bus-smoke-validate-result-file"
	@echo "                   - Validate smoke result filename variable is non-empty"
	@echo "  SMOKE_RESULT=custom.json make event-bus-smoke-validate-contract-input"
	@echo "                   - Validate effective contract input path (SMOKE_RESULT fallback)"
	@echo "  EVENT_BUS_SMOKE_JSON_OUTPUT=custom.json make event-bus-smoke-validate-json-output"
	@echo "                   - Validate effective smoke JSON output path is non-empty"
	@echo "  EVENT_BUS_SMOKE_FILE_SUFFIX=run-123 make event-bus-smoke-validate-file-suffix"
	@echo "                   - Validate file suffix format ([A-Za-z0-9._-], max 64)"
	@echo "  EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS=600000 make event-bus-smoke-validate-stale-threshold-ms"
	@echo "                   - Validate stale-threshold variable is non-negative integer"
	@echo "  EVENT_BUS_SMOKE_SUMMARY_SCHEMA_MODE=strict make event-bus-smoke-validate-summary-schema-mode"
	@echo "                   - Validate summary schema mode variable (strict|compatible)"
	@echo "  EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE=strict make event-bus-smoke-validate-payload-sha256-mode"
	@echo "                   - Validate payload sha256 mode variable (strict|off)"
	@echo "  EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION=1 make event-bus-smoke-validate-summary-schema-version"
	@echo "                   - Validate summary schema version variable is positive integer"
	@echo "  make event-bus-smoke-validate-gh-inputs"
	@echo "                   - Validate all GitHub workflow input variables before triggering"
	@echo "  make event-bus-smoke-preflight"
	@echo "                   - Verify EventBus smoke local/CI prerequisites"
	@echo "  make event-bus-smoke-fast"
	@echo "                   - Run EventBus smoke preflight + unit regression checks"
	@echo "  EVENT_BUS_SMOKE_ADMIN_TOKEN=... make event-bus-smoke-run-validated"
	@echo "                   - Run EventBus smoke script and validate JSON contract in one command"
	@echo "  EVENT_BUS_SMOKE_ADMIN_TOKEN=... EVENT_BUS_SMOKE_SCHEMA_VERSION=2 make event-bus-smoke-run-validated"
	@echo "                   - Run smoke+contract with custom expected schema_version"
	@echo "  EVENT_BUS_SMOKE_ADMIN_TOKEN=... EVENT_BUS_SMOKE_RESULT_FILE=custom-smoke-result.json make event-bus-smoke-run-validated"
	@echo "                   - Run smoke+contract with custom result filename"
	@echo "  EVENT_BUS_SMOKE_ADMIN_TOKEN=... EVENT_BUS_SMOKE_FILE_SUFFIX=run-123 make event-bus-smoke-run-validated"
	@echo "                   - Run smoke+contract with suffix-derived result filename"
	@echo "  EVENT_BUS_SMOKE_ADMIN_TOKEN=... make event-bus-smoke-all"
	@echo "                   - Run preflight + unit + smoke+contract + external smoke pytest in one command"
	@echo "  EVENT_BUS_SMOKE_ADMIN_TOKEN=... EVENT_BUS_SMOKE_SCHEMA_VERSION=2 make event-bus-smoke-all"
	@echo "                   - Run full smoke chain with custom expected schema_version"
	@echo "  make drill-alerting"
	@echo "                   - Run one-command alert trigger + recovery verification"
	@echo "  make reset         - Remove containers and volumes"

npm-scripts:
	@bash scripts/npm-scripts.sh

npm-scripts-json:
	@bash scripts/npm-scripts.sh --json

install:
	@bash scripts/install.sh

bootstrap:
	@$(MAKE) env-init
	@$(MAKE) doctor
	@$(MAKE) install

bootstrap-prod:
	@$(MAKE) env-init
	@DOCTOR_STRICT_WARNINGS=1 $(MAKE) doctor
	@$(MAKE) install-prod

env-init:
	@bash scripts/env-init.sh

local-all:
	@bash run-all.sh

local-backend:
	@bash run-backend.sh

local-frontend:
	@bash run-frontend.sh

install-gpu:
	@bash scripts/install-gpu.sh

install-prod:
	@bash scripts/install-prod.sh

install-prod-soft:
	@DOCTOR_STRICT_WARNINGS=0 bash scripts/install-prod.sh

up:
	@bash scripts/up.sh

up-gpu:
	@bash scripts/up-gpu.sh

up-prod:
	@bash scripts/up-prod.sh

up-monitoring:
	@docker compose -f docker-compose.yml -f deploy/monitoring/docker-compose.monitoring.yml up -d

down:
	@bash scripts/down.sh

down-gpu:
	@bash scripts/down-gpu.sh

down-prod:
	@bash scripts/down-prod.sh

down-monitoring:
	@docker compose -f docker-compose.yml -f deploy/monitoring/docker-compose.monitoring.yml down

status:
	@bash scripts/status.sh

status-monitoring:
	@docker compose -f docker-compose.yml -f deploy/monitoring/docker-compose.monitoring.yml ps

monitoring-smoke:
	@python backend/scripts/monitoring_smoke.py \
		--prometheus-url "$(or $(PROMETHEUS_URL),$(MONITORING_PROMETHEUS_URL))" \
		--alertmanager-url "$(or $(ALERTMANAGER_URL),$(MONITORING_ALERTMANAGER_URL))" \
		--grafana-url "$(or $(GRAFANA_URL),$(MONITORING_GRAFANA_URL))"

monitoring-e2e:
	@$(MAKE) up-monitoring
	@$(MAKE) monitoring-smoke \
		PROMETHEUS_URL="$(or $(PROMETHEUS_URL),$(MONITORING_PROMETHEUS_URL))" \
		ALERTMANAGER_URL="$(or $(ALERTMANAGER_URL),$(MONITORING_ALERTMANAGER_URL))" \
		GRAFANA_URL="$(or $(GRAFANA_URL),$(MONITORING_GRAFANA_URL))"
	@$(MAKE) drill-alerting \
		BACKEND_URL="$(or $(BACKEND_URL),$(ALERT_DRILL_BACKEND_URL))" \
		ALERTMANAGER_URL="$(or $(ALERTMANAGER_URL),$(ALERT_DRILL_ALERTMANAGER_URL))" \
		ROUNDS="$(or $(ROUNDS),$(ALERT_DRILL_ROUNDS))" \
		CONCURRENCY="$(or $(CONCURRENCY),$(ALERT_DRILL_CONCURRENCY))" \
		SCRAPE_WAIT_SECONDS="$(or $(SCRAPE_WAIT_SECONDS),$(ALERT_DRILL_SCRAPE_WAIT_SECONDS))" \
		RECOVERY_TIMEOUT_SECONDS="$(or $(RECOVERY_TIMEOUT_SECONDS),$(ALERT_DRILL_RECOVERY_TIMEOUT_SECONDS))" \
		POLL_INTERVAL_SECONDS="$(or $(POLL_INTERVAL_SECONDS),$(ALERT_DRILL_POLL_INTERVAL_SECONDS))" \
		ALERTS="$(or $(ALERTS),$(ALERT_DRILL_ALERTS))"
	@$(MAKE) status-monitoring

monitoring-e2e-clean:
	@status=0; \
	$(MAKE) monitoring-e2e || status=$$?; \
	$(MAKE) down-monitoring; \
	exit $$status

monitoring-all:
	@$(MAKE) ops-drill-guide
	@$(MAKE) monitoring-e2e-clean

ops-drill-guide:
	@echo "perilla Monitoring Drill Guide"
	@echo ""
	@echo "[Local quick path]"
	@echo "  1) make up-monitoring"
	@echo "  2) make monitoring-smoke"
	@echo "  3) make drill-alerting"
	@echo "  4) make status-monitoring"
	@echo "  5) make down-monitoring"
	@echo ""
	@echo "[Local one-command]"
	@echo "  - make monitoring-e2e          # keep stack after run"
	@echo "  - make monitoring-e2e-clean    # auto stop stack after run"
	@echo ""
	@echo "[Parameter overrides]"
	@echo "  - make drill-alerting ROUNDS=50 CONCURRENCY=8 SCRAPE_WAIT_SECONDS=60"
	@echo "  - make monitoring-smoke PROMETHEUS_URL=http://127.0.0.1:9090"
	@echo ""
	@echo "[CI workflow]"
	@echo "  - .github/workflows/monitoring-alerting-e2e.yml"
	@echo "  - Trigger manually via workflow_dispatch or rely on schedule"
	@echo ""
	@echo "[Notification secrets (optional)]"
	@echo "  SMTP_SMARTHOST, SMTP_FROM, SMTP_AUTH_USERNAME, SMTP_AUTH_PASSWORD"
	@echo "  ALERT_EMAIL_TO, ALERT_CRITICAL_EMAIL_TO, SLACK_WEBHOOK_URL, SLACK_ALERT_CHANNEL"

logs:
	@bash scripts/logs.sh

healthcheck:
	@bash scripts/healthcheck.sh

doctor:
	@bash scripts/doctor.sh

security-guardrails:
	@bash scripts/check-security-guardrails.sh

lint-backend:
	@bash scripts/lint-backend.sh

lint: lint-backend

helm-chart-check:
	@bash scripts/helm-chart-check.sh

compose-config-check:
	@bash scripts/compose-config-check.sh

monitoring-config-check:
	@bash scripts/monitoring-config-check.sh

k8s-manifest-check:
	@bash scripts/k8s-manifest-check.sh

dockerfile-hadolint-check:
	@bash scripts/dockerfile-hadolint-check.sh

# Helm lint/template + 合并门禁契约（列表见 scripts/merge-gate-contract-tests.sh）
helm-deploy-contract-check: helm-chart-check
	@bash scripts/merge-gate-contract-tests.sh -q

merge-gate-contract-tests:
	@bash scripts/merge-gate-contract-tests.sh

check-nvmrc-align:
	@bash scripts/check-nvmrc-align.sh

i18n-hardcoded-scan:
	@bash scripts/check-frontend-i18n-hardcoded.sh

test-frontend-unit: check-nvmrc-align
	@cd frontend && npm run test:unit

test-frontend-unit-coverage: check-nvmrc-align
	@cd frontend && npm run test:unit:coverage

build-frontend: check-nvmrc-align
	@cd frontend && npm run build

pr-check: check-nvmrc-align i18n-hardcoded-scan lint-backend test-no-fallback test-tenant-isolation helm-deploy-contract-check test-frontend-unit build-frontend
	@if [ "$(SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK)" = "1" ]; then \
		echo "pr-check: skip roadmap-acceptance-unit (SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK=1)"; \
	else \
		$(MAKE) roadmap-acceptance-unit; \
	fi
	@echo "pr-check: OK"

pr-check-fast: check-nvmrc-align i18n-hardcoded-scan lint-backend test-no-fallback test-tenant-isolation helm-deploy-contract-check test-frontend-unit
	@if [ "$(SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK)" = "1" ]; then \
		echo "pr-check-fast: skip roadmap-acceptance-unit (SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK=1)"; \
	else \
		$(MAKE) roadmap-acceptance-unit; \
	fi
	@echo "pr-check-fast: OK (no build-frontend)"

ci: pr-check

ci-fast: pr-check-fast

quick-check:
	@bash scripts/quick-check.sh

production-preflight:
	@bash scripts/production-preflight.sh

release-preflight:
	@bash scripts/release-preflight.sh

dependency-policy:
	@bash scripts/check-dependency-version-policy.sh

dependency-scan:
	@bash scripts/scan-dependencies.sh

test-no-fallback:
	@bash scripts/test-no-fallback.sh $(TEST_ARGS)

test-workflow-control-flow:
	@bash backend/scripts/test_workflow_control_flow_regression.sh

test-tenant-isolation:
	@PYTHONPATH=backend pytest -m tenant_isolation -q $(TEST_ARGS)

roadmap-acceptance-unit:
	@echo "$(ROADMAP_GATE_LOG_PREFIX) roadmap acceptance unit start"
	@PYTHONPATH=backend pytest \
		backend/tests/test_roadmap_service.py \
		backend/tests/test_system_api_integration.py \
		backend/tests/test_roadmap_acceptance_smoke.py \
		backend/tests/test_roadmap_openapi_contract.py \
		-q -k roadmap
	@echo "$(ROADMAP_GATE_LOG_PREFIX) roadmap acceptance unit done"

roadmap-acceptance-smoke:
	@echo "$(ROADMAP_GATE_LOG_PREFIX) roadmap acceptance smoke start"
	@python backend/scripts/roadmap_acceptance_smoke.py \
		--base-url "$(ROADMAP_BASE_URL)" \
		$(if $(ROADMAP_API_KEY),--api-key "$(ROADMAP_API_KEY)",) \
		$(if $(filter 1,$(ROADMAP_REQUIRE_GO)),--require-go,) \
		$(if $(ROADMAP_MIN_READINESS_AVG),--min-readiness-avg "$(ROADMAP_MIN_READINESS_AVG)",) \
		$(if $(ROADMAP_MAX_LOWEST_READINESS_SCORE),--max-lowest-readiness-score "$(ROADMAP_MAX_LOWEST_READINESS_SCORE)",) \
		$(if $(ROADMAP_OUTPUT_JSON),--output-json "$(ROADMAP_OUTPUT_JSON)",)
	@echo "$(ROADMAP_GATE_LOG_PREFIX) roadmap acceptance smoke done"

roadmap-acceptance-all:
	@echo "$(ROADMAP_GATE_LOG_PREFIX) roadmap acceptance all start"
	@ROADMAP_BASE_URL="$(ROADMAP_BASE_URL)" \
		ROADMAP_API_KEY="$(ROADMAP_API_KEY)" \
		ROADMAP_RUN_LIVE_SMOKE="$(ROADMAP_RUN_LIVE_SMOKE)" \
		ROADMAP_REQUIRE_GO="$(ROADMAP_REQUIRE_GO)" \
		ROADMAP_MIN_READINESS_AVG="$(ROADMAP_MIN_READINESS_AVG)" \
		ROADMAP_MAX_LOWEST_READINESS_SCORE="$(ROADMAP_MAX_LOWEST_READINESS_SCORE)" \
		ROADMAP_OUTPUT_JSON="$(ROADMAP_OUTPUT_JSON)" \
		ROADMAP_OUTPUT_SCHEMA_VERSION="$(ROADMAP_OUTPUT_SCHEMA_VERSION)" \
		ROADMAP_GATE_LOG_PREFIX="$(ROADMAP_GATE_LOG_PREFIX)" \
		bash scripts/acceptance/run_roadmap_acceptance.sh
	@echo "$(ROADMAP_GATE_LOG_PREFIX) roadmap acceptance all done"

roadmap-acceptance-validate-schema-version:
	@python -c "import sys; p='$(ROADMAP_GATE_LOG_PREFIX)'; v='$(ROADMAP_OUTPUT_SCHEMA_VERSION)'; ok=v.isdigit() and int(v)>0; print(f'{p} ROADMAP_OUTPUT_SCHEMA_VERSION must be a positive integer, got: {v}', file=sys.stderr) if not ok else None; sys.exit(2 if not ok else 0)"

roadmap-acceptance-validate-output:
	@echo "$(ROADMAP_GATE_LOG_PREFIX) validating roadmap output artifact"
	@$(MAKE) roadmap-acceptance-validate-schema-version
	@python -c "import sys; prefix='$(ROADMAP_GATE_LOG_PREFIX)'; p='$(ROADMAP_OUTPUT_JSON)'; ok=bool(str(p).strip()); print(f'{prefix} ROADMAP_OUTPUT_JSON must be non-empty', file=sys.stderr) if not ok else None; sys.exit(2 if not ok else 0)"
	@python backend/scripts/validate_roadmap_acceptance_result.py \
		--input "$(ROADMAP_OUTPUT_JSON)" \
		--expected-schema-version "$(ROADMAP_OUTPUT_SCHEMA_VERSION)"

roadmap-acceptance-run-validated:
	@echo "$(ROADMAP_GATE_LOG_PREFIX) run+validate roadmap acceptance flow"
	@$(MAKE) roadmap-acceptance-validate-schema-version
	@python -c "import sys; prefix='$(ROADMAP_GATE_LOG_PREFIX)'; p='$(ROADMAP_OUTPUT_JSON)'; ok=bool(str(p).strip()); print(f'{prefix} ROADMAP_OUTPUT_JSON must be non-empty', file=sys.stderr) if not ok else None; sys.exit(2 if not ok else 0)"
	@$(MAKE) roadmap-acceptance-all \
		ROADMAP_BASE_URL="$(ROADMAP_BASE_URL)" \
		ROADMAP_API_KEY="$(ROADMAP_API_KEY)" \
		ROADMAP_RUN_LIVE_SMOKE="$(or $(ROADMAP_RUN_LIVE_SMOKE),1)" \
		ROADMAP_REQUIRE_GO="$(ROADMAP_REQUIRE_GO)" \
		ROADMAP_MIN_READINESS_AVG="$(ROADMAP_MIN_READINESS_AVG)" \
		ROADMAP_MAX_LOWEST_READINESS_SCORE="$(ROADMAP_MAX_LOWEST_READINESS_SCORE)" \
		ROADMAP_OUTPUT_JSON="$(ROADMAP_OUTPUT_JSON)" \
		ROADMAP_OUTPUT_SCHEMA_VERSION="$(ROADMAP_OUTPUT_SCHEMA_VERSION)"

roadmap-release-gate:
	@echo "$(ROADMAP_GATE_LOG_PREFIX) strict release gate start"
	@ROADMAP_RUN_LIVE_SMOKE=1 \
		ROADMAP_REQUIRE_GO="$(or $(ROADMAP_REQUIRE_GO),1)" \
		ROADMAP_MIN_READINESS_AVG="$(or $(ROADMAP_MIN_READINESS_AVG),0.8)" \
		ROADMAP_MAX_LOWEST_READINESS_SCORE="$(or $(ROADMAP_MAX_LOWEST_READINESS_SCORE),0.7)" \
		$(MAKE) roadmap-acceptance-run-validated ROADMAP_BASE_URL="$(ROADMAP_BASE_URL)" ROADMAP_API_KEY="$(ROADMAP_API_KEY)" ROADMAP_OUTPUT_JSON="$(ROADMAP_OUTPUT_JSON)" ROADMAP_OUTPUT_SCHEMA_VERSION="$(ROADMAP_OUTPUT_SCHEMA_VERSION)"

smart-routing-smoke:
	@PYTHONPATH=backend pytest backend/tests/test_smart_routing_script_utils.py backend/tests/test_model_router_smart_routing.py backend/tests/test_smart_routing_validation.py

smart-routing-all-checks:
	@$(MAKE) smart-routing-smoke

smart-routing-load-test:
	@python backend/scripts/smart_routing_load_test.py \
		--base-url "$(or $(BASE_URL),http://127.0.0.1:8000)" \
		--model "$(or $(MODEL),ollama:deepseek-r1:32b)" \
		--duration-seconds "$(or $(DURATION),30)" \
		--rps "$(or $(RPS),5)" \
		--concurrency "$(or $(CONCURRENCY),10)" \
		--large-ratio "$(or $(LARGE_RATIO),0.6)" \
		--min-success-rate "$(or $(MIN_SUCCESS_RATE),0.95)" \
		--max-avg-latency-ms "$(or $(MAX_AVG_LATENCY_MS),2500)" \
		--min-fallback-ratio "$(or $(MIN_FALLBACK_RATIO),0.0)" \
		--report-file "$(or $(REPORT),./tmp/smart-routing-load-report.json)" \
		$(if $(API_KEY),--api-key "$(API_KEY)",) \
		$(if $(API_KEY_HEADER),--api-key-header "$(API_KEY_HEADER)",)

smart-routing-experiment:
	@python backend/scripts/run_smart_routing_experiment.py \
		--base-url "$(or $(BASE_URL),http://127.0.0.1:8000)" \
		--model "$(or $(MODEL),ollama:deepseek-r1:32b)" \
		--candidate-policy-file "$(or $(CANDIDATE),backend/scripts/candidate_policy.example.json)" \
		--output-dir "$(or $(OUTPUT),./tmp/smart-routing-exp)" \
		--duration-seconds "$(or $(DURATION),30)" \
		--rps "$(or $(RPS),6)" \
		--concurrency "$(or $(CONCURRENCY),12)" \
		--large-ratio "$(or $(LARGE_RATIO),0.6)" \
		--promote-only-if-better \
		--promote-require-pass \
		$(if $(FAIL_ON_NO_PROMOTE),--fail-on-no-promote,) \
		$(if $(PROMOTE_REPORT),--promote-report-file "$(PROMOTE_REPORT)",) \
		$(if $(API_KEY),--api-key "$(API_KEY)",) \
		$(if $(API_KEY_HEADER),--api-key-header "$(API_KEY_HEADER)",)

smart-routing-param-scan:
	@python backend/scripts/smart_routing_param_scan.py \
		--base-url "$(or $(BASE_URL),http://127.0.0.1:8000)" \
		--model "$(or $(MODEL),ollama:deepseek-r1:32b)" \
		--candidate-policy-file "$(or $(CANDIDATE),backend/scripts/candidate_policy.example.json)" \
		--scan-model-alias "$(or $(SCAN_ALIAS),$(or $(MODEL),ollama:deepseek-r1:32b))" \
		--duration-seconds "$(or $(DURATION),20)" \
		--rps "$(or $(RPS),6)" \
		--concurrency "$(or $(CONCURRENCY),12)" \
		--large-ratio "$(or $(LARGE_RATIO),0.6)" \
		--top-k "$(or $(TOP_K),5)" \
		--max-scan-combos "$(or $(MAX_SCAN_COMBOS),100)" \
		--max-estimated-minutes "$(or $(MAX_ESTIMATED_MINUTES),45)" \
		--estimated-warn-ratio "$(or $(ESTIMATED_WARN_RATIO),0.7)" \
		--estimated-fail-ratio "$(or $(ESTIMATED_FAIL_RATIO),1.0)" \
		$(if $(PASS_ONLY),--pass-only,) \
		$(if $(DRY_RUN),--dry-run,) \
		$(if $(APPLY_BEST),--apply-best-policy,) \
		$(if $(EXPORT_BEST),--export-best-policy-file "$(EXPORT_BEST)",) \
		$(if $(API_KEY),--api-key "$(API_KEY)",) \
		$(if $(API_KEY_HEADER),--api-key-header "$(API_KEY_HEADER)",) \
		--output-dir "$(or $(OUTPUT),./tmp/smart-routing-scan)"

cb-doctor:
	@python backend/scripts/continuous_batch_doctor.py \
		--repo-root "." \
		--output-root "$(or $(PIPELINE_ROOT),backend/data/benchmarks/pipeline)" \
		$(if $(CHECK_API),--check-api,) \
		--base-url "$(or $(BASE_URL),$(CB_BASE_URL))" \
		--timeout-seconds "$(or $(TIMEOUT),10)" \
		$(if $(API_KEY),--api-key "$(API_KEY)",) \
		$(if $(API_KEY_HEADER),--api-key-header "$(API_KEY_HEADER)",)

cb-benchmark:
	@python backend/scripts/continuous_batch_benchmark.py \
		--base-url "$(or $(BASE_URL),$(CB_BASE_URL))" \
		--model "$(or $(MODEL),$(CB_MODEL))" \
		--requests "$(or $(REQUESTS),60)" \
		--concurrency "$(or $(CONCURRENCY),$(CB_CONCURRENCY))" \
		--batch-wait-ms "$(or $(BATCH_WAIT_MS),$(CB_BATCH_WAIT_MS))" \
		--batch-max-size "$(or $(BATCH_MAX_SIZE),$(CB_BATCH_MAX_SIZE))" \
		--timeout-seconds "$(or $(TIMEOUT),$(CB_TIMEOUT))" \
		--report-file "$(or $(REPORT),backend/data/benchmarks/continuous-batch.json)" \
		$(if $(API_KEY),--api-key "$(API_KEY)",) \
		$(if $(API_KEY_HEADER),--api-key-header "$(API_KEY_HEADER)",)

cb-grid:
	@python backend/scripts/continuous_batch_grid_search.py \
		--base-url "$(or $(BASE_URL),$(CB_BASE_URL))" \
		--model "$(or $(MODEL),$(CB_MODEL))" \
		--requests "$(or $(REQUESTS),$(CB_REQUESTS))" \
		--concurrency-list "$(or $(CONCURRENCY_LIST),$(CB_CONCURRENCY_LIST))" \
		--wait-ms-list "$(or $(WAIT_MS_LIST),$(CB_WAIT_MS_LIST))" \
		--max-size-list "$(or $(MAX_SIZE_LIST),$(CB_MAX_SIZE_LIST))" \
		--top-k "$(or $(TOP_K),$(CB_TOP_K))" \
		--timeout-seconds "$(or $(TIMEOUT),$(CB_TIMEOUT))" \
		--output-dir "$(or $(OUTPUT_DIR),backend/data/benchmarks/grid)" \
		--summary-file "$(or $(SUMMARY),backend/data/benchmarks/grid/summary.json)" \
		$(if $(API_KEY),--api-key "$(API_KEY)",) \
		$(if $(API_KEY_HEADER),--api-key-header "$(API_KEY_HEADER)",)

cb-recommend:
	@python backend/scripts/continuous_batch_recommend.py \
		--summary-file "$(or $(SUMMARY),backend/data/benchmarks/grid/summary.json)" \
		--base-url "$(or $(BASE_URL),$(CB_BASE_URL))" \
		--min-throughput-ratio "$(or $(MIN_THROUGHPUT_RATIO),$(CB_MIN_THROUGHPUT_RATIO))" \
		--max-first-response-ratio "$(or $(MAX_FIRST_RESPONSE_RATIO),$(CB_MAX_FIRST_RESPONSE_RATIO))" \
		--output-file "$(or $(RECOMMEND_OUT),backend/data/benchmarks/grid/recommended_config.json)" \
		$(if $(APPLY),--apply,) \
		$(if $(API_KEY),--api-key "$(API_KEY)",) \
		$(if $(API_KEY_HEADER),--api-key-header "$(API_KEY_HEADER)",)

cb-snapshot:
	@python backend/scripts/continuous_batch_rollback.py \
		--base-url "$(or $(BASE_URL),$(CB_BASE_URL))" \
		$(if $(API_KEY),--api-key "$(API_KEY)",) \
		$(if $(API_KEY_HEADER),--api-key-header "$(API_KEY_HEADER)",) \
		snapshot \
		--output-file "$(or $(SNAPSHOT_OUT),backend/data/benchmarks/grid/snapshot.json)"

cb-rollback:
	@python backend/scripts/continuous_batch_rollback.py \
		--base-url "$(or $(BASE_URL),$(CB_BASE_URL))" \
		$(if $(API_KEY),--api-key "$(API_KEY)",) \
		$(if $(API_KEY_HEADER),--api-key-header "$(API_KEY_HEADER)",) \
		rollback \
		--snapshot-file "$(or $(SNAPSHOT),backend/data/benchmarks/grid/snapshot.json)"

cb-tier:
	@python backend/scripts/continuous_batch_tier_advisor.py \
		--input "$(or $(INPUT),backend/data/benchmarks/pipeline)" \
		--last-n "$(or $(LAST_N),$(CB_LAST_N))" \
		--output-file "$(or $(TIER_OUT),backend/data/benchmarks/pipeline/tier-advice.json)"

cb-gate:
	@python backend/scripts/continuous_batch_acceptance_gate.py \
		--summary-file "$(or $(SUMMARY),backend/data/benchmarks/grid/summary.json)" \
		--min-throughput-ratio "$(or $(MIN_THROUGHPUT_RATIO),$(CB_MIN_THROUGHPUT_RATIO))" \
		--max-first-response-ratio "$(or $(MAX_FIRST_RESPONSE_RATIO),$(CB_MAX_FIRST_RESPONSE_RATIO))" \
		--min-success-rate "$(or $(MIN_SUCCESS_RATE),$(CB_MIN_SUCCESS_RATE))" \
		--output-file "$(or $(GATE_OUT),backend/data/benchmarks/grid/gate-result.json)"

cb-triage:
	@python backend/scripts/continuous_batch_triage.py \
		$(if $(RUN_DIR),--run-dir "$(RUN_DIR)",) \
		$(if $(GATE_FILE),--gate-file "$(GATE_FILE)",) \
		$(if $(SUMMARY),--summary-file "$(SUMMARY)",) \
		--output-file "$(or $(TRIAGE_OUT),backend/data/benchmarks/grid/triage.json)"

cb-tests:
	@PYTHONPATH=backend pytest \
		backend/tests/test_continuous_batch_tooling.py \
		backend/tests/test_continuous_batch_run_all.py \
		backend/tests/test_continuous_batch_latest_report.py \
		backend/tests/test_continuous_batch_doctor.py \
		-q

cb-fast:
	@$(MAKE) cb-tests
	@$(MAKE) cb-doctor

cb-latest-report:
	@python backend/scripts/continuous_batch_latest_report.py \
		--pipeline-root "$(or $(PIPELINE_ROOT),backend/data/benchmarks/pipeline)" \
		$(if $(RUN_DIR),--run-dir "$(RUN_DIR)",) \
		$(if $(REPORT_OUT),--output-file "$(REPORT_OUT)",)

cb-pipeline:
	@$(if $(SKIP_DOCTOR),echo [cb-pipeline] SKIP_DOCTOR=1 skipping cb-doctor,$(MAKE) cb-doctor $(if $(CHECK_API),CHECK_API=1,) \
		BASE_URL="$(or $(BASE_URL),$(CB_BASE_URL))" \
		PIPELINE_ROOT="$(or $(PIPELINE_ROOT),backend/data/benchmarks/pipeline)" \
		$(if $(API_KEY),API_KEY="$(API_KEY)",) \
		$(if $(API_KEY_HEADER),API_KEY_HEADER="$(API_KEY_HEADER)",))
	@python backend/scripts/continuous_batch_run_all.py \
		--base-url "$(or $(BASE_URL),$(CB_BASE_URL))" \
		--model "$(or $(MODEL),$(CB_MODEL))" \
		--requests "$(or $(REQUESTS),$(CB_REQUESTS))" \
		--concurrency-list "$(or $(CONCURRENCY_LIST),$(CB_CONCURRENCY_LIST))" \
		--wait-ms-list "$(or $(WAIT_MS_LIST),$(CB_WAIT_MS_LIST))" \
		--max-size-list "$(or $(MAX_SIZE_LIST),$(CB_MAX_SIZE_LIST))" \
		--timeout-seconds "$(or $(TIMEOUT),$(CB_TIMEOUT))" \
		--gate \
		--gate-min-throughput-ratio "$(or $(MIN_THROUGHPUT_RATIO),$(CB_MIN_THROUGHPUT_RATIO))" \
		--gate-max-first-response-ratio "$(or $(MAX_FIRST_RESPONSE_RATIO),$(CB_MAX_FIRST_RESPONSE_RATIO))" \
		--gate-min-success-rate "$(or $(MIN_SUCCESS_RATE),$(CB_MIN_SUCCESS_RATE))" \
		$(if $(SKIP_DOCTOR),--skip-doctor,) \
		$(if $(AUTO_TIER),--auto-tier,) \
		$(if $(AUTO_TRIAGE),--auto-triage,) \
		$(if $(APPLY),--apply,) \
		$(if $(API_KEY),--api-key "$(API_KEY)",) \
		$(if $(API_KEY_HEADER),--api-key-header "$(API_KEY_HEADER)",)

cb-all:
	@$(MAKE) cb-tests
	@$(MAKE) cb-doctor \
		$(if $(CHECK_API),CHECK_API=1,) \
		BASE_URL="$(or $(BASE_URL),$(CB_BASE_URL))" \
		PIPELINE_ROOT="$(or $(PIPELINE_ROOT),backend/data/benchmarks/pipeline)" \
		$(if $(API_KEY),API_KEY="$(API_KEY)",) \
		$(if $(API_KEY_HEADER),API_KEY_HEADER="$(API_KEY_HEADER)",)
	@$(MAKE) cb-pipeline \
		BASE_URL="$(or $(BASE_URL),$(CB_BASE_URL))" \
		MODEL="$(or $(MODEL),$(CB_MODEL))" \
		REQUESTS="$(or $(REQUESTS),$(CB_REQUESTS))" \
		CONCURRENCY_LIST="$(or $(CONCURRENCY_LIST),$(CB_CONCURRENCY_LIST))" \
		WAIT_MS_LIST="$(or $(WAIT_MS_LIST),$(CB_WAIT_MS_LIST))" \
		MAX_SIZE_LIST="$(or $(MAX_SIZE_LIST),$(CB_MAX_SIZE_LIST))" \
		TIMEOUT="$(or $(TIMEOUT),$(CB_TIMEOUT))" \
		MIN_THROUGHPUT_RATIO="$(or $(MIN_THROUGHPUT_RATIO),$(CB_MIN_THROUGHPUT_RATIO))" \
		MAX_FIRST_RESPONSE_RATIO="$(or $(MAX_FIRST_RESPONSE_RATIO),$(CB_MAX_FIRST_RESPONSE_RATIO))" \
		MIN_SUCCESS_RATE="$(or $(MIN_SUCCESS_RATE),$(CB_MIN_SUCCESS_RATE))" \
		$(if $(AUTO_TIER),AUTO_TIER=1,) \
		$(if $(AUTO_TRIAGE),AUTO_TRIAGE=1,) \
		$(if $(APPLY),APPLY=1,) \
		$(if $(CHECK_API),CHECK_API=1,) \
		SKIP_DOCTOR=1 \
		$(if $(API_KEY),API_KEY="$(API_KEY)",) \
		$(if $(API_KEY_HEADER),API_KEY_HEADER="$(API_KEY_HEADER)",)

cb-release-check:
	@$(MAKE) cb-fast \
		BASE_URL="$(or $(BASE_URL),$(CB_BASE_URL))" \
		$(if $(API_KEY),API_KEY="$(API_KEY)",) \
		$(if $(API_KEY_HEADER),API_KEY_HEADER="$(API_KEY_HEADER)",)
	@$(MAKE) cb-all \
		BASE_URL="$(or $(BASE_URL),$(CB_BASE_URL))" \
		MODEL="$(or $(MODEL),$(CB_MODEL))" \
		REQUESTS="$(or $(REQUESTS),$(CB_REQUESTS))" \
		CONCURRENCY_LIST="$(or $(CONCURRENCY_LIST),$(CB_CONCURRENCY_LIST))" \
		WAIT_MS_LIST="$(or $(WAIT_MS_LIST),$(CB_WAIT_MS_LIST))" \
		MAX_SIZE_LIST="$(or $(MAX_SIZE_LIST),$(CB_MAX_SIZE_LIST))" \
		TIMEOUT="$(or $(TIMEOUT),$(CB_TIMEOUT))" \
		MIN_THROUGHPUT_RATIO="$(or $(MIN_THROUGHPUT_RATIO),$(CB_MIN_THROUGHPUT_RATIO))" \
		MAX_FIRST_RESPONSE_RATIO="$(or $(MAX_FIRST_RESPONSE_RATIO),$(CB_MAX_FIRST_RESPONSE_RATIO))" \
		MIN_SUCCESS_RATE="$(or $(MIN_SUCCESS_RATE),$(CB_MIN_SUCCESS_RATE))" \
		$(if $(AUTO_TIER),AUTO_TIER=1,) \
		$(if $(AUTO_TRIAGE),AUTO_TRIAGE=1,) \
		$(if $(APPLY),APPLY=1,) \
		$(if $(CHECK_API),CHECK_API=1,) \
		$(if $(API_KEY),API_KEY="$(API_KEY)",) \
		$(if $(API_KEY_HEADER),API_KEY_HEADER="$(API_KEY_HEADER)",)

event-bus-smoke:
	@if [ -z "$$EVENT_BUS_SMOKE_ADMIN_TOKEN" ]; then \
		echo "EVENT_BUS_SMOKE_ADMIN_TOKEN is required"; \
		exit 2; \
	fi
	@PYTHONPATH=backend python backend/scripts/event_bus_dlq_smoke.py \
		--base-url "$(EVENT_BUS_BASE_URL)" \
		--admin-token "$$EVENT_BUS_SMOKE_ADMIN_TOKEN" \
		--event-type "$(EVENT_BUS_SMOKE_EVENT_TYPE)" \
		--limit "$(EVENT_BUS_SMOKE_LIMIT)" \
		$(if $(EVENT_BUS_SMOKE_JSON_OUTPUT),--json-output "$(EVENT_BUS_SMOKE_JSON_OUTPUT)",)

event-bus-smoke-pytest:
	@if [ -z "$$EVENT_BUS_SMOKE_ADMIN_TOKEN" ]; then \
		echo "EVENT_BUS_SMOKE_ADMIN_TOKEN is required"; \
		exit 2; \
	fi
	@EVENT_BUS_SMOKE_BASE_URL="$(EVENT_BUS_BASE_URL)" \
		EVENT_BUS_SMOKE_ADMIN_TOKEN="$$EVENT_BUS_SMOKE_ADMIN_TOKEN" \
		EVENT_BUS_SMOKE_EVENT_TYPE="$(EVENT_BUS_SMOKE_EVENT_TYPE)" \
		EVENT_BUS_SMOKE_LIMIT="$(EVENT_BUS_SMOKE_LIMIT)" \
		PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
		PYTHONPATH=backend \
		python -m pytest -c backend/tests/pytest.smoke.ini backend/tests/test_event_bus_smoke_external.py

event-bus-smoke-unit:
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=backend \
		python -m pytest -c backend/tests/pytest.smoke.ini \
		backend/tests/test_event_bus_dlq_smoke_script.py \
		backend/tests/test_event_bus_smoke_gh_trigger_watch.py \
		backend/tests/test_make_event_bus_smoke_stale_threshold_validation.py \
		backend/tests/test_make_event_bus_smoke_summary_schema_mode_validation.py \
		backend/tests/test_make_event_bus_smoke_summary_schema_version_validation.py \
		backend/tests/test_make_event_bus_smoke_gh_inputs_validation.py \
		backend/tests/test_make_event_bus_smoke_contract_guard.py \
		backend/tests/test_make_event_bus_smoke_contract_guard_status_json.py \
		backend/tests/test_make_event_bus_smoke_gh_trigger_max_age_validation.py \
		backend/tests/test_make_event_bus_smoke_gh_trigger_expected_conclusion_validation.py \
		backend/tests/test_make_event_bus_smoke_print_gh_inputs.py \
		backend/tests/test_make_event_bus_smoke_print_gh_inputs_json.py \
		backend/tests/test_make_event_bus_smoke_write_gh_inputs_json_file.py \
		backend/tests/test_make_help_smoke_targets.py \
		backend/tests/test_event_bus_smoke_result_contract.py \
		backend/tests/test_event_bus_smoke_summary_keys_contract.py \
		backend/tests/test_event_bus_smoke_summary_payload.py \
		backend/tests/test_event_bus_smoke_summary_reason_codes.py \
		backend/tests/test_event_bus_smoke_gh_inputs_snapshot_contract.py \
		backend/tests/test_event_bus_smoke_workflow_contract_guard_step.py \
		backend/tests/test_event_bus_smoke_contract_guard_summary.py \
		backend/tests/test_event_bus_smoke_preflight.py \
		backend/tests/test_event_bus_smoke_summary_health.py \
		backend/tests/test_event_bus_smoke_reason_codes.py \
		backend/tests/test_event_bus_smoke_summary_contract.py \
		backend/tests/test_event_bus_smoke_json_integrity_contract.py \
		backend/tests/test_event_bus_smoke_error_code_contract.py \
		backend/tests/test_event_bus_smoke_error_codes_constants_contract.py \
		backend/tests/test_event_bus_smoke_error_code_preflight_json_contract.py \
		backend/tests/test_event_bus_smoke_error_code_guard_targets_contract.py \
		backend/tests/test_event_bus_smoke_error_code_coverage_contract.py \
		backend/tests/test_make_event_bus_smoke_gh_trigger_audit_mapping_contract.py \
		backend/tests/test_event_bus_smoke_gh_trigger_audit_payload_contract.py \
		backend/tests/test_event_bus_smoke_gh_trigger_inputs_audit_contract.py

event-bus-smoke-contract-guard:
	@echo "[guard] preflight"
	@$(MAKE) event-bus-smoke-contract-guard-preflight
	@echo "[guard] mapping"
	@$(MAKE) event-bus-smoke-contract-guard-mapping
	@echo "[guard] payload"
	@$(MAKE) event-bus-smoke-contract-guard-payload
	@echo "[guard] validator"
	@$(MAKE) event-bus-smoke-contract-guard-validator
	@echo "[guard] workflow"
	@$(MAKE) event-bus-smoke-contract-guard-workflow

event-bus-smoke-contract-guard-preflight:
	@$(MAKE) event-bus-smoke-preflight

event-bus-smoke-contract-guard-mapping:
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=backend \
		python -m pytest -c backend/tests/pytest.smoke.ini \
		backend/tests/test_make_event_bus_smoke_gh_trigger_audit_mapping_contract.py

event-bus-smoke-contract-guard-payload:
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=backend \
		python -m pytest -c backend/tests/pytest.smoke.ini \
		backend/tests/test_event_bus_smoke_gh_inputs_snapshot_contract.py \
		backend/tests/test_event_bus_smoke_gh_trigger_audit_payload_contract.py

event-bus-smoke-contract-guard-validator:
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=backend \
		python -m pytest -c backend/tests/pytest.smoke.ini \
		backend/tests/test_event_bus_smoke_gh_trigger_inputs_audit_contract.py \
		backend/tests/test_event_bus_smoke_error_code_contract.py \
		backend/tests/test_event_bus_smoke_error_codes_constants_contract.py \
		backend/tests/test_event_bus_smoke_error_code_preflight_json_contract.py \
		backend/tests/test_event_bus_smoke_error_code_guard_targets_contract.py \
		backend/tests/test_event_bus_smoke_error_code_coverage_contract.py

event-bus-smoke-contract-guard-workflow:
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=backend \
		python -m pytest -c backend/tests/pytest.smoke.ini \
		backend/tests/test_event_bus_smoke_workflow_contract_guard_step.py

event-bus-smoke-contract-guard-status-json:
	@PYTHONPATH=backend python backend/scripts/print_event_bus_smoke_contract_guard_status.py \
		--input "$(EVENT_BUS_SMOKE_CONTRACT_GUARD_LOG_FILE)"

event-bus-smoke-contract:
	@$(MAKE) event-bus-smoke-validate-schema-version
	@$(MAKE) event-bus-smoke-validate-contract-input
	@python backend/scripts/validate_event_bus_smoke_result.py \
		--input "$(or $(SMOKE_RESULT),$(EVENT_BUS_SMOKE_RESULT_FILE))" \
		--expected-schema-version "$(EVENT_BUS_SMOKE_SCHEMA_VERSION)"

event-bus-smoke-summary-contract:
	@$(MAKE) event-bus-smoke-validate-payload-sha256-mode
	@PYTHONPATH=backend python backend/scripts/validate_event_bus_smoke_summary_result.py \
		--input "$(or $(EVENT_BUS_SMOKE_SUMMARY_JSON_FILE),event-bus-smoke-summary.json)" \
		--expected-summary-schema-version "$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION)" \
		--schema-mode "$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_MODE)" \
		--payload-sha256-mode "$(EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE)"

event-bus-smoke-gh-strict:
	@$(MAKE) event-bus-smoke-validate-gh-inputs
	@$(MAKE) event-bus-smoke-print-gh-inputs
	@$(MAKE) event-bus-smoke-write-gh-inputs-json-file
	@$(MAKE) event-bus-smoke-validate-gh-inputs-snapshot
	@gh workflow run "$(EVENT_BUS_SMOKE_GH_WORKFLOW)" \
		-f base_url="$(EVENT_BUS_BASE_URL)" \
		-f event_type="$(EVENT_BUS_SMOKE_EVENT_TYPE)" \
		-f limit="$(EVENT_BUS_SMOKE_LIMIT)" \
		-f expected_schema_version="$(EVENT_BUS_SMOKE_SCHEMA_VERSION)" \
		-f expected_summary_schema_version="$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION)" \
		-f summary_schema_mode="strict" \
		-f payload_sha256_mode="$(EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE)" \
		-f result_file_stale_threshold_ms="$(EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS)" \
		-f file_suffix="$(EVENT_BUS_SMOKE_FILE_SUFFIX)"

event-bus-smoke-gh-compatible:
	@$(MAKE) event-bus-smoke-validate-gh-inputs
	@$(MAKE) event-bus-smoke-print-gh-inputs
	@$(MAKE) event-bus-smoke-write-gh-inputs-json-file
	@$(MAKE) event-bus-smoke-validate-gh-inputs-snapshot
	@gh workflow run "$(EVENT_BUS_SMOKE_GH_WORKFLOW)" \
		-f base_url="$(EVENT_BUS_BASE_URL)" \
		-f event_type="$(EVENT_BUS_SMOKE_EVENT_TYPE)" \
		-f limit="$(EVENT_BUS_SMOKE_LIMIT)" \
		-f expected_schema_version="$(EVENT_BUS_SMOKE_SCHEMA_VERSION)" \
		-f expected_summary_schema_version="$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION)" \
		-f summary_schema_mode="compatible" \
		-f payload_sha256_mode="$(EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE)" \
		-f result_file_stale_threshold_ms="$(EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS)" \
		-f file_suffix="$(EVENT_BUS_SMOKE_FILE_SUFFIX)"

event-bus-smoke-gh-watch-latest:
	@run_id="$$(gh run list --workflow "$(EVENT_BUS_SMOKE_GH_WORKFLOW)" --limit 1 --json databaseId --jq '.[0].databaseId')"; \
	if [ -z "$$run_id" ] || [ "$$run_id" = "null" ]; then \
		echo "No run found for workflow: $(EVENT_BUS_SMOKE_GH_WORKFLOW)"; \
		exit 2; \
	fi; \
	echo "Watching run id: $$run_id"; \
	gh run watch "$$run_id"; \
	run_url="$$(gh run view "$$run_id" --json url --jq '.url')"; \
	conclusion="$$(gh run view "$$run_id" --json conclusion --jq '.conclusion')"; \
	echo "Run URL: $$run_url"; \
	echo "Conclusion: $$conclusion"

event-bus-smoke-print-gh-inputs:
	@echo "workflow=$(EVENT_BUS_SMOKE_GH_WORKFLOW)"
	@echo "base_url=$(EVENT_BUS_BASE_URL)"
	@echo "event_type=$(EVENT_BUS_SMOKE_EVENT_TYPE)"
	@echo "limit=$(EVENT_BUS_SMOKE_LIMIT)"
	@echo "expected_schema_version=$(EVENT_BUS_SMOKE_SCHEMA_VERSION)"
	@echo "expected_summary_schema_version=$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION)"
	@echo "summary_schema_mode=$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_MODE)"
	@echo "payload_sha256_mode=$(EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE)"
	@echo "result_file_stale_threshold_ms=$(EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS)"
	@echo "file_suffix=$(EVENT_BUS_SMOKE_FILE_SUFFIX)"

event-bus-smoke-print-gh-inputs-json:
	@python -c "import json; print(json.dumps({ \
'workflow': '$(EVENT_BUS_SMOKE_GH_WORKFLOW)', \
'base_url': '$(EVENT_BUS_BASE_URL)', \
'event_type': '$(EVENT_BUS_SMOKE_EVENT_TYPE)', \
'limit': '$(EVENT_BUS_SMOKE_LIMIT)', \
'expected_schema_version': '$(EVENT_BUS_SMOKE_SCHEMA_VERSION)', \
'expected_summary_schema_version': '$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION)', \
'summary_schema_mode': '$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_MODE)', \
'payload_sha256_mode': '$(EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE)', \
'result_file_stale_threshold_ms': '$(EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS)', \
'file_suffix': '$(EVENT_BUS_SMOKE_FILE_SUFFIX)' \
}, ensure_ascii=False, sort_keys=True))"

event-bus-smoke-write-gh-inputs-json-file:
	@python -c "import hashlib, json, time; from pathlib import Path; p=Path('$(EVENT_BUS_SMOKE_GH_INPUTS_JSON_FILE)'); payload={ \
'schema_version': 1, \
'generated_at_ms': int(time.time()*1000), \
'source': 'make event-bus-smoke-write-gh-inputs-json-file', \
'workflow': '$(EVENT_BUS_SMOKE_GH_WORKFLOW)', \
'base_url': '$(EVENT_BUS_BASE_URL)', \
'event_type': '$(EVENT_BUS_SMOKE_EVENT_TYPE)', \
'limit': '$(EVENT_BUS_SMOKE_LIMIT)', \
'expected_schema_version': '$(EVENT_BUS_SMOKE_SCHEMA_VERSION)', \
'expected_summary_schema_version': '$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION)', \
'summary_schema_mode': '$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_MODE)', \
'payload_sha256_mode': '$(EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE)', \
'result_file_stale_threshold_ms': '$(EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS)', \
'file_suffix': '$(EVENT_BUS_SMOKE_FILE_SUFFIX)' \
}; canonical=json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')); payload['payload_sha256']=hashlib.sha256(canonical.encode('utf-8')).hexdigest(); p.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding='utf-8'); print(f'Wrote gh inputs snapshot: {p}')"

event-bus-smoke-validate-gh-inputs-snapshot:
	@$(MAKE) event-bus-smoke-validate-payload-sha256-mode
	@PYTHONPATH=backend python backend/scripts/validate_event_bus_smoke_gh_inputs_snapshot.py \
		--input "$(EVENT_BUS_SMOKE_GH_INPUTS_JSON_FILE)" \
		--expected-schema-version 1 \
		--payload-sha256-mode "$(EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE)"

event-bus-smoke-validate-gh-trigger-inputs-audit:
	@python -c "import sys; p='$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE)'; \
ok=bool(str(p).strip()); \
print('EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE must be non-empty') if not ok else None; \
sys.exit(2 if not ok else 0)"
	@$(MAKE) event-bus-smoke-validate-gh-trigger-inputs-audit-schema-version
	@$(MAKE) event-bus-smoke-validate-gh-trigger-inputs-audit-schema-mode
	@$(MAKE) event-bus-smoke-validate-gh-trigger-expected-conclusion
	@$(MAKE) event-bus-smoke-validate-gh-trigger-max-duration-ms
	@$(MAKE) event-bus-smoke-validate-gh-trigger-max-age-ms
	@$(MAKE) event-bus-smoke-validate-payload-sha256-mode
	@PYTHONPATH=backend python backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py \
		--input "$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE)" \
		--payload-sha256-mode "$(EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE)" \
		--expected-schema-version "$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_VERSION)" \
		--schema-mode "$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_MODE)" \
		$(if $(EVENT_BUS_SMOKE_GH_TRIGGER_MODE),--expected-trigger-mode "$(EVENT_BUS_SMOKE_GH_TRIGGER_MODE)",) \
		$(if $(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_WORKFLOW),--expected-workflow "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_WORKFLOW)",) \
		$(if $(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_BASE_URL),--expected-base-url "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_BASE_URL)",) \
		$(if $(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_EVENT_TYPE),--expected-event-type "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_EVENT_TYPE)",) \
		$(if $(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_LIMIT),--expected-limit "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_LIMIT)",) \
		$(if $(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_STALE_THRESHOLD_MS),--expected-result-file-stale-threshold-ms "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_STALE_THRESHOLD_MS)",) \
		$(if $(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_SUMMARY_SCHEMA_VERSION),--expected-summary-schema-version "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_SUMMARY_SCHEMA_VERSION)",) \
		$(if $(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_RESULT_SCHEMA_VERSION),--expected-result-schema-version "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_RESULT_SCHEMA_VERSION)",) \
		--expected-file-suffix "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_FILE_SUFFIX)" \
		$(if $(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION),--expected-conclusion "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION)",) \
		$(if $(EVENT_BUS_SMOKE_GH_TRIGGER_MAX_DURATION_MS),--max-duration-ms "$(EVENT_BUS_SMOKE_GH_TRIGGER_MAX_DURATION_MS)",) \
		$(if $(EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS),--max-age-ms "$(EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS)",)

event-bus-smoke-gh-strict-watch:
	@$(MAKE) event-bus-smoke-validate-gh-inputs
	@$(MAKE) event-bus-smoke-print-gh-inputs
	@$(MAKE) event-bus-smoke-write-gh-inputs-json-file
	@$(MAKE) event-bus-smoke-validate-gh-inputs-snapshot
	@PYTHONPATH=backend python backend/scripts/event_bus_smoke_gh_trigger_watch.py \
		--workflow "$(EVENT_BUS_SMOKE_GH_WORKFLOW)" \
		--mode strict \
		--base-url "$(EVENT_BUS_BASE_URL)" \
		--event-type "$(EVENT_BUS_SMOKE_EVENT_TYPE)" \
		--limit "$(EVENT_BUS_SMOKE_LIMIT)" \
		--expected-schema-version "$(EVENT_BUS_SMOKE_SCHEMA_VERSION)" \
		--expected-summary-schema-version "$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION)" \
		--payload-sha256-mode "$(EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE)" \
		--result-file-stale-threshold-ms "$(EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS)" \
		--file-suffix "$(EVENT_BUS_SMOKE_FILE_SUFFIX)" \
		--expected-conclusion "$(or $(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION),success)" \
		--trigger-inputs-audit-file "$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE)"
	@if [ -n "$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE)" ]; then \
		$(MAKE) event-bus-smoke-validate-gh-trigger-inputs-audit EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE="$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE)" EVENT_BUS_SMOKE_GH_TRIGGER_MODE="strict" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_WORKFLOW="$(EVENT_BUS_SMOKE_GH_WORKFLOW)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_BASE_URL="$(EVENT_BUS_BASE_URL)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_EVENT_TYPE="$(EVENT_BUS_SMOKE_EVENT_TYPE)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_LIMIT="$(EVENT_BUS_SMOKE_LIMIT)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_STALE_THRESHOLD_MS="$(EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_SUMMARY_SCHEMA_VERSION="$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_RESULT_SCHEMA_VERSION="$(EVENT_BUS_SMOKE_SCHEMA_VERSION)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_FILE_SUFFIX="$(EVENT_BUS_SMOKE_FILE_SUFFIX)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION="$(or $(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION),success)"; \
	fi

event-bus-smoke-gh-compatible-watch:
	@$(MAKE) event-bus-smoke-validate-gh-inputs
	@$(MAKE) event-bus-smoke-print-gh-inputs
	@$(MAKE) event-bus-smoke-write-gh-inputs-json-file
	@$(MAKE) event-bus-smoke-validate-gh-inputs-snapshot
	@PYTHONPATH=backend python backend/scripts/event_bus_smoke_gh_trigger_watch.py \
		--workflow "$(EVENT_BUS_SMOKE_GH_WORKFLOW)" \
		--mode compatible \
		--base-url "$(EVENT_BUS_BASE_URL)" \
		--event-type "$(EVENT_BUS_SMOKE_EVENT_TYPE)" \
		--limit "$(EVENT_BUS_SMOKE_LIMIT)" \
		--expected-schema-version "$(EVENT_BUS_SMOKE_SCHEMA_VERSION)" \
		--expected-summary-schema-version "$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION)" \
		--payload-sha256-mode "$(EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE)" \
		--result-file-stale-threshold-ms "$(EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS)" \
		--file-suffix "$(EVENT_BUS_SMOKE_FILE_SUFFIX)" \
		--expected-conclusion "$(or $(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION),success)" \
		--trigger-inputs-audit-file "$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE)"
	@if [ -n "$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE)" ]; then \
		$(MAKE) event-bus-smoke-validate-gh-trigger-inputs-audit EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE="$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE)" EVENT_BUS_SMOKE_GH_TRIGGER_MODE="compatible" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_WORKFLOW="$(EVENT_BUS_SMOKE_GH_WORKFLOW)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_BASE_URL="$(EVENT_BUS_BASE_URL)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_EVENT_TYPE="$(EVENT_BUS_SMOKE_EVENT_TYPE)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_LIMIT="$(EVENT_BUS_SMOKE_LIMIT)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_STALE_THRESHOLD_MS="$(EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_SUMMARY_SCHEMA_VERSION="$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_RESULT_SCHEMA_VERSION="$(EVENT_BUS_SMOKE_SCHEMA_VERSION)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_FILE_SUFFIX="$(EVENT_BUS_SMOKE_FILE_SUFFIX)" EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION="$(or $(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION),success)"; \
	fi

event-bus-smoke-validate-schema-version:
	@python -c "import sys; v='$(EVENT_BUS_SMOKE_SCHEMA_VERSION)'; \
ok=v.isdigit() and int(v)>0; \
print(f'EVENT_BUS_SMOKE_SCHEMA_VERSION must be a positive integer, got: {v}') if not ok else None; \
sys.exit(2 if not ok else 0)"

event-bus-smoke-validate-result-file:
	@python -c "import sys; v='$(EVENT_BUS_SMOKE_RESULT_FILE)'; \
ok=bool(v.strip()); \
print(f'EVENT_BUS_SMOKE_RESULT_FILE must be non-empty, got: {v!r}') if not ok else None; \
sys.exit(2 if not ok else 0)"

event-bus-smoke-validate-contract-input:
	@python -c "import sys; v='$(or $(SMOKE_RESULT),$(EVENT_BUS_SMOKE_RESULT_FILE))'; \
ok=bool(v.strip()); \
print(f'Effective contract input path must be non-empty, got: {v!r}') if not ok else None; \
sys.exit(2 if not ok else 0)"

event-bus-smoke-validate-json-output:
	@$(MAKE) event-bus-smoke-validate-result-file
	@$(MAKE) event-bus-smoke-validate-file-suffix
	@python -c "import sys; out='$(EVENT_BUS_SMOKE_EFFECTIVE_RESULT_FILE)'; \
ok=bool(out.strip()); \
print(f'Effective smoke json output path must be non-empty, got: {out!r}') if not ok else None; \
sys.exit(2 if not ok else 0)"

event-bus-smoke-validate-file-suffix:
	@python -c "import re, sys; s='$(EVENT_BUS_SMOKE_FILE_SUFFIX)'; \
ok=(not s) or (len(s)<=64 and re.fullmatch(r'[A-Za-z0-9._-]+', s) is not None); \
print(f\"EVENT_BUS_SMOKE_FILE_SUFFIX is invalid: {s!r}. Allowed: [A-Za-z0-9._-], max 64\") if not ok else None; \
sys.exit(2 if not ok else 0)"

event-bus-smoke-validate-stale-threshold-ms:
	@python -c "import sys; v='$(EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS)'; \
ok=v.isdigit(); \
print(f'EVENT_BUS_SMOKE_RESULT_FILE_STALE_THRESHOLD_MS must be a non-negative integer, got: {v}') if not ok else None; \
sys.exit(2 if not ok else 0)"

event-bus-smoke-validate-summary-schema-mode:
	@python -c "import sys; m='$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_MODE)'; \
ok=m in ('strict','compatible'); \
print(f'EVENT_BUS_SMOKE_SUMMARY_SCHEMA_MODE must be one of: strict,compatible; got: {m}') if not ok else None; \
sys.exit(2 if not ok else 0)"

event-bus-smoke-validate-payload-sha256-mode:
	@python -c "import sys; m='$(EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE)'; \
ok=m in ('strict','off'); \
print(f'EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE must be one of: strict,off; got: {m}') if not ok else None; \
sys.exit(2 if not ok else 0)"

event-bus-smoke-validate-summary-schema-version:
	@python -c "import sys; v='$(EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION)'; \
ok=v.isdigit() and int(v)>0; \
print(f'EVENT_BUS_SMOKE_SUMMARY_SCHEMA_VERSION must be a positive integer, got: {v}') if not ok else None; \
sys.exit(2 if not ok else 0)"

event-bus-smoke-validate-gh-trigger-inputs-audit-schema-version:
	@python -c "import sys; v='$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_VERSION)'; \
ok=v.isdigit() and int(v)>0; \
print(f'EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_VERSION must be a positive integer, got: {v}') if not ok else None; \
sys.exit(2 if not ok else 0)"

event-bus-smoke-validate-gh-trigger-inputs-audit-schema-mode:
	@python -c "import sys; m='$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_MODE)'; \
ok=m in ('strict','compatible'); \
print(f'EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_MODE must be one of: strict,compatible; got: {m}') if not ok else None; \
sys.exit(2 if not ok else 0)"

event-bus-smoke-validate-gh-trigger-expected-conclusion:
	@python -c "import sys; v='$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION)'; \
allowed={'','success','failure','cancelled','skipped','timed_out','action_required','neutral','stale'}; \
ok=v in allowed; \
print(f'EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION must be empty or one of: success,failure,cancelled,skipped,timed_out,action_required,neutral,stale; got: {v}') if not ok else None; \
sys.exit(2 if not ok else 0)"

event-bus-smoke-validate-gh-trigger-max-duration-ms:
	@python -c "import sys; v='$(EVENT_BUS_SMOKE_GH_TRIGGER_MAX_DURATION_MS)'; \
ok=(v=='') or v.isdigit(); \
print(f'EVENT_BUS_SMOKE_GH_TRIGGER_MAX_DURATION_MS must be empty or a non-negative integer, got: {v}') if not ok else None; \
sys.exit(2 if not ok else 0)"

event-bus-smoke-validate-gh-trigger-max-age-ms:
	@python -c "import sys; v='$(EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS)'; \
ok=(v=='') or v.isdigit(); \
print(f'EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS must be empty or a non-negative integer, got: {v}') if not ok else None; \
sys.exit(2 if not ok else 0)"

event-bus-smoke-validate-gh-inputs:
	@$(MAKE) event-bus-smoke-validate-schema-version
	@$(MAKE) event-bus-smoke-validate-summary-schema-version
	@$(MAKE) event-bus-smoke-validate-summary-schema-mode
	@$(MAKE) event-bus-smoke-validate-payload-sha256-mode
	@$(MAKE) event-bus-smoke-validate-stale-threshold-ms

event-bus-smoke-preflight:
	@PYTHONPATH=backend python backend/scripts/event_bus_smoke_preflight.py

event-bus-smoke-fast:
	@$(MAKE) event-bus-smoke-validate-schema-version
	@$(MAKE) event-bus-smoke-preflight
	@$(MAKE) event-bus-smoke-unit

event-bus-smoke-run-validated:
	@$(if $(EVENT_BUS_SMOKE_SKIP_SCHEMA_VALIDATE),true,$(MAKE) event-bus-smoke-validate-schema-version)
	@$(MAKE) event-bus-smoke-validate-result-file
	@$(MAKE) event-bus-smoke-validate-json-output
	@$(MAKE) event-bus-smoke-validate-file-suffix
	@$(MAKE) event-bus-smoke \
		EVENT_BUS_SMOKE_JSON_OUTPUT="$(EVENT_BUS_SMOKE_EFFECTIVE_RESULT_FILE)"
	@$(MAKE) event-bus-smoke-contract \
		SMOKE_RESULT="$(EVENT_BUS_SMOKE_EFFECTIVE_RESULT_FILE)" \
		EVENT_BUS_SMOKE_SCHEMA_VERSION="$(EVENT_BUS_SMOKE_SCHEMA_VERSION)"

event-bus-smoke-all:
	@if [ -z "$$EVENT_BUS_SMOKE_ADMIN_TOKEN" ]; then \
		echo "EVENT_BUS_SMOKE_ADMIN_TOKEN is required"; \
		exit 2; \
	fi
	@$(MAKE) event-bus-smoke-fast
	@$(MAKE) event-bus-smoke-run-validated \
		EVENT_BUS_SMOKE_JSON_OUTPUT="$(or $(EVENT_BUS_SMOKE_JSON_OUTPUT),$(EVENT_BUS_SMOKE_RESULT_FILE))" \
		EVENT_BUS_SMOKE_SKIP_SCHEMA_VALIDATE=1
	@$(MAKE) event-bus-smoke-pytest

drill-alerting:
	@python backend/scripts/alerting_e2e_drill.py \
		--backend-url "$(or $(BACKEND_URL),$(ALERT_DRILL_BACKEND_URL))" \
		--alertmanager-url "$(or $(ALERTMANAGER_URL),$(ALERT_DRILL_ALERTMANAGER_URL))" \
		--rounds "$(or $(ROUNDS),$(ALERT_DRILL_ROUNDS))" \
		--concurrency "$(or $(CONCURRENCY),$(ALERT_DRILL_CONCURRENCY))" \
		--scrape-wait-seconds "$(or $(SCRAPE_WAIT_SECONDS),$(ALERT_DRILL_SCRAPE_WAIT_SECONDS))" \
		--recovery-timeout-seconds "$(or $(RECOVERY_TIMEOUT_SECONDS),$(ALERT_DRILL_RECOVERY_TIMEOUT_SECONDS))" \
		--poll-interval-seconds "$(or $(POLL_INTERVAL_SECONDS),$(ALERT_DRILL_POLL_INTERVAL_SECONDS))" \
		--alerts "$(or $(ALERTS),$(ALERT_DRILL_ALERTS))"

reset:
	@bash scripts/reset.sh
