#!/usr/bin/env python3
"""
Alerting drill script for OpenVitamin monitoring stack.

Goals:
1. Generate controlled inference failures to raise error-rate signals.
2. Verify /metrics exposes expected business metrics.
3. Optionally poll Alertmanager API for active alerts.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from typing import Optional

try:
    import httpx
except ImportError:
    print("需要安装 httpx: pip install httpx")
    raise SystemExit(1)


def _metric_value(metrics_text: str, metric_name: str) -> Optional[float]:
    pattern = re.compile(rf"^{re.escape(metric_name)}(?:\{{.*\}})?\s+([0-9eE+.\-]+)$", re.MULTILINE)
    total = 0.0
    found = False
    for m in pattern.finditer(metrics_text):
        found = True
        total += float(m.group(1))
    return total if found else None


def _fetch_metrics(base_url: str) -> str:
    r = httpx.get(f"{base_url.rstrip('/')}/metrics", timeout=15.0)
    r.raise_for_status()
    return r.text


def _inject_inference_errors(base_url: str, rounds: int, concurrency: int) -> tuple[int, int]:
    # Use invalid model alias to trigger gateway routing/adapter failure path.
    payload = {
        "model": "__drill_invalid_model__",
        "messages": [{"role": "user", "content": "trigger monitoring drill"}],
        "stream": False,
        "max_tokens": 16,
    }
    client = httpx.Client(timeout=20.0)
    sent = 0
    failed_http = 0
    for _ in range(rounds):
        batch = []
        for _i in range(concurrency):
            batch.append(client.build_request("POST", f"{base_url.rstrip('/')}/v1/chat/completions", json=payload))
        for req in batch:
            sent += 1
            try:
                resp = client.send(req)
                if resp.status_code >= 400:
                    failed_http += 1
            except Exception:
                failed_http += 1
    client.close()
    return sent, failed_http


def _check_alertmanager(alertmanager_url: str) -> list[str]:
    r = httpx.get(f"{alertmanager_url.rstrip('/')}/api/v2/alerts", timeout=15.0)
    r.raise_for_status()
    data = r.json()
    names: list[str] = []
    for item in data:
        labels = item.get("labels") or {}
        name = labels.get("alertname")
        if isinstance(name, str):
            names.append(name)
    return sorted(set(names))


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenVitamin 告警演练脚本")
    parser.add_argument("--backend-url", default="http://localhost:8000", help="后端地址")
    parser.add_argument("--alertmanager-url", default="http://localhost:9093", help="Alertmanager 地址")
    parser.add_argument("--rounds", type=int, default=30, help="压测轮数")
    parser.add_argument("--concurrency", type=int, default=4, help="每轮并发请求数")
    parser.add_argument("--wait-seconds", type=int, default=45, help="注入后等待 Prometheus 抓取秒数")
    parser.add_argument("--check-alertmanager", action="store_true", help="是否调用 Alertmanager API 查看活跃告警")
    args = parser.parse_args()

    backend = args.backend_url.rstrip("/")
    print(f"[1/4] 读取演练前指标: {backend}/metrics")
    before = _fetch_metrics(backend)
    err_before = _metric_value(before, "openvitamin_inference_errors_total") or 0.0
    cnt_before = _metric_value(before, "openvitamin_inference_latency_seconds_count") or 0.0
    print(f"  - openvitamin_inference_errors_total = {err_before}")
    print(f"  - openvitamin_inference_latency_seconds_count = {cnt_before}")

    print(f"[2/4] 注入错误请求: rounds={args.rounds}, concurrency={args.concurrency}")
    sent, failed_http = _inject_inference_errors(backend, args.rounds, args.concurrency)
    print(f"  - sent={sent}, http_error_or_exception={failed_http}")

    print(f"[3/4] 等待 {args.wait_seconds}s 让 Prometheus 抓取新样本")
    time.sleep(max(1, args.wait_seconds))
    after = _fetch_metrics(backend)
    err_after = _metric_value(after, "openvitamin_inference_errors_total") or 0.0
    cnt_after = _metric_value(after, "openvitamin_inference_latency_seconds_count") or 0.0
    err_delta = err_after - err_before
    cnt_delta = cnt_after - cnt_before
    print(f"  - openvitamin_inference_errors_total = {err_after} (delta={err_delta})")
    print(f"  - openvitamin_inference_latency_seconds_count = {cnt_after} (delta={cnt_delta})")

    ok = err_delta > 0 and cnt_delta > 0
    if not ok:
        print("  ! 指标增长不符合预期，请检查 /metrics 或请求路径是否经过 InferenceGateway。")

    if args.check_alertmanager:
        print(f"[4/4] 查询 Alertmanager 活跃告警: {args.alertmanager_url.rstrip('/')}/api/v2/alerts")
        try:
            active = _check_alertmanager(args.alertmanager_url)
            if active:
                print(f"  - active alerts: {', '.join(active)}")
            else:
                print("  - 当前无活跃告警（可能尚未达到 for 窗口）")
        except Exception as e:
            print(f"  ! Alertmanager 查询失败: {e}")
            return 1
    else:
        print("[4/4] 跳过 Alertmanager API 查询（可加 --check-alertmanager）")

    print("")
    if ok:
        print("演练完成：业务指标已增长。若告警规则阈值满足，稍后应收到邮件/Slack 通知。")
        return 0
    print("演练完成：但指标未按预期增长，请检查监控链路。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
