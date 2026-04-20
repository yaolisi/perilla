# OpenVitamin Enhanced 10-Minute Quickstart

> Goal: help first-time users get from zero to "running + basic security validation" in about 10 minutes.

---

## 0. What you will complete

1. Install dependencies and start backend/frontend  
2. Verify health probes  
3. Validate CSRF write path  
4. Run tenant/security regression scripts

---

## 1. Prerequisites

- Python 3.11+
- Node.js 18+
- Conda (recommended)
- Repository cloned and current directory is project root (standalone distribution is usually `openvitamin_enhanced_docker`)

Quick check:

```bash
python --version
node --version
```

---

## 2. Install dependencies (first time only)

Backend:

```bash
cd backend
pip install -r requirements.txt
cd ..
```

Frontend:

```bash
cd frontend
npm install
cd ..
```

---

## 3. Start services

Terminal A (backend):

```bash
cd backend
python main.py
```

Terminal B (frontend):

```bash
cd frontend
npm run dev
```

---

## 4. Health checks (must pass)

```bash
curl -s http://127.0.0.1:8000/api/health | jq .
curl -s http://127.0.0.1:8000/api/health/live | jq .
curl -s http://127.0.0.1:8000/api/health/ready | jq .
```

Expected: all endpoints return HTTP 200 and healthy status fields.

---

## 5. Security check: CSRF (must verify)

Get token (also saves cookie):

```bash
curl -i -s -c /tmp/ov_cookie.txt http://127.0.0.1:8000/api/health | tee /tmp/ov_headers.txt
export CSRF_TOKEN="$(rg "X-CSRF-Token:" /tmp/ov_headers.txt -i | awk '{print $2}' | tr -d '\r')"
echo "$CSRF_TOKEN"
```

Send one write request (example: system config):

```bash
curl -s -X POST "http://127.0.0.1:8000/api/system/config" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: admin-key" \
  -H "X-Tenant-Id: tenant-dev" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -b /tmp/ov_cookie.txt \
  -d '{"runtimeAutoReleaseEnabled": true}' | jq .
```

Expected behavior:

- with valid cookie + header token: request is processed (subject to RBAC)
- missing/mismatched token: `403`

---

## 6. Run security regressions

From project root:

```bash
backend/scripts/test_tenant_security_regression.sh
scripts/acceptance/run_security_regression.sh
```

Pass criteria:

- exit code is `0`
- output contains `passed`

Reports:

- `backend/test-reports/tenant-security-summary.md`
- `test-reports/security-regression-summary.md`

---

## 7. Optional: trigger CI manually

In GitHub Actions, run:

- `tenant-security-regression`
- `security-regression`

Optional input:

- `slow_threshold_seconds` (must be a positive integer, e.g. `20`)

Defaults:

- pull_request: 20s
- main/master push: 30s

Results are available in Step Summary and artifacts.

---

## 8. Fast troubleshooting

- `403 CSRF token validation failed`  
  - call `GET /api/health` first, then send write request with cookie + `X-CSRF-Token`
- `404/403 workflow`  
  - check `X-Tenant-Id`, namespace, and key-tenant bindings
- `429`  
  - reduce request rate or tune rate-limit settings

---

## 9. Next docs

- Full tutorial: `tutorial.md`
- Index: `tutorial-index.md`
- Security baseline: `tutorial-security-baseline.md`
