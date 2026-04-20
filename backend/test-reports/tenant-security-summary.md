# Tenant Security Regression Summary

- started_at: 2026-04-20T02:40:18Z

## Suite
- tests/test_workflow_tenant_api_isolation.py
- tests/test_workflow_tenant_guard.py
- tests/test_production_readiness_baseline.py::test_tenant_enforcement_protected_path
- tests/test_production_readiness_baseline.py::test_apply_production_security_defaults_in_non_debug
- duration_seconds: 1 ⚠️
- result: passed (slow)
- finished_at: 2026-04-20T02:40:19Z
- performance_warning: exceeded 0s threshold

## Local Reproduce
```bash
backend/scripts/test_tenant_security_regression.sh
```
