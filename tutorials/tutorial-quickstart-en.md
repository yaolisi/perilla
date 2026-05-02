# perilla 10-Minute Quickstart

**Goal**: from zero to *running services + health checks + CSRF write path + optional security regressions* in about ten minutes.

For the full narrative and troubleshooting, see **[tutorial.md](tutorial.md)** and **[tutorial-index.md](tutorial-index.md)**.  
For beginner onboarding and debugging playbooks, also see **[tutorial-beginner-playbook.md](tutorial-beginner-playbook.md)** and **[tutorial-debug-playbook.md](tutorial-debug-playbook.md)**.

---

## What you will do

1. Install dependencies and start backend/frontend (Conda env aligned with repo scripts).  
2. Hit the health endpoints.  
3. Prove the CSRF double-submit path for a mutating request.  
4. (Recommended) Run the tenant + security regression shell scripts.  

---

## Prerequisites

- Python 3.11+, Node.js 18+, Conda (recommended)  
- Current working directory is the **repository root** (clone directory is often named `perilla`)

```bash
python --version
node --version
```

---

## Install (first time only)

The backend launcher expects conda env **`ai-inference-platform`** (see `run-backend.sh`).

```bash
conda create -n ai-inference-platform python=3.11 -y
cd backend
conda run -n ai-inference-platform pip install -r requirements.txt
cd ../frontend && npm install && cd ..
```

---

## Start services

**Recommended (repo root)**

```bash
./run-all.sh
```

**Or split terminals**

```bash
./run-backend.sh
./run-frontend.sh
```

Defaults: backend `http://127.0.0.1:8000`, frontend `http://localhost:5173`.

---

## Health checks (required)

```bash
curl -s http://127.0.0.1:8000/api/health | jq .
curl -s http://127.0.0.1:8000/api/health/live | jq .
curl -s http://127.0.0.1:8000/api/health/ready | jq .
```

All should return HTTP 200 with healthy status payloads.

---

## CSRF mutating request (required)

Fetch token and cookie (requires [ripgrep](https://github.com/BurntSushi/ripgrep) `rg`):

```bash
curl -i -s -c /tmp/ov_cookie.txt http://127.0.0.1:8000/api/health | tee /tmp/ov_headers.txt
export CSRF_TOKEN="$(rg "X-CSRF-Token:" /tmp/ov_headers.txt -i | awk '{print $2}' | tr -d '\r')"
echo "$CSRF_TOKEN"
```

Example write (adjust key/tenant for your `.env`):

```bash
curl -s -X POST "http://127.0.0.1:8000/api/system/config" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: admin-key" \
  -H "X-Tenant-Id: tenant-dev" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -b /tmp/ov_cookie.txt \
  -d '{"runtimeAutoReleaseEnabled": true}' | jq .
```

Missing or mismatched token → **403**.

---

## Security regressions (highly recommended)

From the repository root:

```bash
backend/scripts/test_tenant_security_regression.sh
scripts/acceptance/run_security_regression.sh
```

Pass criteria: exit code `0` and summary output indicating success.

Reports:

- `backend/test-reports/tenant-security-summary.md`  
- `test-reports/security-regression-summary.md`  

---

## Optional: trigger CI workflows

GitHub Actions: `tenant-security-regression`, `security-regression`.  
Input: `slow_threshold_seconds` (positive integer).

---

## Fast troubleshooting

| Symptom | Action |
|---------|--------|
| `403 CSRF token validation failed` | `GET /api/health` first; resend with cookie + `X-CSRF-Token` |
| **400** `tenant id required for protected path` | Path under tenant enforcement prefixes (**`backend/middleware/tenant_paths.py`**); send `-H "X-Tenant-Id: ..."` — see **tutorial.md §10.4** |
| Workflow **403/404** | Check `X-Tenant-Id`, namespace, key–tenant binding |
| **429** | Lower request rate or tune rate limits |
| **409** idempotency | Same key requires same body; change key if body changes |
| Execution **PAUSED** | `approval` node pending; approve or reject |

---

## Next docs

- [tutorial-beginner-playbook.md](tutorial-beginner-playbook.md) — beginner hands-on onboarding path  
- [tutorial-debug-playbook.md](tutorial-debug-playbook.md) — practical debugging and rollback triggers  
- [tutorial.md](tutorial.md) — full tutorial  
- [tutorial-index.md](tutorial-index.md) — index and command cheatsheet  
- [tutorial-security-baseline.md](tutorial-security-baseline.md) — security baseline  
