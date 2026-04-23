#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[security-guardrails] running production guardrail checks..."
PYTHONPATH=backend python3 - <<'PY'
from config.settings import Settings, apply_production_security_defaults, validate_production_security_guardrails

# CI 门禁：始终按生产模式进行校验
settings = Settings(debug=False)
apply_production_security_defaults(settings)
issues = validate_production_security_guardrails(settings)

if issues:
    print("[security-guardrails] blocked:")
    for issue in issues:
        print(f" - {issue}")
    raise SystemExit(1)

print("[security-guardrails] passed")
PY
