#!/usr/bin/env bash
# least_loaded strategy smoke gate (resolved_via + success rate + p95).
set -euo pipefail

: "${BASE_URL:?}" "${ADMIN_KEY:?}" "${USER_KEY:?}"
: "${LEAST_ALIAS:?}" "${WORKER_A:?}" "${WORKER_B:?}"
: "${TOTAL:=120}" "${MAX_FAIL_RATE_PCT:=3}" "${MAX_P95_MS:=5000}" "${MIN_LEAST_LOADED_VIA_PCT:=80}"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

apply_config() {
  local body
  body="$(python3 - <<'PY'
import json, os
alias = os.environ["LEAST_ALIAS"]
policies = {
    alias: {
        "strategy": "least_loaded",
        "candidates": [os.environ["WORKER_A"], os.environ["WORKER_B"]],
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

for i in $(seq 1 "${TOTAL}"); do
  export CI_I="$i"
  t0="$(python3 -c 'import time; print(int(time.time()*1000))')"
  resp="$(curl -sS -X POST "${BASE_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "X-Api-Key: ${USER_KEY}" \
    -H "X-User-Id: ci-least-user" \
    -d "$(python3 - <<'PY'
import json, os
print(json.dumps({
    "model": os.environ["LEAST_ALIAS"],
    "messages": [{"role": "user", "content": f"ci-least-{os.environ['CI_I']}"}],
    "stream": False,
}))
PY
)" || true)"
  t1="$(python3 -c 'import time; print(int(time.time()*1000))')"
  ms=$((t1 - t0))
  rf="$(mktemp)"
  printf '%s' "$resp" >"$rf"
  python3 - "$rf" "$ms" <<'PY' >>"$TMP"
import json, sys

path, ms_s = sys.argv[1], int(sys.argv[2])
with open(path, encoding="utf-8") as f:
    resp = f.read()
ok = 0
resolved = ""
via = ""
try:
    d = json.loads(resp)
    m = d.get("metadata") or {}
    resolved = str(m.get("resolved_model") or d.get("model") or "")
    via = str(m.get("resolved_via") or "")
    ok = 1
except Exception:
    pass
print(json.dumps({"ok": ok, "latency_ms": ms_s, "resolved": resolved, "via": via}))
PY
  rm -f "$rf"
done

python3 - "$TMP" "$MAX_FAIL_RATE_PCT" "$MAX_P95_MS" "$MIN_LEAST_LOADED_VIA_PCT" <<'PY'
import json, sys, math

path = sys.argv[1]
max_fail = float(sys.argv[2])
max_p95 = float(sys.argv[3])
min_via = float(sys.argv[4])

rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
ok = [r for r in rows if int(r.get("ok") or 0) == 1]
fail_pct = ((len(rows) - len(ok)) / len(rows) * 100) if rows else 100.0
lat = sorted([int(r["latency_ms"]) for r in ok])
p95 = lat[max(0, min(len(lat) - 1, math.ceil(len(lat) * 0.95) - 1))] if lat else 0.0
via_n = sum(1 for r in ok if "least_loaded" in (r.get("via") or ""))
via_pct = (via_n / len(ok) * 100) if ok else 0.0
checks = [
    ("fail_rate", fail_pct <= max_fail, f"{fail_pct:.2f}% <= {max_fail:.2f}%"),
    ("p95_latency", p95 <= max_p95, f"{p95:.0f} <= {max_p95:.0f} ms"),
    ("least_loaded_via", via_pct >= min_via, f"{via_pct:.2f}% >= {min_via:.2f}%"),
]
for name, okc, msg in checks:
    print(f"[{'PASS' if okc else 'FAIL'}] {name}: {msg}")
if not all(c[1] for c in checks):
    raise SystemExit(1)
PY
