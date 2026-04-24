#!/usr/bin/env bash
# Canary routing + admin stable preference smoke gate.
set -euo pipefail

: "${BASE_URL:?}" "${ADMIN_KEY:?}" "${USER_KEY:?}"
: "${MODEL_ALIAS:?}" "${STABLE_MODEL:?}" "${CANARY_MODEL:?}"
: "${CANARY_PERCENT:=10}" "${CANARY_TOLERANCE_PCT:=5}" "${ADMIN_STABLE_MIN_PCT:=95}"
: "${MAX_FAIL_RATE_PCT:=3}" "${MAX_P95_MS:=5000}"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

apply_config() {
  local body
  body="$(python3 - <<'PY'
import json, os
alias = os.environ["MODEL_ALIAS"]
policies = {
    alias: {
        "strategy": "canary",
        "stable": os.environ["STABLE_MODEL"],
        "canary": os.environ["CANARY_MODEL"],
        "canary_percent": int(os.environ.get("CANARY_PERCENT", "10")),
    }
}
print(json.dumps({
    "inferenceSmartRoutingEnabled": True,
    "inferenceSmartRoutingPoliciesJson": json.dumps(policies),
}))
PY
)"
  curl -sS -f -X POST "${BASE_URL}/api/system/config" \
    -H "Content-Type: application/json" \
    -H "X-Api-Key: ${ADMIN_KEY}" \
    -d "${body}" >/dev/null
}

apply_config

run_one() {
  local role="$1" idx="$2" key="${USER_KEY}" meta_json='{}'
  if [[ "$role" == "admin" ]]; then
    key="${ADMIN_KEY}"
    meta_json='{"role":"admin","is_admin":true}'
  fi
  export CI_ROLE="$role" CI_IDX="$idx" CI_META_JSON="$meta_json"
  local t0 t1 ms resp
  t0="$(python3 -c 'import time; print(int(time.time()*1000))')"
  resp="$(curl -sS -X POST "${BASE_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "X-Api-Key: ${key}" \
    -H "X-User-Id: ci-${role}-user" \
    -d "$(python3 - <<'PY'
import json, os
print(json.dumps({
    "model": os.environ["MODEL_ALIAS"],
    "messages": [{"role": "user", "content": f"ci-{os.environ['CI_ROLE']}-{os.environ['CI_IDX']}"}],
    "stream": False,
    "metadata": json.loads(os.environ["CI_META_JSON"]),
}))
PY
)" || true)"
  t1="$(python3 -c 'import time; print(int(time.time()*1000))')"
  ms=$((t1 - t0))
  rf="$(mktemp)"
  printf '%s' "$resp" >"$rf"
  python3 - "$rf" "$ms" "$role" >>"$TMP" <<'PY'
import json, sys

path, ms_s, role = sys.argv[1], int(sys.argv[2]), sys.argv[3]
with open(path, encoding="utf-8") as f:
    resp = f.read()
ok = 0
resolved = ""
try:
    d = json.loads(resp)
    m = d.get("metadata") or {}
    resolved = str(m.get("resolved_model") or d.get("model") or "")
    ok = 1
except Exception:
    pass
print(json.dumps({"role": role, "ok": ok, "latency_ms": ms_s, "resolved": resolved}))
PY
  rm -f "$rf"
}

for i in $(seq 1 120); do run_one user "$i"; done
for i in $(seq 1 30); do run_one admin "$i"; done

python3 - "$TMP" "$STABLE_MODEL" "$CANARY_MODEL" "$CANARY_PERCENT" "$CANARY_TOLERANCE_PCT" "$ADMIN_STABLE_MIN_PCT" "$MAX_FAIL_RATE_PCT" "$MAX_P95_MS" <<'PY'
import json, sys, math

path = sys.argv[1]
stable, canary = sys.argv[2], sys.argv[3]
target = float(sys.argv[4])
tol = float(sys.argv[5])
admin_min = float(sys.argv[6])
max_fail = float(sys.argv[7])
max_p95 = float(sys.argv[8])

rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
ok = [r for r in rows if int(r.get("ok") or 0) == 1]
fail_pct = ((len(rows) - len(ok)) / len(rows) * 100) if rows else 100.0
users = [r for r in ok if r.get("role") == "user"]
admins = [r for r in ok if r.get("role") == "admin"]
u_canary = sum(1 for r in users if canary in (r.get("resolved") or ""))
a_stable = sum(1 for r in admins if stable in (r.get("resolved") or ""))
u_pct = (u_canary / len(users) * 100) if users else 0.0
a_pct = (a_stable / len(admins) * 100) if admins else 0.0
lat = sorted([int(r["latency_ms"]) for r in ok])
p95 = lat[max(0, min(len(lat) - 1, math.ceil(len(lat) * 0.95) - 1))] if lat else 0.0
checks = [
    ("fail_rate", fail_pct <= max_fail, f"{fail_pct:.2f}% <= {max_fail:.2f}%"),
    ("canary_ratio", (target - tol) <= u_pct <= (target + tol), f"{u_pct:.2f}% in [{target - tol:.2f}, {target + tol:.2f}]"),
    ("admin_stable_ratio", a_pct >= admin_min, f"{a_pct:.2f}% >= {admin_min:.2f}%"),
    ("p95_latency", p95 <= max_p95, f"{p95:.0f} <= {max_p95:.0f} ms"),
]
for name, okc, msg in checks:
    print(f"[{'PASS' if okc else 'FAIL'}] {name}: {msg}")
if not all(c[1] for c in checks):
    raise SystemExit(1)
PY
