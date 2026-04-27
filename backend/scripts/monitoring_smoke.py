#!/usr/bin/env python3
"""
Monitoring stack smoke check:
- Prometheus ready and has targets endpoint
- Alertmanager healthy API
- Grafana health API
"""
from __future__ import annotations

import argparse
import sys

try:
    import httpx
except ImportError:
    print("需要安装 httpx: pip install httpx")
    raise SystemExit(1)


def _check(url: str, expect_status: int = 200) -> tuple[bool, str]:
    try:
        r = httpx.get(url, timeout=10.0)
        if r.status_code != expect_status:
            return False, f"{url} status={r.status_code}"
        return True, f"{url} OK"
    except Exception as e:
        return False, f"{url} failed: {e}"


def main() -> int:
    p = argparse.ArgumentParser(description="OpenVitamin monitoring smoke checks")
    p.add_argument("--prometheus-url", default="http://127.0.0.1:9090")
    p.add_argument("--alertmanager-url", default="http://127.0.0.1:9093")
    p.add_argument("--grafana-url", default="http://127.0.0.1:3000")
    args = p.parse_args()

    checks = [
        (f"{args.prometheus_url.rstrip('/')}/-/ready", 200),
        (f"{args.prometheus_url.rstrip('/')}/api/v1/targets", 200),
        (f"{args.alertmanager_url.rstrip('/')}/-/healthy", 200),
        (f"{args.alertmanager_url.rstrip('/')}/api/v2/status", 200),
        (f"{args.grafana_url.rstrip('/')}/api/health", 200),
    ]

    ok = True
    for url, status in checks:
        passed, msg = _check(url, expect_status=status)
        print(msg)
        ok = ok and passed

    if ok:
        print("Monitoring smoke check passed.")
        return 0
    print("Monitoring smoke check failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
