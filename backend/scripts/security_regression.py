"""
Security regression checks for protected backend APIs.

Usage:
  python backend/scripts/security_regression.py \
    --base http://127.0.0.1:8000 \
    --api-key "your-admin-key" \
    --tenant-id default
"""

from __future__ import annotations

import argparse
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import requests


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: Any


def _write_file(path: str, size_bytes: int, fill: bytes) -> None:
    p = Path(path)
    with p.open("wb") as f:
        f.write(fill * size_bytes)


def run_checks(base: str, api_key: str, tenant_id: str, fail_fast: bool = False) -> list[CheckResult]:
    results: list[CheckResult] = []

    def add(name: str, ok: bool, detail: Any) -> None:
        results.append(CheckResult(name=name, ok=ok, detail=detail))
        if fail_fast and not ok:
            raise RuntimeError(f"fail-fast: {name} failed: {detail}")

    # Prime CSRF token from safe endpoint, then echo as cookie+header for write methods.
    health_resp = requests.get(f"{base}/api/health", timeout=10)
    csrf_token = health_resp.headers.get("X-CSRF-Token") or "manual-csrf-token"
    csrf_cookie = f"csrf_token={csrf_token}"
    admin_headers = {"X-Api-Key": api_key, "X-Tenant-Id": tenant_id}
    write_headers = {
        **admin_headers,
        "X-CSRF-Token": csrf_token,
        "Cookie": csrf_cookie,
    }

    r = requests.get(f"{base}/api/agents", timeout=10)
    add("agents_no_key_blocked", r.status_code in (401, 403), r.status_code)

    r = requests.get(
        f"{base}/api/agents",
        headers={"X-Api-Key": "wrong-key", "X-Tenant-Id": tenant_id},
        timeout=10,
    )
    add("agents_wrong_key_403", r.status_code == 403, r.status_code)

    r = requests.get(f"{base}/api/agents", headers=admin_headers, timeout=10)
    add("agents_admin_ok", r.status_code == 200, r.status_code)

    r = requests.get(f"{base}/api/system/config", timeout=10)
    add("system_no_key_blocked", r.status_code in (401, 403), r.status_code)

    r = requests.get(f"{base}/api/system/config", headers=admin_headers, timeout=10)
    add("system_admin_ok", r.status_code == 200, f"{r.status_code} {r.text[:120]}")

    r = requests.post(f"{base}/api/models/scan", headers=admin_headers, timeout=20)
    add("models_scan_no_csrf_403", r.status_code == 403 and "CSRF" in r.text, r.status_code)

    r = requests.post(f"{base}/api/models/scan", headers=write_headers, timeout=30)
    add("models_scan_with_csrf_ok", r.status_code == 200, r.status_code)

    r = requests.post(
        f"{base}/api/skills/builtin_shell.run/execute",
        headers=write_headers,
        json={"inputs": {"command": "echo hi"}},
        timeout=20,
    )
    add(
        "dangerous_skill_blocked",
        r.status_code == 403 and "dangerous" in r.text.lower(),
        f"{r.status_code} {r.text[:120]}",
    )

    # HTTP hardening check by direct policy behavior via skill endpoint.
    r = requests.get(f"{base}/api/skills", headers=admin_headers, timeout=20)
    http_skill_id = None
    if r.status_code == 200:
        skill_ids = [x.get("id") for x in r.json().get("data", []) if isinstance(x, dict)]
        for candidate in (
            "builtin_http.request",
            "builtin_http.get",
            "builtin_net.http_request",
            "builtin_http.fetch",
        ):
            if candidate in skill_ids:
                http_skill_id = candidate
                break
    if http_skill_id:
        r = requests.post(
            f"{base}/api/skills/{http_skill_id}/execute",
            headers=write_headers,
            json={"inputs": {"url": "http://example.com", "method": "GET"}},
            timeout=20,
        )
        text = r.text.lower()
        hardened = ("allowlist" in text) or ("net.http" in text) or ("permission denied" in text)
        add("http_outbound_hardened", hardened, f"{r.status_code} {r.text[:120]}")
    else:
        add("http_outbound_hardened", False, "http skill not found")

    # Upload controls check: 413 (size limit), 429 (concurrency limit).
    r = requests.get(f"{base}/api/models", headers=admin_headers, timeout=20)
    model_id = ""
    if r.status_code == 200 and r.json().get("data"):
        model_id = r.json()["data"][0].get("id", "")
    if not model_id:
        add("upload_tests_ready", False, "no model id available")
        return results

    create_payload = {
        "name": "security-upload-test",
        "description": "upload guard regression test",
        "model_id": model_id,
        "system_prompt": "You are helpful.",
        "enabled_skills": [],
        "tool_ids": [],
        "rag_ids": [],
        "max_steps": 2,
        "temperature": 0.1,
        "execution_mode": "legacy",
    }
    r = requests.post(f"{base}/api/agents", headers=write_headers, json=create_payload, timeout=20)
    if r.status_code != 200:
        add("upload_tests_ready", False, f"agent create failed: {r.status_code} {r.text[:120]}")
        return results

    agent_id = r.json().get("agent_id", "")
    add("upload_tests_ready", bool(agent_id), agent_id or "missing agent_id")
    if not agent_id:
        return results

    big_file = "/tmp/ov_big_21mb.bin"
    _write_file(big_file, 21 * 1024 * 1024, b"0")
    data = {"messages": json.dumps([{"role": "user", "content": "upload"}]), "session_id": ""}
    with Path(big_file).open("rb") as fh:
        files = [("files", ("big.bin", fh, "application/octet-stream"))]
        r = requests.post(
            f"{base}/api/agents/{agent_id}/run/with-files",
            headers=write_headers,
            data=data,
            files=files,
            timeout=120,
        )
    add("upload_413_size_limit", r.status_code == 413, f"{r.status_code} {r.text[:120]}")

    small_file = "/tmp/ov_small_10mb.bin"
    _write_file(small_file, 10 * 1024 * 1024, b"1")
    status_codes: list[int] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        payload = {
            "messages": json.dumps([{"role": "user", "content": f"upload {index}"}]),
            "session_id": "",
        }
        with Path(small_file).open("rb") as fh:
            files = [("files", (f"s{index}.bin", fh, "application/octet-stream"))]
            try:
                rr = requests.post(
                    f"{base}/api/agents/{agent_id}/run/with-files",
                    headers=write_headers,
                    data=payload,
                    files=files,
                    timeout=120,
                )
                code = rr.status_code
            except Exception:
                code = -1
        with lock:
            status_codes.append(code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    add("upload_429_concurrency_best_effort", 429 in status_codes, status_codes)

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run backend security regression checks.")
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--api-key", required=True, help="Admin API key")
    parser.add_argument("--tenant-id", default="default", help="Tenant ID header value")
    parser.add_argument(
        "--json-output",
        default="",
        help="Optional path to write JSON report (for CI artifacts)",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop execution on first failed check",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print summary only (suppress per-check JSON output)",
    )
    parser.add_argument(
        "--junit-output",
        default="",
        help="Optional path to write JUnit XML report",
    )
    parser.add_argument(
        "--suite-name",
        default="security_regression",
        help="Suite name used in JUnit XML report",
    )
    args = parser.parse_args()

    try:
        results = run_checks(args.base.rstrip("/"), args.api_key, args.tenant_id, fail_fast=args.fail_fast)
    except RuntimeError as e:
        # Preserve partial results generated before fail-fast trigger
        # by rerunning in non-fail-fast mode only when no output is available is expensive;
        # instead emit a minimal failure report for CI.
        report = {
            "base": args.base.rstrip("/"),
            "tenant_id": args.tenant_id,
            "passed": 0,
            "total": 0,
            "ok": False,
            "error": str(e),
            "results": [],
        }
        if args.json_output:
            out_path = Path(args.json_output).expanduser()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.junit_output:
            junit_path = Path(args.junit_output).expanduser()
            junit_path.parent.mkdir(parents=True, exist_ok=True)
            testsuite = ET.Element(
                "testsuite",
                name=args.suite_name,
                tests="1",
                failures="1",
            )
            testcase = ET.SubElement(testsuite, "testcase", classname=args.suite_name, name="fail_fast")
            failure = ET.SubElement(testcase, "failure", message="fail-fast")
            failure.text = str(e)
            ET.ElementTree(testsuite).write(junit_path, encoding="utf-8", xml_declaration=True)
        if not args.quiet:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        print("Summary: fail-fast terminated on first failure")
        return 1

    ok_count = sum(1 for x in results if x.ok)
    failed = [x for x in results if not x.ok]
    report = {
        "base": args.base.rstrip("/"),
        "tenant_id": args.tenant_id,
        "passed": ok_count,
        "total": len(results),
        "ok": len(failed) == 0,
        "results": [x.__dict__ for x in results],
    }

    if args.json_output:
        out_path = Path(args.json_output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.junit_output:
        junit_path = Path(args.junit_output).expanduser()
        junit_path.parent.mkdir(parents=True, exist_ok=True)
        testsuite = ET.Element(
            "testsuite",
            name=args.suite_name,
            tests=str(len(results)),
            failures=str(len(failed)),
        )
        for item in results:
            case = ET.SubElement(
                testsuite,
                "testcase",
                classname=args.suite_name,
                name=item.name,
            )
            if not item.ok:
                failure = ET.SubElement(case, "failure", message="check failed")
                failure.text = str(item.detail)
        ET.ElementTree(testsuite).write(junit_path, encoding="utf-8", xml_declaration=True)

    if not args.quiet:
        print(json.dumps(report["results"], ensure_ascii=False, indent=2))
    print(f"\nSummary: {ok_count}/{len(results)} checks passed")
    if failed:
        print("Failed checks:")
        for f in failed:
            print(f"- {f.name}: {f.detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
