from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

import requests


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _request(method: str, base_url: str, path: str, api_key: str | None, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key
    resp = requests.request(method=method, url=url, headers=headers, json=payload, timeout=20)
    _assert(resp.status_code < 500, f"{method} {path} failed with {resp.status_code}: {resp.text}")
    return {"status_code": resp.status_code, "body": resp.json()}


def run_smoke(base_url: str, api_key: str | None) -> None:
    # 1) 读取 KPI
    kpi_get = _request("GET", base_url, "/api/system/roadmap/kpis", api_key)
    _assert(kpi_get["status_code"] == 200, "roadmap kpis read should be 200")
    _assert(isinstance(kpi_get["body"].get("kpis"), dict), "kpis response must contain object")

    # 2) 更新 KPI
    kpi_post = _request(
        "POST",
        base_url,
        "/api/system/roadmap/kpis",
        api_key,
        payload={"availability_min": 0.99, "p99_latency_ms_max": 3000},
    )
    _assert(kpi_post["status_code"] == 200, "roadmap kpis update should be 200")
    _assert(kpi_post["body"].get("success") is True, "roadmap kpis update should return success=true")

    # 3) 写入质量指标
    quality_post = _request(
        "POST",
        base_url,
        "/api/system/roadmap/quality-metrics",
        api_key,
        payload={"rag_top5_recall": 0.88, "answer_usefulness": 0.9},
    )
    _assert(quality_post["status_code"] == 200, "quality metrics update should be 200")
    _assert(isinstance(quality_post["body"].get("quality_metrics"), dict), "quality metrics response invalid")

    # 4) 查询阶段状态
    phase_status = _request("GET", base_url, "/api/system/roadmap/phases/status", api_key)
    _assert(phase_status["status_code"] == 200, "phase status should be 200")
    body = phase_status["body"]
    _assert(isinstance(body.get("snapshot"), dict), "phase status missing snapshot")
    _assert(isinstance(body.get("north_star"), dict), "phase status missing north_star")
    _assert(isinstance(body.get("phase_gate"), dict), "phase status missing phase_gate")
    _assert(body.get("go_no_go") in {"go", "no_go"}, "phase status go_no_go invalid")
    _assert(isinstance(body.get("go_no_go_reasons"), list), "phase status go_no_go_reasons must be list")

    # 5) 创建月度复盘
    review_create = _request("POST", base_url, "/api/system/roadmap/monthly-review", api_key)
    _assert(review_create["status_code"] == 200, "monthly review create should be 200")
    review = review_create["body"].get("review", {})
    _assert(review.get("go_no_go") in {"go", "no_go"}, "monthly review go_no_go invalid")

    # 6) 查询月度复盘列表
    review_list = _request("GET", base_url, "/api/system/roadmap/monthly-review?limit=3", api_key)
    _assert(review_list["status_code"] == 200, "monthly review list should be 200")
    list_body = review_list["body"]
    _assert(isinstance(list_body.get("items"), list), "monthly review list items must be list")
    _assert(isinstance(list_body.get("meta"), dict), "monthly review list meta must be object")
    meta = list_body.get("meta", {})
    _assert(isinstance(meta.get("applied_filters"), dict), "monthly review list filters invalid")
    _assert(meta.get("returned_order") == "newest_first", "monthly review list order invalid")
    _assert(isinstance(meta.get("total_before_limit"), int), "monthly review list total_before_limit invalid")
    _assert(isinstance(meta.get("has_more"), bool), "monthly review list has_more invalid")
    _assert(meta.get("next_offset") is None or isinstance(meta.get("next_offset"), int), "monthly review list next_offset invalid")
    _assert(meta.get("prev_offset") is None or isinstance(meta.get("prev_offset"), int), "monthly review list prev_offset invalid")
    _assert(isinstance(meta.get("page_window"), dict), "monthly review list page_window invalid")
    _assert(isinstance(meta.get("page_window", {}).get("start"), int), "monthly review list page_window.start invalid")
    _assert(
        isinstance(meta.get("page_window", {}).get("end_exclusive"), int),
        "monthly review list page_window.end_exclusive invalid",
    )

    print(
        json.dumps(
            {
                "ok": True,
                "phase_gate_score": body.get("phase_gate", {}).get("score"),
                "north_star_score": body.get("north_star", {}).get("score"),
                "latest_go_no_go": review.get("go_no_go"),
            },
            ensure_ascii=False,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Roadmap API acceptance smoke script")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--api-key", default=None, help="Optional X-Api-Key value")
    args = parser.parse_args()

    try:
        run_smoke(args.base_url, args.api_key)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
