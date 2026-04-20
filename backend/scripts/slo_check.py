"""
SLO checker from chaos summary JSON.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def evaluate(summary: dict, fail_rate_slo: float, p95_slo_ms: float) -> dict:
    failed_rate = float(summary.get("failed_rate", 0.0) or 0.0)
    p95 = summary.get("sqlite", {}).get("avg_p95_ms")
    p95_v = float(p95) if p95 is not None else 0.0
    return {
        "failed_rate": failed_rate,
        "failed_rate_ok": failed_rate <= fail_rate_slo,
        "sqlite_avg_p95_ms": p95_v,
        "sqlite_p95_ok": p95_v <= p95_slo_ms,
        "overall_ok": (failed_rate <= fail_rate_slo) and (p95_v <= p95_slo_ms),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--summary-file", required=True)
    p.add_argument("--fail-rate-slo", type=float, default=0.02)
    p.add_argument("--p95-slo-ms", type=float, default=500)
    args = p.parse_args()

    data = json.loads(Path(args.summary_file).read_text(encoding="utf-8"))
    out = evaluate(data, args.fail_rate_slo, args.p95_slo_ms)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["overall_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
