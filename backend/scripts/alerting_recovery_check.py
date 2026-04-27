#!/usr/bin/env python3
"""
Alert recovery checker for OpenVitamin.

Use this after running alerting_drill.py to verify alerts return to resolved state.
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Iterable

try:
    import httpx
except ImportError:
    print("需要安装 httpx: pip install httpx")
    raise SystemExit(1)


def _active_alert_names(alertmanager_url: str) -> set[str]:
    r = httpx.get(f"{alertmanager_url.rstrip('/')}/api/v2/alerts", timeout=15.0)
    r.raise_for_status()
    data = r.json()
    names: set[str] = set()
    for item in data:
        status = (item.get("status") or {}).get("state")
        if status != "active":
            continue
        labels = item.get("labels") or {}
        name = labels.get("alertname")
        if isinstance(name, str) and name.strip():
            names.add(name.strip())
    return names


def _wait_until_resolved(
    alertmanager_url: str,
    targets: Iterable[str],
    timeout_seconds: int,
    interval_seconds: int,
) -> tuple[bool, set[str]]:
    target_set = {x.strip() for x in targets if x and x.strip()}
    deadline = time.time() + max(1, timeout_seconds)
    while time.time() <= deadline:
        active = _active_alert_names(alertmanager_url)
        still_firing = target_set & active
        print(f"[poll] active={sorted(active) if active else []}, waiting_resolve={sorted(still_firing)}")
        if not still_firing:
            return True, set()
        time.sleep(max(1, interval_seconds))
    active = _active_alert_names(alertmanager_url)
    return False, (target_set & active)


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenVitamin 告警恢复检查脚本")
    parser.add_argument("--alertmanager-url", default="http://localhost:9093", help="Alertmanager 地址")
    parser.add_argument(
        "--alerts",
        default="OpenVitaminInferenceErrorRateHigh,OpenVitaminAgentFailureRateHigh,OpenVitaminInferenceP95TooHigh",
        help="要观察恢复的告警名（逗号分隔）",
    )
    parser.add_argument("--timeout-seconds", type=int, default=900, help="最长等待秒数（默认 15 分钟）")
    parser.add_argument("--poll-interval-seconds", type=int, default=15, help="轮询间隔秒数")
    args = parser.parse_args()

    target_alerts = [x.strip() for x in args.alerts.split(",") if x.strip()]
    if not target_alerts:
        print("未提供待观察告警名")
        return 1

    print(f"检查告警恢复: {target_alerts}")
    try:
        ok, remaining = _wait_until_resolved(
            alertmanager_url=args.alertmanager_url,
            targets=target_alerts,
            timeout_seconds=args.timeout_seconds,
            interval_seconds=args.poll_interval_seconds,
        )
    except Exception as e:
        print(f"查询 Alertmanager 失败: {e}")
        return 1

    if ok:
        print("恢复验证通过：目标告警均已从 active 状态恢复。")
        return 0
    print(f"恢复验证失败：超时后仍在 active 的告警: {sorted(remaining)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
