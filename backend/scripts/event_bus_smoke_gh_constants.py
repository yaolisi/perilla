from __future__ import annotations

GH_TRIGGER_AUDIT_SOURCE = "event_bus_smoke_gh_trigger_watch.py"

ALLOWED_GH_RUN_CONCLUSIONS = (
    "success",
    "failure",
    "cancelled",
    "skipped",
    "timed_out",
    "action_required",
    "neutral",
    "stale",
)

ALLOWED_GH_RUN_CONCLUSIONS_SET = frozenset(ALLOWED_GH_RUN_CONCLUSIONS)
