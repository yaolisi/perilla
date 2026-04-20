"""
Chaos 报告汇总器：聚合 backend/data/chaos-reports/*.json。
输出失败率、sqlite 写压测 p95、5xx 计数趋势。
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SETTING_KEY_FAIL_RATE = "chaosFailRateWarn"
SETTING_KEY_P95_MS = "chaosP95WarnMs"
SETTING_KEY_NET_ERR = "chaosNetErrWarn"


@dataclass
class ReportPoint:
    file: str
    generated_at_ms: Optional[int]
    failed_checks: int
    total_checks: int
    sqlite_p95_ms: Optional[float]
    sqlite_5xx: int
    sqlite_net_err: int
    sqlite_total: Optional[int]


def _extract_sqlite_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    sqlite_item = next((r for r in results if r.get("name") == "sqlite_write_storm"), None)
    if not sqlite_item:
        return {"p95_ms": None, "s5xx": 0, "net_err": 0, "total": None}

    detail = sqlite_item.get("detail") or {}
    status_hist = detail.get("status_histogram") or {}
    s5xx = 0
    for k, v in status_hist.items():
        try:
            code = int(k)
        except Exception:
            continue
        if code >= 500:
            s5xx += int(v)

    return {
        "p95_ms": detail.get("p95_ms"),
        "s5xx": s5xx,
        "net_err": len(detail.get("errors") or []),
        "total": _parse_total_from_actual(sqlite_item.get("actual", "")),
    }


def _parse_total_from_actual(actual: str) -> Optional[int]:
    for part in (actual or "").split(","):
        p = part.strip()
        if p.startswith("total="):
            value = p.split("=", 1)[1].strip()
            try:
                return int(value)
            except Exception:
                return None
    return None


def load_report_points(report_dir: Path) -> List[ReportPoint]:
    files = sorted(report_dir.glob("*.json"))
    points: List[ReportPoint] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        results = data.get("results") or []
        total = int(data.get("summary", {}).get("total", len(results)))
        failed = int(data.get("summary", {}).get("failed", 0))
        sqlite = _extract_sqlite_metrics(results)
        points.append(
            ReportPoint(
                file=f.name,
                generated_at_ms=data.get("generated_at_ms"),
                failed_checks=failed,
                total_checks=total,
                sqlite_p95_ms=sqlite["p95_ms"],
                sqlite_5xx=sqlite["s5xx"],
                sqlite_net_err=sqlite["net_err"],
                sqlite_total=sqlite["total"],
            )
        )
    return points


def build_summary(points: List[ReportPoint]) -> Dict[str, Any]:
    n = len(points)
    if n == 0:
        return {"reports": 0, "message": "no report files found"}

    total_checks = sum(p.total_checks for p in points)
    total_failed = sum(p.failed_checks for p in points)
    fail_rate = (total_failed / total_checks) if total_checks else 0.0

    p95_values = [p.sqlite_p95_ms for p in points if p.sqlite_p95_ms is not None]
    avg_p95 = round(sum(p95_values) / len(p95_values), 2) if p95_values else None

    total_5xx = sum(p.sqlite_5xx for p in points)
    total_net_err = sum(p.sqlite_net_err for p in points)

    return {
        "reports": n,
        "failed_checks": total_failed,
        "total_checks": total_checks,
        "failed_rate": round(fail_rate, 4),
        "sqlite": {
            "avg_p95_ms": avg_p95,
            "total_5xx": total_5xx,
            "total_net_err": total_net_err,
        },
        "series": [asdict(p) for p in points],
    }


def _collect_top_failures(
    report_dir: Path,
    top_n: int = 5,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    files = sorted(report_dir.glob("*.json"), reverse=True)
    grouped: Dict[str, int] = {}
    items: List[Dict[str, Any]] = []
    # 倒序：优先最近文件
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for r in data.get("results") or []:
            if bool(r.get("passed", False)):
                continue
            name = str(r.get("name", "unknown"))
            grouped[name] = grouped.get(name, 0) + 1
            items.append(
                {
                    "file": f.name,
                    "name": name,
                    "expected": r.get("expected"),
                    "actual": r.get("actual"),
                }
            )
    return items[: max(1, top_n)], grouped


def _append_overview(lines: List[str], summary: Dict[str, Any]) -> None:
    lines.append("## Overview")
    lines.append(f"- Reports: {summary.get('reports')}")
    lines.append(f"- Total checks: {summary.get('total_checks')}")
    lines.append(f"- Failed checks: {summary.get('failed_checks')}")
    lines.append(f"- Failed rate: {summary.get('failed_rate')}")
    sqlite = summary.get("sqlite") or {}
    lines.append(f"- SQLite avg p95(ms): {sqlite.get('avg_p95_ms')}")
    lines.append(f"- SQLite total 5xx: {sqlite.get('total_5xx')}")
    lines.append(f"- SQLite total net errors: {sqlite.get('total_net_err')}")


def _append_recent_series(lines: List[str], summary: Dict[str, Any]) -> None:
    lines.append("## Recent Series")
    lines.append("| file | failed_checks | total_checks | sqlite_p95_ms | sqlite_5xx | sqlite_net_err |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    series = summary.get("series") or []
    for item in series[-20:]:
        lines.append(
            f"| {item.get('file')} | {item.get('failed_checks')} | {item.get('total_checks')} | "
            f"{item.get('sqlite_p95_ms')} | {item.get('sqlite_5xx')} | {item.get('sqlite_net_err')} |"
        )


def _append_top_failures(lines: List[str], top_failures: Dict[str, Any]) -> None:
    lines.append("## Top Failures")
    grouped = top_failures.get("grouped") or {}
    if grouped:
        lines.append("| check | count |")
        lines.append("|---|---:|")
        for k, v in sorted(grouped.items(), key=lambda kv: kv[1], reverse=True):
            lines.append(f"| {k} | {v} |")
    else:
        lines.append("- No failed checks found in report set.")

    details = top_failures.get("items") or []
    if details:
        lines.append("")
        lines.append("### Recent Failed Samples")
        lines.append("| file | check | expected | actual |")
        lines.append("|---|---|---|---|")
        for d in details:
            lines.append(
                f"| {d.get('file')} | {d.get('name')} | "
                f"{str(d.get('expected', '')).replace('|', '/')} | "
                f"{str(d.get('actual', '')).replace('|', '/')} |"
            )


def build_recommendations(
    summary: Dict[str, Any],
    *,
    fail_rate_warn: float,
    p95_warn_ms: float,
    net_err_warn: int,
) -> List[str]:
    recs: List[str] = []
    failed_rate = float(summary.get("failed_rate", 0.0) or 0.0)
    sqlite = summary.get("sqlite") or {}
    p95 = sqlite.get("avg_p95_ms")
    total_5xx = int(sqlite.get("total_5xx", 0) or 0)
    total_net_err = int(sqlite.get("total_net_err", 0) or 0)

    if failed_rate >= fail_rate_warn:
        recs.append(
            f"失败率 {failed_rate:.4f} >= 阈值 {fail_rate_warn:.4f}：建议先降并发（chaos total/concurrency），并检查最近失败样本中的主导检查项。"
        )
    if total_5xx > 0:
        recs.append("检测到 SQLite 写路径 5xx：建议排查 DB 锁竞争、连接池与事务边界（重点看 workflow create 路径）。")
    if p95 is not None and float(p95) >= p95_warn_ms:
        recs.append(
            f"SQLite 平均 p95={p95}ms >= 阈值 {p95_warn_ms}ms：建议降低并发、拉长压测间隔，并检查宿主机 IO/CPU 抖动。"
        )
    if total_net_err >= net_err_warn:
        recs.append(
            f"网络异常累计 {total_net_err} >= 阈值 {net_err_warn}：建议先确认服务存活与端口可达，再检查反向代理超时配置。"
        )
    if not recs:
        recs.append("当前指标未触发告警阈值，建议继续按固定频率执行混沌测试并观察趋势。")
    return recs


def to_markdown(
    summary: Dict[str, Any],
    top_failures: Optional[Dict[str, Any]] = None,
    recommendations: Optional[List[str]] = None,
) -> str:
    if summary.get("reports", 0) == 0:
        return "# Chaos Stability Summary\n\nNo report files found.\n"

    lines: List[str] = []
    lines.append("# Chaos Stability Summary")
    lines.append("")
    _append_overview(lines, summary)
    lines.append("")
    _append_recent_series(lines, summary)
    if top_failures:
        lines.append("")
        _append_top_failures(lines, top_failures)
    if recommendations:
        lines.append("")
        lines.append("## Suggested Actions")
        for r in recommendations:
            lines.append(f"- {r}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _safe_float(val: Any, default: float) -> float:
    try:
        return float(val)
    except Exception:
        return float(default)


def _safe_int(val: Any, default: int) -> int:
    try:
        return int(val)
    except Exception:
        return int(default)


def _load_thresholds_from_system_settings() -> Dict[str, Any]:
    try:
        from core.system.settings_store import get_system_settings_store

        store = get_system_settings_store()
        return {
            "fail_rate_warn": store.get_setting(SETTING_KEY_FAIL_RATE, None),
            "p95_warn_ms": store.get_setting(SETTING_KEY_P95_MS, None),
            "net_err_warn": store.get_setting(SETTING_KEY_NET_ERR, None),
        }
    except Exception:
        return {"fail_rate_warn": None, "p95_warn_ms": None, "net_err_warn": None}


def build_parser() -> argparse.ArgumentParser:
    settings_defaults = _load_thresholds_from_system_settings()
    fail_rate_default = _safe_float(
        os.getenv("CHAOS_FAIL_RATE_WARN", settings_defaults.get("fail_rate_warn", 0.05)),
        0.05,
    )
    p95_warn_default = _safe_float(
        os.getenv("CHAOS_P95_WARN_MS", settings_defaults.get("p95_warn_ms", 800)),
        800.0,
    )
    net_err_warn_default = _safe_int(
        os.getenv("CHAOS_NET_ERR_WARN", settings_defaults.get("net_err_warn", 1)),
        1,
    )

    p = argparse.ArgumentParser(description="Summarize chaos report JSON files")
    p.add_argument("--report-dir", default="data/chaos-reports")
    p.add_argument("--output-file", default=None)
    p.add_argument("--format", choices=["json", "markdown"], default="json")
    p.add_argument("--top-failures", type=int, default=5, help="Markdown 中展示最近失败样本数")
    p.add_argument("--fail-rate-warn", type=float, default=fail_rate_default)
    p.add_argument("--p95-warn-ms", type=float, default=p95_warn_default)
    p.add_argument("--net-err-warn", type=int, default=net_err_warn_default)
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    report_dir = Path(args.report_dir).expanduser().resolve()
    points = load_report_points(report_dir)
    summary = build_summary(points)
    if args.format == "markdown":
        items, grouped = _collect_top_failures(report_dir, top_n=args.top_failures)
        recs = build_recommendations(
            summary,
            fail_rate_warn=args.fail_rate_warn,
            p95_warn_ms=args.p95_warn_ms,
            net_err_warn=args.net_err_warn,
        )
        out = to_markdown(
            summary,
            top_failures={"items": items, "grouped": grouped},
            recommendations=recs,
        )
    else:
        out = json.dumps(summary, ensure_ascii=False, indent=2)
    print(out)

    if args.output_file:
        out_file = Path(args.output_file).expanduser().resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(out, encoding="utf-8")
        print(f"\n[chaos] summary saved: {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
