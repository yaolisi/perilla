from __future__ import annotations

from pathlib import Path


def test_event_bus_smoke_workflow_contains_contract_guard_step() -> None:
    workflow = Path(".github/workflows/event-bus-dlq-smoke.yml").read_text(encoding="utf-8")
    assert "Run smoke contract guard gate" in workflow
    assert "make event-bus-smoke-contract-guard" in workflow
    assert 'tee "${EVENT_BUS_SMOKE_CONTRACT_GUARD_LOG_FILE}"' in workflow
    assert "EVENT_BUS_SMOKE_CONTRACT_GUARD_LOG_FILE" in workflow
    assert "contract_guard_sections_seen" in workflow
    assert "contract_guard_status" in workflow
    assert "sections_seen_from_status" in workflow
