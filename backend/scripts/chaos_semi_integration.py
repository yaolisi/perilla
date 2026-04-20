"""
半集成混沌测试（需后端服务已启动）。

目标：
1) 验证 Trace Header 污染输入回退逻辑；
2) 对 SQLite 写路径做并发压力注入（以 workflow create 为载体）；
3) 验证 workflow debug 不存在资源时不会 500；
4) 输出失败矩阵（expected/actual/pass）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx


@dataclass
class CheckResult:
    name: str
    expected: str
    actual: str
    passed: bool
    detail: Optional[Dict[str, Any]] = None


def _ts_ms() -> int:
    return int(time.time() * 1000)


async def _single_health_check(client: httpx.AsyncClient) -> CheckResult:
    url = "/api/health"
    try:
        r = await client.get(url)
        passed = r.status_code == 200
        return CheckResult(
            name="baseline_health",
            expected="status_code == 200",
            actual=f"status_code == {r.status_code}",
            passed=passed,
            detail={"body": r.json() if r.headers.get("content-type", "").startswith("application/json") else None},
        )
    except Exception as e:
        return CheckResult(
            name="baseline_health",
            expected="status_code == 200",
            actual=f"exception: {e}",
            passed=False,
        )


async def _trace_pollution_check(client: httpx.AsyncClient) -> CheckResult:
    url = "/api/health"
    req_id = f"chaos-{uuid.uuid4().hex[:12]}"
    polluted = "bad/trace\\id?*"
    try:
        r = await client.get(url, headers={"X-Request-Id": req_id, "X-Trace-Id": polluted})
        out = r.headers.get("X-Trace-Id")
        passed = r.status_code == 200 and out == req_id
        return CheckResult(
            name="trace_header_pollution",
            expected="200 and response X-Trace-Id == X-Request-Id fallback",
            actual=f"status={r.status_code}, x-trace-id={out}",
            passed=passed,
        )
    except Exception as e:
        return CheckResult(
            name="trace_header_pollution",
            expected="200 and response X-Trace-Id == X-Request-Id fallback",
            actual=f"exception: {e}",
            passed=False,
        )


async def _workflow_create_once(client: httpx.AsyncClient, user_id: str, i: int) -> Dict[str, Any]:
    name = f"chaos-wf-{_ts_ms()}-{i}-{uuid.uuid4().hex[:6]}"
    payload = {"namespace": "chaos", "name": name, "description": "chaos injection workflow"}
    headers = {"X-User-Id": user_id}
    t0 = time.perf_counter()
    try:
        r = await client.post("/api/v1/workflows", json=payload, headers=headers)
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return {"status": r.status_code, "latency_ms": elapsed, "ok": True}
    except Exception as e:
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return {"status": None, "latency_ms": elapsed, "ok": False, "error": str(e)}


async def _sqlite_write_storm_check(
    client: httpx.AsyncClient,
    user_id: str,
    total_requests: int,
    concurrency: int,
) -> CheckResult:
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _run_one(idx: int) -> Dict[str, Any]:
        async with sem:
            return await _workflow_create_once(client, user_id, idx)

    rows = await asyncio.gather(*[_run_one(i) for i in range(total_requests)])

    statuses = [x["status"] for x in rows if x.get("status") is not None]
    latencies = [x["latency_ms"] for x in rows if x.get("ok")]
    errs = [x for x in rows if not x.get("ok")]
    s5xx = [s for s in statuses if s >= 500]
    locked_like = [s for s in statuses if s in (409, 423, 429)]

    if len(latencies) >= 20:
        p95 = round(statistics.quantiles(latencies, n=20)[18], 2)
    elif latencies:
        p95 = max(latencies)
    else:
        p95 = None
    # 失败判定：存在网络异常、或出现任意 5xx
    passed = (len(errs) == 0) and (len(s5xx) == 0)
    actual = (
        f"total={total_requests}, ok={len(statuses)}, net_err={len(errs)}, "
        f"5xx={len(s5xx)}, lock_like={len(locked_like)}, p95_ms={p95}"
    )
    return CheckResult(
        name="sqlite_write_storm",
        expected="no network exception and no 5xx under concurrent workflow writes",
        actual=actual,
        passed=passed,
        detail={
            "status_histogram": {str(s): statuses.count(s) for s in sorted(set(statuses))},
            "errors": errs[:5],
            "p95_ms": p95,
        },
    )


async def _workflow_debug_not_found_check(client: httpx.AsyncClient, user_id: str) -> CheckResult:
    headers = {"X-User-Id": user_id}
    url = "/api/v1/workflows/not-exist/executions/not-exist/debug?event_limit=20"
    try:
        r = await client.get(url, headers=headers)
        passed = r.status_code == 404
        return CheckResult(
            name="workflow_debug_not_found",
            expected="status_code == 404 (not 5xx)",
            actual=f"status_code == {r.status_code}",
            passed=passed,
        )
    except Exception as e:
        return CheckResult(
            name="workflow_debug_not_found",
            expected="status_code == 404 (not 5xx)",
            actual=f"exception: {e}",
            passed=False,
        )


async def run(args: argparse.Namespace) -> int:
    timeout = httpx.Timeout(args.timeout_seconds, connect=args.connect_timeout_seconds)
    results: List[CheckResult] = []
    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=timeout) as client:
        results.append(await _single_health_check(client))
        results.append(await _trace_pollution_check(client))
        results.append(
            await _sqlite_write_storm_check(
                client,
                user_id=args.user_id,
                total_requests=args.total_requests,
                concurrency=args.concurrency,
            )
        )
        results.append(await _workflow_debug_not_found_check(client, user_id=args.user_id))

    failed = [r for r in results if not r.passed]
    report = {
        "base_url": args.base_url,
        "generated_at_ms": _ts_ms(),
        "summary": {"total": len(results), "passed": len(results) - len(failed), "failed": len(failed)},
        "results": [asdict(r) for r in results],
        "failure_criteria": [
            "baseline_health != 200",
            "trace_header_pollution 未回退到 request_id",
            "sqlite_write_storm 出现网络异常或 5xx",
            "workflow_debug_not_found 不是 404（或异常）",
        ],
    }

    out = json.dumps(report, ensure_ascii=False, indent=2)
    print(out)

    report_file = _resolve_report_file(args)
    if report_file:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(out, encoding="utf-8")
        print(f"\n[chaos] report saved: {report_file}")
    return 1 if failed else 0


def _resolve_report_file(args: argparse.Namespace) -> Optional[Path]:
    if getattr(args, "report_file", None):
        return Path(args.report_file).expanduser().resolve()

    report_dir = getattr(args, "report_dir", None)
    if not report_dir:
        return None
    d = Path(report_dir).expanduser().resolve()
    ts = time.strftime("%Y%m%d-%H%M%S")
    filename = f"chaos-report-{ts}.json"
    return d / filename


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="OpenVitamin semi-integration chaos test")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--user-id", default="chaos-user")
    p.add_argument("--total-requests", type=int, default=40)
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--timeout-seconds", type=float, default=8.0)
    p.add_argument("--connect-timeout-seconds", type=float, default=2.0)
    p.add_argument(
        "--report-dir",
        default="data/chaos-reports",
        help="目录模式：自动生成报告文件名（默认 data/chaos-reports）",
    )
    p.add_argument(
        "--report-file",
        default=None,
        help="文件模式：显式指定报告文件路径（优先级高于 report-dir）",
    )
    return p


if __name__ == "__main__":
    parser = build_parser()
    ns = parser.parse_args()
    raise SystemExit(asyncio.run(run(ns)))
