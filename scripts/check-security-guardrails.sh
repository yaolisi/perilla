#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
if [[ ! -d backend ]]; then
  echo >&2 "check-security-guardrails.sh: missing backend/ (${ROOT_DIR})"
  exit 1
fi

# 使用与 pytest/lint 相同的解释器：裸 python3 常为系统 Python，未必装有 backend 依赖。
pick_python() {
  local cand py
  local candidates=()
  [[ -n "${PERILLA_PYTHON:-}" ]] && candidates+=("${PERILLA_PYTHON}")
  if [[ -n "${CONDA_PREFIX:-}" && -x "${CONDA_PREFIX}/bin/python" ]]; then
    candidates+=("${CONDA_PREFIX}/bin/python")
  fi
  candidates+=("python" "python3")
  for cand in "${candidates[@]}"; do
    [[ -z "${cand}" ]] && continue
    py=""
    if [[ -x "$cand" ]]; then
      py="$cand"
    elif command -v "$cand" >/dev/null 2>&1; then
      py="$(command -v "$cand")"
    else
      continue
    fi
    if PYTHONPATH=backend "$py" -c "import pydantic" >/dev/null 2>&1; then
      printf '%s' "$py"
      return 0
    fi
  done
  echo >&2 "[security-guardrails] no Python found with backend deps (import pydantic failed)."
  echo >&2 "  Activate the conda env used for the backend (see AGENTS.md), or install backend/requirements/base.txt."
  echo >&2 "  Override: PERILLA_PYTHON=/path/to/python bash scripts/check-security-guardrails.sh"
  exit 1
}

PYBIN="$(pick_python)"
echo "[security-guardrails] running production guardrail checks (python: ${PYBIN})..."
PYTHONPATH=backend "$PYBIN" - <<'PY'
from pathlib import Path

from config.settings import (
    Settings,
    apply_production_security_defaults,
    bootstrap_env_files,
    validate_production_security_guardrails,
)

# 与 main.py 一致：加载 backend/.env、仓库根 .env、可选 .env.encrypted（便于上线前本地/流水线校验）
bootstrap_env_files(Path.cwd() / "backend")

# 门禁：始终按生产模式进行校验（依赖环境中的生产变量）
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
