import argparse
import asyncio
import json
import httpx

from scripts.chaos_semi_integration import (
    _trace_pollution_check,
    _workflow_debug_not_found_check,
    _sqlite_write_storm_check,
    _resolve_report_file,
    run,
)


def test_trace_pollution_check_passes_on_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        req_id = request.headers.get("X-Request-Id")
        return httpx.Response(200, headers={"X-Trace-Id": req_id}, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    async def _run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await _trace_pollution_check(client)

    result = asyncio.run(_run())
    assert result.passed is True


def test_workflow_debug_not_found_passes():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/debug"):
            return httpx.Response(404, json={"detail": "Workflow not found"})
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    async def _run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await _workflow_debug_not_found_check(client, user_id="u1")

    result = asyncio.run(_run())
    assert result.passed is True


def test_sqlite_write_storm_detects_5xx_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v1/workflows":
            return httpx.Response(500, json={"detail": "boom"})
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    async def _run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await _sqlite_write_storm_check(client, user_id="u1", total_requests=5, concurrency=2)

    result = asyncio.run(_run())
    assert result.passed is False


def test_resolve_report_file_prefers_explicit_file(tmp_path):
    ns = argparse.Namespace(report_file=str(tmp_path / "x.json"), report_dir=str(tmp_path / "d"))
    out = _resolve_report_file(ns)
    assert out is not None
    assert out.name == "x.json"


def test_run_writes_report_file(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health":
            rid = request.headers.get("X-Request-Id", "r1")
            return httpx.Response(200, headers={"X-Trace-Id": rid}, json={"status": "healthy"})
        if request.method == "POST" and request.url.path == "/api/v1/workflows":
            return httpx.Response(201, json={"id": "wf-1"})
        if request.url.path.endswith("/debug"):
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)

    import scripts.chaos_semi_integration as mod

    orig_client = mod.httpx.AsyncClient

    class PatchedClient(orig_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    mod.httpx.AsyncClient = PatchedClient
    try:
        report_path = tmp_path / "report.json"
        ns = argparse.Namespace(
            base_url="http://test",
            user_id="u1",
            total_requests=5,
            concurrency=2,
            timeout_seconds=5.0,
            connect_timeout_seconds=1.0,
            report_dir=None,
            report_file=str(report_path),
        )
        code = asyncio.run(run(ns))
        assert code == 0
        assert report_path.exists()
        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert data["summary"]["failed"] == 0
    finally:
        mod.httpx.AsyncClient = orig_client


def test_run_writes_default_report_dir(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health":
            rid = request.headers.get("X-Request-Id", "r1")
            return httpx.Response(200, headers={"X-Trace-Id": rid}, json={"status": "healthy"})
        if request.method == "POST" and request.url.path == "/api/v1/workflows":
            return httpx.Response(201, json={"id": "wf-1"})
        if request.url.path.endswith("/debug"):
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)

    import scripts.chaos_semi_integration as mod

    orig_client = mod.httpx.AsyncClient

    class PatchedClient(orig_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    mod.httpx.AsyncClient = PatchedClient
    try:
        report_dir = tmp_path / "reports"
        ns = argparse.Namespace(
            base_url="http://test",
            user_id="u1",
            total_requests=3,
            concurrency=1,
            timeout_seconds=5.0,
            connect_timeout_seconds=1.0,
            report_dir=str(report_dir),
            report_file=None,
        )
        code = asyncio.run(run(ns))
        assert code == 0
        files = list(report_dir.glob("chaos-report-*.json"))
        assert files
    finally:
        mod.httpx.AsyncClient = orig_client
