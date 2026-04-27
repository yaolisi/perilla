# OpenVitamin: Security and Logic Review Hints (Archived)

Outcomes of a **static architecture / focused code review**. Complements [tutorial-security-baseline.md](tutorial-security-baseline.md) (MUST rules); **not** a penetration test or full production sign-off.

---

## 1. Threat model

The product defaults to **local-first / trusted-network** deployments. If you expose the gateway to the **internet** or **shared multi-tenant hosts**, you must tighten configuration explicitly—developer-friendly defaults may conflict with strong isolation expectations.

---

## 2. High-priority hints

### 2.1 RBAC and missing API keys

- With RBAC enabled, requests **without** `X-Api-Key` fall back to **`rbac_default_role` (default: `operator`)**.  
- **Implication**: omitting keys does **not** automatically mean read-only. For public-adjacent deployments, prefer **`RBAC_DEFAULT_ROLE=viewer`** and grant admin/operator via keys.

### 2.2 `RBAC_ENABLED=false` (debug-style)

- When RBAC is off, middleware treats the platform role as **Operator**—do not rely on this on shared or public networks.

### 2.3 Dangerous defaults vs production guardrails (`DEBUG=false`)

- Production guardrails block risky combos (see `tutorial-security-baseline.md`).  
- If `SECURITY_GUARDRAILS_STRICT=false` or `DEBUG=true`, guardrails/auto-hardening may **not** apply as intended.

### 2.4 Control-plane consistency (example)

- **`GET /api/system/browse-directory`** triggers server-side folder-picker behavior; treat it as a **sensitive/debug** capability and restrict exposure (network ACL, localhost-only, or admin-only), depending on deployment.

---

## 3. Medium-priority hints

### 3.1 Tenancy and `X-Tenant-Id`

- Tenant id is client-supplied; isolation depends on enforcement, API-key binding, and **tenant-scoped data access**. Continue IDOR reviews per API surface.

### 3.2 CSRF vs non-browser clients

- Double-submit CSRF primarily protects browser cookie flows. Automations should document how they authenticate (keys, paths, CSRF behavior).

### 3.3 Front-end identity headers (e.g. `X-User-Id`)

- Values can be spoofed; use API keys / RBAC / real sessions for authorization—not headers from local storage alone.

### 3.4 Dynamic SQL identifiers

- Ensure dynamic table names / identifiers are **never** derived from untrusted user input.

---

## 4. Strengths already in place (summary)

- Production fail-fast guardrails + strict mode.  
- Layered controls: RBAC, tenant, scope, audit, rate limit, trace, CSRF, XSS baseline.  
- Timing-safe CSRF token comparison.

---

## 5. Recommended actions

1. Internet/shared hosting: enable RBAC, set **default role to viewer**, grant elevated roles via keys; review write paths on `system`, backup, models, workflows.  
2. Re-evaluate debug-style endpoints for exposure and required roles.  
3. Deployment checklist: `DEBUG`, `CORS_ALLOWED_ORIGINS`, `FILE_READ_ALLOWED_ROOTS`, `TOOL_NET_*`, `CSRF_COOKIE_SECURE` on HTTPS.  
4. Backend audit: any route using `X-User-Id` must not treat it as proof of identity.

---

## 6. Related docs

> In this standalone pack, the tutorials below live in the same folder as this file (`tutorials/`).

- [tutorial-security-baseline.md](tutorial-security-baseline.md)  
- [tutorial-ops-checklist.md](tutorial-ops-checklist.md)  
- [tutorial-index.md](tutorial-index.md)  
- [README_EN.md](../README_EN.md)
