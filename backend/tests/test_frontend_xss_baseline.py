from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_markdown_disables_raw_html():
    content = (_repo_root() / "frontend" / "src" / "utils" / "markdown.ts").read_text(encoding="utf-8")
    assert "html: false" in content


def test_markdown_output_is_sanitized():
    content = (_repo_root() / "frontend" / "src" / "utils" / "markdown.ts").read_text(encoding="utf-8")
    assert "sanitizeHtml(md.render(content || ''))" in content


def test_agent_trace_mermaid_svg_is_sanitized():
    content = (
        _repo_root() / "frontend" / "src" / "components" / "agents" / "AgentExecutionTraceView.vue"
    ).read_text(encoding="utf-8")
    assert "securityLevel: 'strict'" in content
    assert "dagMermaidSvg.value = sanitizeHtml(svg)" in content
