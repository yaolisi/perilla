from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.getenv("EVENT_BUS_SMOKE_BASE_URL") or not os.getenv("EVENT_BUS_SMOKE_ADMIN_TOKEN"),
    reason="Set EVENT_BUS_SMOKE_BASE_URL and EVENT_BUS_SMOKE_ADMIN_TOKEN to enable external smoke test.",
)
def test_event_bus_dlq_external_smoke_script() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "backend" / "scripts" / "event_bus_dlq_smoke.py"
    cmd = [
        sys.executable,
        str(script),
        "--base-url",
        str(os.getenv("EVENT_BUS_SMOKE_BASE_URL")),
        "--admin-token",
        str(os.getenv("EVENT_BUS_SMOKE_ADMIN_TOKEN")),
    ]
    event_type = os.getenv("EVENT_BUS_SMOKE_EVENT_TYPE")
    if event_type:
        cmd.extend(["--event-type", event_type])
    limit = os.getenv("EVENT_BUS_SMOKE_LIMIT")
    if limit:
        cmd.extend(["--limit", limit])

    result = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(
            "External smoke script failed.\n"
            f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        )
