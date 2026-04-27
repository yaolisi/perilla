from __future__ import annotations

import argparse
from typing import Final

# Single source of truth for Makefile -> validator CLI mappings.
# make_pattern is asserted as a raw snippet in Makefile target body.
GH_TRIGGER_AUDIT_ARG_MAPPINGS: Final[tuple[tuple[str, str], ...]] = (
    ("--input", '--input "$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE)"'),
    ("--payload-sha256-mode", '--payload-sha256-mode "$(EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE)"'),
    ("--expected-schema-version", '--expected-schema-version "$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_VERSION)"'),
    ("--schema-mode", '--schema-mode "$(EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_MODE)"'),
    ("--expected-trigger-mode", '--expected-trigger-mode "$(EVENT_BUS_SMOKE_GH_TRIGGER_MODE)"'),
    ("--expected-workflow", '--expected-workflow "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_WORKFLOW)"'),
    ("--expected-base-url", '--expected-base-url "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_BASE_URL)"'),
    ("--expected-event-type", '--expected-event-type "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_EVENT_TYPE)"'),
    ("--expected-limit", '--expected-limit "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_LIMIT)"'),
    (
        "--expected-result-file-stale-threshold-ms",
        '--expected-result-file-stale-threshold-ms "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_STALE_THRESHOLD_MS)"',
    ),
    (
        "--expected-summary-schema-version",
        '--expected-summary-schema-version "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_SUMMARY_SCHEMA_VERSION)"',
    ),
    (
        "--expected-result-schema-version",
        '--expected-result-schema-version "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_RESULT_SCHEMA_VERSION)"',
    ),
    ("--expected-file-suffix", '--expected-file-suffix "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_FILE_SUFFIX)"'),
    ("--expected-conclusion", '--expected-conclusion "$(EVENT_BUS_SMOKE_GH_TRIGGER_EXPECTED_CONCLUSION)"'),
    ("--max-duration-ms", '--max-duration-ms "$(EVENT_BUS_SMOKE_GH_TRIGGER_MAX_DURATION_MS)"'),
    ("--max-age-ms", '--max-age-ms "$(EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS)"'),
)

GH_TRIGGER_AUDIT_BASE_ARG_SPECS: Final[
    tuple[tuple[str, str, object, type | None, tuple[str, ...] | None, bool], ...]
] = (
    ("--input", "Path to trigger inputs audit json file", None, None, None, True),
    (
        "--payload-sha256-mode",
        "Payload sha256 validation mode: strict(validate) or off(skip)",
        "strict",
        None,
        ("strict", "off"),
        False,
    ),
    (
        "--schema-mode",
        "Schema validation mode: strict(==) or compatible(<=)",
        "strict",
        None,
        ("strict", "compatible"),
        False,
    ),
)

# Shared validator argparse specs for expected-* options.
# Tuple shape: (flag, help_text, default, type, choices)
GH_TRIGGER_AUDIT_EXPECTED_ARG_SPECS: Final[
    tuple[tuple[str, str, object, type | None, tuple[str, ...] | None], ...]
] = (
    ("--expected-schema-version", "Expected schema_version value (default: 1)", 1, int, None),
    (
        "--expected-trigger-mode",
        "Expected trigger mode in payload; empty means do not check",
        "",
        None,
        ("strict", "compatible"),
    ),
    ("--expected-workflow", "Expected workflow filename in payload; empty means do not check", "", None, None),
    ("--expected-base-url", "Expected base_url in payload; empty means do not check", "", None, None),
    ("--expected-event-type", "Expected event_type in payload; empty means do not check", "", None, None),
    ("--expected-limit", "Expected limit in payload; empty means do not check", "", None, None),
    (
        "--expected-result-file-stale-threshold-ms",
        "Expected result_file_stale_threshold_ms in payload; empty means do not check",
        "",
        None,
        None,
    ),
    (
        "--expected-summary-schema-version",
        "Expected expected_summary_schema_version in payload; empty means do not check",
        "",
        None,
        None,
    ),
    ("--expected-result-schema-version", "Expected expected_schema_version in payload; empty means do not check", "", None, None),
    ("--expected-file-suffix", "Expected file_suffix in payload; empty means do not check", "", None, None),
    ("--expected-conclusion", "Expected conclusion in payload; empty means do not check", "", None, None),
)

GH_TRIGGER_AUDIT_THRESHOLD_ARG_SPECS: Final[
    tuple[tuple[str, str, object, type | None, tuple[str, ...] | None], ...]
] = (
    (
        "--max-duration-ms",
        "Optional max duration threshold; if set, duration_ms must be <= this value",
        None,
        int,
        None,
    ),
    (
        "--max-age-ms",
        "Optional max audit age threshold; if set, now-completed_at_ms must be <= this value",
        None,
        int,
        None,
    ),
)

GH_TRIGGER_AUDIT_VALIDATE_PAYLOAD_ARG_BINDINGS: Final[tuple[tuple[str, str], ...]] = (
    ("payload_sha256_mode", "payload_sha256_mode"),
    ("expected_schema_version", "expected_schema_version"),
    ("schema_mode", "schema_mode"),
    ("expected_trigger_mode", "expected_trigger_mode"),
    ("expected_workflow", "expected_workflow"),
    ("expected_limit", "expected_limit"),
    ("expected_result_file_stale_threshold_ms", "expected_result_file_stale_threshold_ms"),
    ("expected_summary_schema_version", "expected_summary_schema_version"),
    ("expected_result_schema_version", "expected_result_schema_version"),
    ("expected_file_suffix", "expected_file_suffix"),
    ("max_duration_ms", "max_duration_ms"),
    ("expected_base_url", "expected_base_url"),
    ("expected_event_type", "expected_event_type"),
    ("expected_conclusion", "expected_conclusion"),
    ("max_age_ms", "max_age_ms"),
)


def add_expected_field_arguments(parser: argparse.ArgumentParser) -> None:
    for flag, help_text, default_value, value_type, choices in GH_TRIGGER_AUDIT_EXPECTED_ARG_SPECS:
        kwargs: dict[str, object] = {"default": default_value, "help": help_text}
        if value_type is not None:
            kwargs["type"] = value_type
        if choices:
            kwargs["choices"] = choices
        parser.add_argument(flag, **kwargs)


def add_base_arguments(parser: argparse.ArgumentParser) -> None:
    for flag, help_text, default_value, value_type, choices, required in GH_TRIGGER_AUDIT_BASE_ARG_SPECS:
        kwargs: dict[str, object] = {"help": help_text}
        if required:
            kwargs["required"] = True
        else:
            kwargs["default"] = default_value
        if value_type is not None:
            kwargs["type"] = value_type
        if choices:
            kwargs["choices"] = choices
        parser.add_argument(flag, **kwargs)


def add_threshold_arguments(parser: argparse.ArgumentParser) -> None:
    for flag, help_text, default_value, value_type, choices in GH_TRIGGER_AUDIT_THRESHOLD_ARG_SPECS:
        kwargs: dict[str, object] = {"default": default_value, "help": help_text}
        if value_type is not None:
            kwargs["type"] = value_type
        if choices:
            kwargs["choices"] = choices
        parser.add_argument(flag, **kwargs)


def build_validate_payload_kwargs(args: argparse.Namespace) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    for payload_param, arg_attr in GH_TRIGGER_AUDIT_VALIDATE_PAYLOAD_ARG_BINDINGS:
        kwargs[payload_param] = getattr(args, arg_attr)
    return kwargs
