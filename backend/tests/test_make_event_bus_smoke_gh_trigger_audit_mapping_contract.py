from __future__ import annotations

from pathlib import Path

from scripts.event_bus_smoke_gh_trigger_audit_arg_map import (
    GH_TRIGGER_AUDIT_ARG_MAPPINGS,
    GH_TRIGGER_AUDIT_BASE_ARG_SPECS,
    GH_TRIGGER_AUDIT_EXPECTED_ARG_SPECS,
    GH_TRIGGER_AUDIT_THRESHOLD_ARG_SPECS,
    GH_TRIGGER_AUDIT_VALIDATE_PAYLOAD_ARG_BINDINGS,
)


def test_makefile_validate_target_contains_all_declared_mappings() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    anchor = "event-bus-smoke-validate-gh-trigger-inputs-audit:"
    next_anchor = "\nevent-bus-smoke-gh-strict-watch:"
    start = makefile.find(anchor)
    assert start >= 0, "target not found: event-bus-smoke-validate-gh-trigger-inputs-audit"
    end = makefile.find(next_anchor, start)
    assert end > start, "failed to slice target body"
    section = makefile[start:end]
    for _flag, make_pattern in GH_TRIGGER_AUDIT_ARG_MAPPINGS:
        assert make_pattern in section, f"missing mapping snippet in Makefile: {make_pattern}"


def test_validator_cli_exposes_all_declared_flags() -> None:
    script_content = Path("backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py").read_text(encoding="utf-8")
    for flag, _make_pattern in GH_TRIGGER_AUDIT_ARG_MAPPINGS:
        if (
            flag.startswith("--expected-")
            or flag in {"--max-duration-ms", "--max-age-ms"}
            or flag in {"--input", "--payload-sha256-mode", "--schema-mode"}
        ):
            continue
        assert f'"{flag}"' in script_content, f"validator CLI flag missing: {flag}"


def test_expected_arg_specs_cover_all_expected_flags_in_mapping() -> None:
    expected_flags_from_mapping = {
        flag for flag, _pattern in GH_TRIGGER_AUDIT_ARG_MAPPINGS if flag.startswith("--expected-")
    }
    expected_flags_from_specs = {flag for flag, _help, _default, _type, _choices in GH_TRIGGER_AUDIT_EXPECTED_ARG_SPECS}
    assert expected_flags_from_specs == expected_flags_from_mapping


def test_validator_uses_shared_expected_arg_builder() -> None:
    script_content = Path("backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py").read_text(encoding="utf-8")
    assert "add_expected_field_arguments(parser)" in script_content


def test_base_arg_specs_cover_all_base_flags_in_mapping() -> None:
    base_flags_from_mapping = {
        flag for flag, _pattern in GH_TRIGGER_AUDIT_ARG_MAPPINGS if flag in {"--input", "--payload-sha256-mode", "--schema-mode"}
    }
    base_flags_from_specs = {flag for flag, _help, _default, _type, _choices, _required in GH_TRIGGER_AUDIT_BASE_ARG_SPECS}
    assert base_flags_from_specs == base_flags_from_mapping


def test_validator_uses_shared_base_arg_builder() -> None:
    script_content = Path("backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py").read_text(encoding="utf-8")
    assert "add_base_arguments(parser)" in script_content


def test_threshold_arg_specs_cover_all_threshold_flags_in_mapping() -> None:
    threshold_flags_from_mapping = {
        flag for flag, _pattern in GH_TRIGGER_AUDIT_ARG_MAPPINGS if flag in {"--max-duration-ms", "--max-age-ms"}
    }
    threshold_flags_from_specs = {flag for flag, _help, _default, _type, _choices in GH_TRIGGER_AUDIT_THRESHOLD_ARG_SPECS}
    assert threshold_flags_from_specs == threshold_flags_from_mapping


def test_validator_uses_shared_threshold_arg_builder() -> None:
    script_content = Path("backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py").read_text(encoding="utf-8")
    assert "add_threshold_arguments(parser)" in script_content


def test_validate_payload_arg_bindings_cover_expected_flags_and_runtime_fields() -> None:
    expected_flag_names = {flag.removeprefix("--").replace("-", "_") for flag, _help, _default, _type, _choices in GH_TRIGGER_AUDIT_EXPECTED_ARG_SPECS}
    threshold_flag_names = {
        flag.removeprefix("--").replace("-", "_")
        for flag, _help, _default, _type, _choices in GH_TRIGGER_AUDIT_THRESHOLD_ARG_SPECS
    }
    expected_attrs = expected_flag_names | threshold_flag_names | {"payload_sha256_mode", "schema_mode"}
    actual_attrs = {arg_attr for _payload_param, arg_attr in GH_TRIGGER_AUDIT_VALIDATE_PAYLOAD_ARG_BINDINGS}
    assert expected_attrs <= actual_attrs


def test_validator_uses_shared_validate_payload_kwargs_builder() -> None:
    script_content = Path("backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py").read_text(encoding="utf-8")
    assert "build_validate_payload_kwargs(args)" in script_content
