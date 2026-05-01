from __future__ import annotations

import pytest

from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo


def test_vitest_config_coverage_include_lists_workflow_logs_uselogs() -> None:
    """Keep Vitest coverage scope aligned with documented frontend gates (workflow, logs UI, useLogs)."""
    root = repo_root()
    text = (root / "frontend" / "vitest.config.ts").read_text(encoding="utf-8")
    assert "'src/components/workflow/**/*.{ts,vue}'" in text
    assert "'src/components/logs/**/*.{ts,vue}'" in text
    assert "'src/composables/useLogs.ts'" in text
