#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQ_FILE="${ROOT_DIR}/backend/requirements/base.txt"

echo "[dep-policy] validating core dependency version policy..."

python3 - <<'PY'
from pathlib import Path
import re
import sys

req_file = Path("backend/requirements/base.txt")
lines = req_file.read_text(encoding="utf-8").splitlines()

specs: dict[str, str] = {}
pattern = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(.*)$")
for raw in lines:
    line = raw.strip()
    if not line or line.startswith("#") or line.startswith("-r "):
        continue
    line = line.split(";", 1)[0].strip()
    m = pattern.match(line)
    if not m:
        continue
    name = m.group(1).lower()
    spec = (m.group(2) or "").strip()
    specs[name] = spec

errors: list[str] = []

fastapi_spec = specs.get("fastapi", "")
if not fastapi_spec.startswith("=="):
    errors.append("fastapi must be pinned with exact version (==x.y.z)")

sqlalchemy_spec = specs.get("sqlalchemy", "")
if "<3.0.0" not in sqlalchemy_spec.replace(" ", ""):
    errors.append("sqlalchemy must include upper bound <3.0.0")
if ">=2." not in sqlalchemy_spec.replace(" ", ""):
    errors.append("sqlalchemy must stay on major v2 (>=2.x)")

if errors:
    print("[dep-policy] blocked:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("[dep-policy] passed")
PY
