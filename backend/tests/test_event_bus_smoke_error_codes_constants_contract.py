from __future__ import annotations

import re

import scripts.event_bus_smoke_error_codes as error_codes


def _all_error_code_constants() -> dict[str, str]:
    constants: dict[str, str] = {}
    for name in dir(error_codes):
        if not name.startswith("ERR_"):
            continue
        value = getattr(error_codes, name)
        if isinstance(value, str):
            constants[name] = value
    return constants


def test_error_code_constants_are_unique() -> None:
    constants = _all_error_code_constants()
    values = list(constants.values())
    assert len(values) == len(set(values)), "duplicate error code values found"


def test_error_code_constants_use_snake_case_values() -> None:
    constants = _all_error_code_constants()
    pattern = re.compile(r"^[a-z][a-z0-9_]*$")
    invalid = [name for name, value in constants.items() if pattern.fullmatch(value) is None]
    assert not invalid, f"error code values must be lowercase snake_case: {invalid}"


def test_error_code_constants_have_expected_prefix_groups() -> None:
    constants = _all_error_code_constants()
    supported_prefixes = (
        "guard_",
        "health_",
        "payload_",
        "summary_",
        "preflight_",
        "contract_",
        "result_",
        "log_",
        "gh_trigger_",
        "gh_snapshot_",
        "smoke_dlq_",
    )
    invalid = [name for name, value in constants.items() if not value.startswith(supported_prefixes)]
    assert not invalid, f"unsupported error code prefix groups: {invalid}"
