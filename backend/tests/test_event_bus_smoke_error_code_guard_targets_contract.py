from __future__ import annotations

from pathlib import Path
import re

from scripts.event_bus_smoke_error_code_guard_targets import (
    discover_error_code_guard_test_files,
    ERROR_CODE_GUARD_TEST_FILES,
    ERROR_CODE_GUARD_TEST_GLOB,
    extract_error_code_guard_tests_from_text,
    error_code_guard_test_path_regex,
    error_code_guard_test_regex,
    render_error_code_guard_tests_for_makefile,
)


def test_error_code_guard_targets_is_non_empty_tuple() -> None:
    assert isinstance(ERROR_CODE_GUARD_TEST_FILES, tuple)
    assert ERROR_CODE_GUARD_TEST_FILES


def test_error_code_guard_targets_are_unique() -> None:
    assert len(ERROR_CODE_GUARD_TEST_FILES) == len(set(ERROR_CODE_GUARD_TEST_FILES))


def test_error_code_guard_targets_use_expected_test_path_shape() -> None:
    for path in ERROR_CODE_GUARD_TEST_FILES:
        assert path.startswith("backend/tests/test_event_bus_smoke_")
        assert path.endswith(".py")


def test_error_code_guard_targets_include_coverage_contract() -> None:
    assert "backend/tests/test_event_bus_smoke_error_code_coverage_contract.py" in ERROR_CODE_GUARD_TEST_FILES


def test_error_code_guard_targets_follow_stable_order() -> None:
    expected_order = (
        "backend/tests/test_event_bus_smoke_error_code_contract.py",
        "backend/tests/test_event_bus_smoke_error_codes_constants_contract.py",
        "backend/tests/test_event_bus_smoke_error_code_preflight_json_contract.py",
        "backend/tests/test_event_bus_smoke_error_code_guard_targets_contract.py",
        "backend/tests/test_event_bus_smoke_error_code_coverage_contract.py",
    )
    assert ERROR_CODE_GUARD_TEST_FILES == expected_order


def test_error_code_guard_targets_match_repo_error_code_test_files_exactly() -> None:
    assert set(discover_error_code_guard_test_files()) == set(ERROR_CODE_GUARD_TEST_FILES)


def test_discover_error_code_guard_test_files_returns_sorted_tuple() -> None:
    discovered = discover_error_code_guard_test_files()
    assert isinstance(discovered, tuple)
    assert list(discovered) == sorted(discovered)


def test_discover_error_code_guard_test_files_supports_custom_base_dir(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_event_bus_smoke_error_code_b.py").write_text("", encoding="utf-8")
    (tests_dir / "test_event_bus_smoke_error_code_a.py").write_text("", encoding="utf-8")
    (tests_dir / "test_event_bus_smoke_error_codes_constants_contract.py").write_text("", encoding="utf-8")
    (tests_dir / "not_error_code_test.py").write_text("", encoding="utf-8")
    discovered = discover_error_code_guard_test_files(str(tests_dir))
    assert discovered == (
        str(tests_dir / "test_event_bus_smoke_error_code_a.py").replace("\\", "/"),
        str(tests_dir / "test_event_bus_smoke_error_code_b.py").replace("\\", "/"),
        str(tests_dir / "test_event_bus_smoke_error_codes_constants_contract.py").replace("\\", "/"),
    )


def test_error_code_guard_test_regex_matches_all_guard_targets() -> None:
    pattern = re.compile(error_code_guard_test_regex())
    for path in ERROR_CODE_GUARD_TEST_FILES:
        assert pattern.fullmatch(Path(path).name) is not None


def test_error_code_guard_test_path_regex_matches_all_guard_targets() -> None:
    pattern = re.compile(error_code_guard_test_path_regex())
    for path in ERROR_CODE_GUARD_TEST_FILES:
        assert pattern.fullmatch(path) is not None


def test_error_code_guard_regex_does_not_match_partial_or_extended_names() -> None:
    file_pattern = re.compile(error_code_guard_test_regex())
    path_pattern = re.compile(error_code_guard_test_path_regex())
    assert file_pattern.fullmatch("x_test_event_bus_smoke_error_code_contract.py") is None
    assert file_pattern.fullmatch("test_event_bus_smoke_error_code_contract.py.bak") is None
    assert path_pattern.fullmatch("x/backend/tests/test_event_bus_smoke_error_code_contract.py") is None
    assert path_pattern.fullmatch("backend/tests/test_event_bus_smoke_error_code_contract.py.bak") is None


def test_extract_error_code_guard_tests_from_text_preserves_order() -> None:
    text = "\n".join(
        [
            "foo",
            "backend/tests/test_event_bus_smoke_error_code_contract.py",
            "bar",
            "backend/tests/test_event_bus_smoke_error_codes_constants_contract.py",
        ]
    )
    extracted = extract_error_code_guard_tests_from_text(text)
    assert extracted == (
        "backend/tests/test_event_bus_smoke_error_code_contract.py",
        "backend/tests/test_event_bus_smoke_error_codes_constants_contract.py",
    )


def test_extract_error_code_guard_tests_from_text_ignores_non_matching_paths() -> None:
    text = "\n".join(
        [
            "backend/tests/test_event_bus_smoke_error_code_contract.py.bak",
            "x/backend/tests/test_event_bus_smoke_error_code_contract.py",
            "backend/tests/test_event_bus_smoke_error_code_contract.py",
        ]
    )
    extracted = extract_error_code_guard_tests_from_text(text)
    assert extracted == ("backend/tests/test_event_bus_smoke_error_code_contract.py",)


def test_extract_error_code_guard_tests_from_text_handles_makefile_line_continuations() -> None:
    text = "\n".join(
        [
            "backend/tests/test_event_bus_smoke_error_code_contract.py \\",
            "backend/tests/test_event_bus_smoke_error_codes_constants_contract.py \\",
            "backend/tests/test_event_bus_smoke_error_code_guard_targets_contract.py",
        ]
    )
    extracted = extract_error_code_guard_tests_from_text(text)
    assert extracted == (
        "backend/tests/test_event_bus_smoke_error_code_contract.py",
        "backend/tests/test_event_bus_smoke_error_codes_constants_contract.py",
        "backend/tests/test_event_bus_smoke_error_code_guard_targets_contract.py",
    )


def test_extract_error_code_guard_tests_from_text_handles_multiple_tokens_per_line() -> None:
    text = (
        "python -m pytest -c backend/tests/pytest.smoke.ini "
        "backend/tests/test_event_bus_smoke_error_code_contract.py "
        "backend/tests/test_event_bus_smoke_error_code_coverage_contract.py \\"
    )
    extracted = extract_error_code_guard_tests_from_text(text)
    assert extracted == (
        "backend/tests/test_event_bus_smoke_error_code_contract.py",
        "backend/tests/test_event_bus_smoke_error_code_coverage_contract.py",
    )


def test_extract_error_code_guard_tests_from_text_deduplicates_preserving_order() -> None:
    text = "\n".join(
        [
            "backend/tests/test_event_bus_smoke_error_code_contract.py",
            "backend/tests/test_event_bus_smoke_error_code_contract.py",
            "backend/tests/test_event_bus_smoke_error_code_coverage_contract.py",
            "backend/tests/test_event_bus_smoke_error_code_contract.py",
        ]
    )
    extracted = extract_error_code_guard_tests_from_text(text)
    assert extracted == (
        "backend/tests/test_event_bus_smoke_error_code_contract.py",
        "backend/tests/test_event_bus_smoke_error_code_coverage_contract.py",
    )


def test_render_error_code_guard_tests_for_makefile_matches_expected_block() -> None:
    rendered = render_error_code_guard_tests_for_makefile()
    expected = "\n".join(
        [
            "\t\tbackend/tests/test_event_bus_smoke_error_code_contract.py \\",
            "\t\tbackend/tests/test_event_bus_smoke_error_codes_constants_contract.py \\",
            "\t\tbackend/tests/test_event_bus_smoke_error_code_preflight_json_contract.py \\",
            "\t\tbackend/tests/test_event_bus_smoke_error_code_guard_targets_contract.py \\",
            "\t\tbackend/tests/test_event_bus_smoke_error_code_coverage_contract.py",
        ]
    )
    assert rendered == expected
