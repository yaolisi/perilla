from __future__ import annotations

import pytest

from scripts.event_bus_smoke_makefile_utils import slice_make_target


def test_slice_make_target_returns_section_between_targets() -> None:
    makefile_text = "\n".join(
        [
            "foo:",
            "\t@echo foo",
            "bar:",
            "\t@echo bar",
            "baz:",
            "\t@echo baz",
        ]
    )
    section = slice_make_target(makefile_text, "bar", "baz")
    assert section == "bar:\n\t@echo bar"


def test_slice_make_target_raises_when_target_not_found() -> None:
    with pytest.raises(ValueError, match="target not found: missing"):
        slice_make_target("foo:\n\t@echo foo\n", "missing", "foo")


def test_slice_make_target_raises_when_next_target_not_found() -> None:
    with pytest.raises(ValueError, match="failed to slice target body: foo"):
        slice_make_target("foo:\n\t@echo foo\n", "foo", "missing")
