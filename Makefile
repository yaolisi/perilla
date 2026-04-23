.PHONY: help bootstrap bootstrap-prod env-init install install-gpu install-prod install-prod-soft up up-gpu up-prod down down-gpu down-prod status logs healthcheck doctor test-no-fallback reset

help:
	@echo "OpenVitamin Docker helper targets:"
	@echo "  make bootstrap     - First-time setup (env-init + doctor + install)"
	@echo "  make bootstrap-prod"
	@echo "                   - First-time prod setup (env-init + strict doctor + install-prod)"
	@echo "  make env-init      - Initialize .env from .env.example"
	@echo "  make install       - Build and start base profile"
	@echo "  make install-gpu   - Build and start GPU profile"
	@echo "  make install-prod  - Build and start production profile"
	@echo "  make install-prod-soft"
	@echo "                   - Build/start prod profile with relaxed doctor warnings"
	@echo "  make up            - Start base profile"
	@echo "  make up-gpu        - Start GPU profile"
	@echo "  make up-prod       - Start production profile"
	@echo "  make down          - Stop base profile"
	@echo "  make down-gpu      - Stop GPU profile"
	@echo "  make down-prod     - Stop production profile"
	@echo "  make status        - Show status in all profile views"
	@echo "  make logs          - Tail logs"
	@echo "  make healthcheck   - Run health checks"
	@echo "  make doctor        - Run environment diagnostics"
	@echo "  DOCTOR_STRICT_WARNINGS=1 make doctor"
	@echo "                   - Treat warnings as failures"
	@echo "  make test-no-fallback"
	@echo "                   - Run API no-fallback regression tests"
	@echo "  make test-no-fallback TEST_ARGS=\"-k memory -x\""
	@echo "                   - Run subset/extra pytest args for no-fallback suite"
	@echo "  make reset         - Remove containers and volumes"

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

down:
	@bash scripts/down.sh

down-gpu:
	@bash scripts/down-gpu.sh

down-prod:
	@bash scripts/down-prod.sh

status:
	@bash scripts/status.sh

logs:
	@bash scripts/logs.sh

healthcheck:
	@bash scripts/healthcheck.sh

doctor:
	@bash scripts/doctor.sh

test-no-fallback:
	@bash scripts/test-no-fallback.sh $(TEST_ARGS)

reset:
	@bash scripts/reset.sh
