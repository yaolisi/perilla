import json
from pathlib import Path

import pytest

from scripts.chaos_report_summary import (
    build_recommendations,
    build_parser,
    build_summary,
    load_report_points,
    to_markdown,
)


def _write_report(path: Path, failed: int, total: int, p95: float, s500: int):
    data = {
        "generated_at_ms": 1,
        "summary": {"failed": failed, "total": total},
        "results": [
            {
                "name": "sqlite_write_storm",
                "actual": "total=40, ok=40, net_err=0, 5xx=0, lock_like=0, p95_ms=50",
                "detail": {
                    "p95_ms": p95,
                    "errors": [],
                    "status_histogram": {"201": 40, "500": s500} if s500 else {"201": 40},
                },
            }
        ],
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_and_build_summary(tmp_path):
    _write_report(tmp_path / "a.json", failed=0, total=4, p95=10.0, s500=0)
    _write_report(tmp_path / "b.json", failed=1, total=4, p95=30.0, s500=2)

    points = load_report_points(tmp_path)
    assert len(points) == 2
    summary = build_summary(points)
    assert summary["reports"] == 2
    assert summary["failed_checks"] == 1
    assert summary["total_checks"] == 8
    assert summary["sqlite"]["total_5xx"] == 2
    assert summary["sqlite"]["avg_p95_ms"] == pytest.approx(20.0)


def test_build_summary_empty():
    out = build_summary([])
    assert out["reports"] == 0


def test_to_markdown_contains_key_metrics(tmp_path):
    _write_report(tmp_path / "a.json", failed=0, total=4, p95=11.0, s500=0)
    _write_report(tmp_path / "b.json", failed=1, total=4, p95=33.0, s500=1)
    points = load_report_points(tmp_path)
    summary = build_summary(points)
    md = to_markdown(summary)
    assert "# Chaos Stability Summary" in md
    assert "Failed rate" in md
    assert "SQLite total 5xx" in md
    assert "| file | failed_checks | total_checks |" in md


def test_to_markdown_top_failures_section():
    summary = {
        "reports": 2,
        "total_checks": 8,
        "failed_checks": 1,
        "failed_rate": 0.125,
        "sqlite": {"avg_p95_ms": 20.0, "total_5xx": 1, "total_net_err": 0},
        "series": [],
    }
    md = to_markdown(
        summary,
        top_failures={
            "grouped": {"sqlite_write_storm": 2, "trace_header_pollution": 1},
            "items": [
                {
                    "file": "a.json",
                    "name": "sqlite_write_storm",
                    "expected": "no 5xx",
                    "actual": "5xx=1",
                }
            ],
        },
    )
    assert "## Top Failures" in md
    assert "| check | count |" in md
    assert "sqlite_write_storm" in md
    assert "### Recent Failed Samples" in md


def test_build_recommendations_warns_on_high_failure():
    summary = {
        "failed_rate": 0.2,
        "sqlite": {"avg_p95_ms": 1200, "total_5xx": 3, "total_net_err": 2},
    }
    recs = build_recommendations(
        summary,
        fail_rate_warn=0.05,
        p95_warn_ms=800,
        net_err_warn=1,
    )
    text = "\n".join(recs)
    assert "失败率" in text
    assert "5xx" in text
    assert "p95" in text
    assert "网络异常" in text


def test_to_markdown_includes_suggested_actions():
    summary = {
        "reports": 1,
        "total_checks": 4,
        "failed_checks": 0,
        "failed_rate": 0.0,
        "sqlite": {"avg_p95_ms": 50.0, "total_5xx": 0, "total_net_err": 0},
        "series": [],
    }
    md = to_markdown(summary, recommendations=["建议 A", "建议 B"])
    assert "## Suggested Actions" in md
    assert "- 建议 A" in md


def test_parser_defaults_from_env(monkeypatch):
    monkeypatch.setenv("CHAOS_FAIL_RATE_WARN", "0.11")
    monkeypatch.setenv("CHAOS_P95_WARN_MS", "950")
    monkeypatch.setenv("CHAOS_NET_ERR_WARN", "3")
    parser = build_parser()
    args = parser.parse_args([])
    assert args.fail_rate_warn == pytest.approx(0.11)
    assert args.p95_warn_ms == pytest.approx(950.0)
    assert args.net_err_warn == 3


def test_parser_defaults_from_system_settings(monkeypatch):
    monkeypatch.delenv("CHAOS_FAIL_RATE_WARN", raising=False)
    monkeypatch.delenv("CHAOS_P95_WARN_MS", raising=False)
    monkeypatch.delenv("CHAOS_NET_ERR_WARN", raising=False)

    import scripts.chaos_report_summary as mod

    monkeypatch.setattr(
        mod,
        "_load_thresholds_from_system_settings",
        lambda: {"fail_rate_warn": 0.2, "p95_warn_ms": 1234, "net_err_warn": 7},
    )
    parser = mod.build_parser()
    args = parser.parse_args([])
    assert args.fail_rate_warn == pytest.approx(0.2)
    assert args.p95_warn_ms == pytest.approx(1234.0)
    assert args.net_err_warn == 7
