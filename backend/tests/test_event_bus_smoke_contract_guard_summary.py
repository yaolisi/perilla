from __future__ import annotations

from pathlib import Path

from scripts.event_bus_smoke_contract_guard_summary import (
    GUARD_SECTIONS,
    parse_guard_log_text,
    sections_seen_from_status,
    summarize_guard_log,
)


def test_parse_guard_log_text_marks_seen_sections() -> None:
    text = "\n".join(
        [
            "[guard] preflight",
            "random text",
            "[guard] payload",
            "[guard] workflow",
        ]
    )
    status = parse_guard_log_text(text)
    assert status["preflight"] == "seen"
    assert status["payload"] == "seen"
    assert status["workflow"] == "seen"
    assert status["mapping"] == "missing"
    assert status["validator"] == "missing"


def test_summarize_guard_log_returns_missing_for_absent_file(tmp_path: Path) -> None:
    status, seen = summarize_guard_log(str(tmp_path / "missing.log"))
    assert status == dict.fromkeys(GUARD_SECTIONS, "missing")
    assert seen == []


def test_summarize_guard_log_reads_existing_file(tmp_path: Path) -> None:
    log = tmp_path / "guard.log"
    log.write_text("[guard] preflight\n[guard] mapping\n", encoding="utf-8")
    status, seen = summarize_guard_log(str(log))
    assert status["preflight"] == "seen"
    assert status["mapping"] == "seen"
    assert status["payload"] == "missing"
    assert seen == ["preflight", "mapping"]


def test_sections_seen_from_status_uses_declared_section_order() -> None:
    status = {
        "preflight": "seen",
        "mapping": "missing",
        "payload": "seen",
        "validator": "missing",
        "workflow": "seen",
    }
    assert sections_seen_from_status(status) == ["preflight", "payload", "workflow"]
