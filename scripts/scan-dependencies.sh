#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
if [[ ! -f backend/requirements/base.txt ]]; then
  echo >&2 "scan-dependencies.sh: missing backend/requirements/base.txt (${ROOT_DIR})"
  exit 1
fi

echo "[dep-scan] installing scanner tooling..."
TMP_VENV_DIR=".tmp/dependency-scan-venv"
python3 -m venv "$TMP_VENV_DIR"
source "$TMP_VENV_DIR/bin/activate"
python -m pip install --upgrade pip >/dev/null
python -m pip install pip-audit >/dev/null

echo "[dep-scan] running vulnerability audit..."
# --strict: 漏洞存在时返回非零退出码，阻断 CI
# CVE-2025-69872 (diskcache): pickle 反序列化；上游截至 5.6.3 无修复版，OSV/Debian 仍标 unfixed。
# 缓解：限制应用使用的 cache 目录写权限，不信任攻击者可写的缓存文件。待上游发版后移除此 --ignore-vuln。
python - <<'PY'
import subprocess
import sys

cmd = [
    sys.executable,
    "-m",
    "pip_audit",
    "-r",
    "backend/requirements/base.txt",
    "--strict",
    "--ignore-vuln",
    "CVE-2025-69872",
]
try:
    completed = subprocess.run(cmd, check=False, timeout=600)
except subprocess.TimeoutExpired:
    print("[dep-scan] pip-audit timed out after 600s", file=sys.stderr)
    raise SystemExit(1)
raise SystemExit(completed.returncode)
PY
