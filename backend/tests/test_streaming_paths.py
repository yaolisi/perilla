"""middleware.streaming_paths：SSE 豁免路径匹配（与敏感数据脱敏短路一致）。"""

from middleware.streaming_paths import is_sse_stream_exempt_path


def test_sse_exempt_chat_completions_prefix():
    assert is_sse_stream_exempt_path("/v1/chat/completions")
    assert is_sse_stream_exempt_path("/v1/chat/completions/stream/resume")
    assert is_sse_stream_exempt_path("/api/v1/chat/completions")


def test_sse_exempt_workflow_execution_stream():
    assert is_sse_stream_exempt_path(
        "/api/v1/workflows/wf-1/executions/ex-1/stream"
    )


def test_sse_exempt_agent_session_stream():
    assert is_sse_stream_exempt_path("/api/agent-sessions/sess-1/stream")


def test_sse_exempt_system_logs_stream():
    assert is_sse_stream_exempt_path("/api/system/logs/stream")


def test_non_exempt_json_api():
    assert not is_sse_stream_exempt_path("/api/v1/workflows")
    assert not is_sse_stream_exempt_path("/api/events/instance/x")
