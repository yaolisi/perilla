#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, List

from scripts.event_bus_smoke_gh_constants import ALLOWED_GH_RUN_CONCLUSIONS, GH_TRIGGER_AUDIT_SOURCE
from scripts.event_bus_smoke_json_integrity import canonical_json_sha256
from scripts.event_bus_smoke_gh_trigger_audit_payload import (
    build_initial_trigger_inputs_payload,
    finalize_trigger_inputs_payload,
)


def _run(command: List[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip() or f"command failed: {' '.join(command)}")
    return result


def _latest_run_id(workflow: str) -> str:
    result = _run(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            workflow,
            "--limit",
            "1",
            "--json",
            "databaseId",
            "--jq",
            ".[0].databaseId",
        ]
    )
    return (result.stdout or "").strip()


def _atomic_write_text(target: Path, text: str, encoding: str = "utf-8") -> None:
    tmp_path = target.with_name(f"{target.name}.tmp-{int(time.time() * 1000)}")
    try:
        tmp_path.write_text(text, encoding=encoding)
        tmp_path.replace(target)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _write_trigger_inputs_audit_file(path: str, payload: dict[str, Any]) -> None:
    core_payload = dict(payload)
    core_payload.setdefault("schema_version", 1)
    core_payload.setdefault("generated_at_ms", int(time.time() * 1000))
    core_payload.setdefault("source", GH_TRIGGER_AUDIT_SOURCE)
    core_payload["payload_sha256"] = canonical_json_sha256(core_payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(target, json.dumps(core_payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger and watch latest EventBus smoke workflow run")
    parser.add_argument("--workflow", required=True, help="Workflow file name, e.g. event-bus-dlq-smoke.yml")
    parser.add_argument("--mode", required=True, choices=["strict", "compatible"], help="Summary schema mode")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--limit", required=True)
    parser.add_argument("--expected-schema-version", required=True)
    parser.add_argument("--expected-summary-schema-version", required=True)
    parser.add_argument("--payload-sha256-mode", required=True, choices=["strict", "off"])
    parser.add_argument("--result-file-stale-threshold-ms", required=True)
    parser.add_argument("--file-suffix", default="")
    parser.add_argument("--trigger-inputs-audit-file", default="")
    parser.add_argument("--expected-conclusion", default="success", choices=list(ALLOWED_GH_RUN_CONCLUSIONS))
    args = parser.parse_args()
    generated_at_ms = int(time.time() * 1000)
    trigger_inputs = build_initial_trigger_inputs_payload(vars(args), generated_at_ms=generated_at_ms)

    try:
        print(f"Trigger inputs JSON: {json.dumps(trigger_inputs, ensure_ascii=False, sort_keys=True)}")
        if args.trigger_inputs_audit_file:
            _write_trigger_inputs_audit_file(args.trigger_inputs_audit_file, trigger_inputs)
            print(f"Trigger inputs audit file: {args.trigger_inputs_audit_file}")
        before_id = _latest_run_id(args.workflow)
        _run(
            [
                "gh",
                "workflow",
                "run",
                args.workflow,
                "-f",
                f"base_url={args.base_url}",
                "-f",
                f"event_type={args.event_type}",
                "-f",
                f"limit={args.limit}",
                "-f",
                f"expected_schema_version={args.expected_schema_version}",
                "-f",
                f"expected_summary_schema_version={args.expected_summary_schema_version}",
                "-f",
                f"summary_schema_mode={args.mode}",
                "-f",
                f"payload_sha256_mode={args.payload_sha256_mode}",
                "-f",
                f"result_file_stale_threshold_ms={args.result_file_stale_threshold_ms}",
                "-f",
                f"file_suffix={args.file_suffix}",
            ]
        )
        new_id = _latest_run_id(args.workflow)
        if not new_id or new_id == "null":
            print(f"No run found after trigger for workflow: {args.workflow}")
            return 2
        if before_id == new_id:
            print(f"Latest run id unchanged after trigger ({new_id}). Please retry.")
            return 2
        print(f"Watching triggered run id: {new_id}")
        watch = subprocess.run(["gh", "run", "watch", new_id])
        run_url = _run(["gh", "run", "view", new_id, "--json", "url", "--jq", ".url"]).stdout.strip()
        conclusion = _run(["gh", "run", "view", new_id, "--json", "conclusion", "--jq", ".conclusion"]).stdout.strip()
        if args.trigger_inputs_audit_file:
            finalized_payload = finalize_trigger_inputs_payload(
                trigger_inputs,
                run_id=str(new_id),
                run_url=run_url,
                conclusion=conclusion,
                completed_at_ms=int(time.time() * 1000),
            )
            _write_trigger_inputs_audit_file(args.trigger_inputs_audit_file, finalized_payload)
        print(f"Run URL: {run_url}")
        print(f"Conclusion: {conclusion}")
        return watch.returncode
    except RuntimeError as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
