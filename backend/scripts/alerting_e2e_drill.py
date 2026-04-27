#!/usr/bin/env python3
"""
One-command E2E alerting drill:
1) trigger errors (alerting_drill),
2) wait for alerts to appear,
3) verify alerts recover (alerting_recovery_check).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def _run(cmd: list[str]) -> int:
    print(f"$ {' '.join(cmd)}")
    proc = subprocess.run(cmd)
    return int(proc.returncode)


def main() -> int:
    p = argparse.ArgumentParser(description="OpenVitamin 一键告警闭环演练")
    p.add_argument("--backend-url", default="http://localhost:8000")
    p.add_argument("--alertmanager-url", default="http://localhost:9093")
    p.add_argument("--rounds", type=int, default=30)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--scrape-wait-seconds", type=int, default=45)
    p.add_argument("--recovery-timeout-seconds", type=int, default=900)
    p.add_argument("--poll-interval-seconds", type=int, default=15)
    p.add_argument(
        "--alerts",
        default="OpenVitaminInferenceErrorRateHigh,OpenVitaminAgentFailureRateHigh,OpenVitaminInferenceP95TooHigh",
        help="逗号分隔的目标告警名",
    )
    args = p.parse_args()

    python = sys.executable
    drill_script = str(SCRIPT_DIR / "alerting_drill.py")
    recover_script = str(SCRIPT_DIR / "alerting_recovery_check.py")

    print("=== Step 1/2: 触发告警演练 ===")
    rc = _run(
        [
            python,
            drill_script,
            "--backend-url",
            args.backend_url,
            "--alertmanager-url",
            args.alertmanager_url,
            "--rounds",
            str(args.rounds),
            "--concurrency",
            str(args.concurrency),
            "--wait-seconds",
            str(args.scrape_wait_seconds),
            "--check-alertmanager",
        ]
    )
    if rc != 0:
        print("告警触发阶段失败，终止。")
        return rc

    print("=== Step 2/2: 检查告警恢复 ===")
    rc = _run(
        [
            python,
            recover_script,
            "--alertmanager-url",
            args.alertmanager_url,
            "--alerts",
            args.alerts,
            "--timeout-seconds",
            str(args.recovery_timeout_seconds),
            "--poll-interval-seconds",
            str(args.poll_interval_seconds),
        ]
    )
    if rc != 0:
        print("恢复检查阶段失败。")
        return rc

    print("告警闭环演练完成：触发与恢复均通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
