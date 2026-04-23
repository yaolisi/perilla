#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[dep-scan] installing scanner tooling..."
TMP_VENV_DIR=".tmp/dependency-scan-venv"
python3 -m venv "$TMP_VENV_DIR"
source "$TMP_VENV_DIR/bin/activate"
python -m pip install --upgrade pip >/dev/null
python -m pip install pip-audit >/dev/null

echo "[dep-scan] running vulnerability audit..."
# --strict: 漏洞存在时返回非零退出码，阻断 CI
python - <<'PY'
import subprocess
import sys

cmd = [sys.executable, "-m", "pip_audit", "-r", "backend/requirements/base.txt", "--strict"]
try:
    completed = subprocess.run(cmd, check=False, timeout=600)
except subprocess.TimeoutExpired:
    print("[dep-scan] pip-audit timed out after 600s", file=sys.stderr)
    raise SystemExit(1)
raise SystemExit(completed.returncode)
PY
