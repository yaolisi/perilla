#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

warn_count=0
critical_count=0
strict_warnings="${DOCTOR_STRICT_WARNINGS:-0}"

ok() {
  echo "[OK] $1"
}

warn() {
  echo "[WARN] $1"
  warn_count=$((warn_count + 1))
}

critical() {
  echo "[CRITICAL] $1"
  critical_count=$((critical_count + 1))
}

check_command() {
  local cmd="$1"
  local msg="$2"
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$msg"
  else
    critical "$msg (missing command: $cmd)"
  fi
}

echo "== OpenVitamin Docker Doctor =="
echo "Working directory: ${ROOT_DIR}"

check_command docker "docker is installed"

if docker compose version >/dev/null 2>&1; then
  ok "docker compose plugin is available"
else
  critical "docker compose plugin is unavailable"
fi

if [[ ! -f ".env" ]]; then
  warn ".env not found (copy from .env.example first)"
else
  ok ".env file exists"
fi

if [[ -f ".env.example" ]]; then
  ok ".env.example file exists"
else
  warn ".env.example is missing"
fi

if [[ -d "backend" && -f "backend/main.py" ]]; then
  ok "backend source exists in current folder"
else
  critical "backend source missing in current folder (expect backend/main.py)"
fi

if [[ -d "frontend" && -f "frontend/package.json" ]]; then
  ok "frontend source exists in current folder"
else
  critical "frontend source missing in current folder (expect frontend/package.json)"
fi

echo ""
echo "== Node (.nvmrc) =="
if bash scripts/check-nvmrc-align.sh; then
  ok ".nvmrc matches frontend/.nvmrc"
else
  critical ".nvmrc alignment failed (required for make pr-check / CI)"
fi

if [[ -f ".env" ]]; then
  if [[ ! -f docker-compose.yml ]]; then
    critical "docker-compose.yml missing — cannot validate compose stacks"
  else
    if docker compose --env-file .env -f docker-compose.yml config >/dev/null 2>&1; then
      ok "base compose config is valid"
    else
      critical "base compose config validation failed"
    fi

    if [[ -f docker-compose.gpu.yml ]]; then
      if docker compose --env-file .env -f docker-compose.yml -f docker-compose.gpu.yml config >/dev/null 2>&1; then
        ok "gpu compose override is valid"
      else
        critical "gpu compose override validation failed"
      fi
    else
      warn "docker-compose.gpu.yml missing — skipped gpu compose validation"
    fi

    if [[ -f docker-compose.prod.yml ]]; then
      if docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml config >/dev/null 2>&1; then
        ok "prod compose override is valid"
      else
        critical "prod compose override validation failed"
      fi
    else
      warn "docker-compose.prod.yml missing — skipped prod compose validation"
    fi
  fi
fi

FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
if [[ -f ".env" ]]; then
  # shellcheck disable=SC1091
  source .env || true
  FRONTEND_PORT="${FRONTEND_PORT:-5173}"
  BACKEND_PORT="${BACKEND_PORT:-8000}"
fi

for p in "${FRONTEND_PORT}" "${BACKEND_PORT}"; do
  if command -v lsof >/dev/null 2>&1; then
    if lsof -iTCP:"${p}" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
      warn "port ${p} is already in use"
    else
      ok "port ${p} is available"
    fi
  else
    warn "lsof not found, cannot verify port ${p}"
  fi
done

echo ""
if [[ "${critical_count}" -gt 0 ]]; then
  echo "Doctor check failed with ${critical_count} critical issue(s) and ${warn_count} warning(s)."
  echo "Fix critical issues before install/up."
  exit 2
elif [[ "${strict_warnings}" == "1" && "${warn_count}" -gt 0 ]]; then
  echo "Doctor strict mode enabled: warning(s) treated as failure."
  echo "Doctor check failed with ${warn_count} warning(s)."
  exit 3
elif [[ "${warn_count}" -gt 0 ]]; then
  echo "Doctor check completed with ${warn_count} warning(s)."
  echo "Review warnings above before install/up."
else
  echo "Doctor check passed with no warnings."
fi
