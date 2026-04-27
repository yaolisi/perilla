from __future__ import annotations


def slice_make_target(makefile_text: str, target: str, next_target: str) -> str:
    anchor = f"{target}:"
    next_anchor = f"\n{next_target}:"
    start = makefile_text.find(anchor)
    if start < 0:
        raise ValueError(f"target not found: {target}")
    end = makefile_text.find(next_anchor, start)
    if end <= start:
        raise ValueError(f"failed to slice target body: {target}")
    return makefile_text[start:end]
