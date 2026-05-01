import pytest

from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo


def test_markdown_disables_raw_html():
    content = (repo_root() / "frontend" / "src" / "utils" / "markdown.ts").read_text(encoding="utf-8")
    assert "html: false" in content


def test_markdown_output_is_sanitized():
    content = (repo_root() / "frontend" / "src" / "utils" / "markdown.ts").read_text(encoding="utf-8")
    assert "sanitizeHtml(md.render(content || ''))" in content


def test_agent_trace_mermaid_svg_is_sanitized():
    content = (
        repo_root() / "frontend" / "src" / "components" / "agents" / "AgentExecutionTraceView.vue"
    ).read_text(encoding="utf-8")
    assert "securityLevel: 'strict'" in content
    # Mermaid SVG 经专门收敛后再通用 HTML 消毒（与 utils/security 中实现一致）
    assert "dagMermaidSvg.value = sanitizeMermaidSvg(svg)" in content
