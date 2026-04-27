#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.event_bus_smoke_contract_guard_summary import summarize_guard_log


def main() -> int:
    parser = argparse.ArgumentParser(description="Print EventBus contract guard status as JSON")
    parser.add_argument(
        "--input",
        default="event-bus-smoke-contract-guard.log",
        help="Path to contract guard log file",
    )
    args = parser.parse_args()
    status, seen = summarize_guard_log(args.input)
    payload = {
        "log_file": args.input,
        "log_file_exists": Path(args.input).exists(),
        "sections_seen": seen,
        "status": status,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
