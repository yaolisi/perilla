"""chat.resume 辅助：DONE 行检测（避免重复终端帧）、请求追踪字段。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from api.chat import _correlation_from_request, _sse_buffers_include_done_line


def test_sse_buffers_include_done_detects_marker() -> None:
    assert _sse_buffers_include_done_line(["data: [DONE]\n\n"]) is True
    assert _sse_buffers_include_done_line(["data: {\"x\":1}\n\n", "data: [DONE]\n\n"]) is True
    assert _sse_buffers_include_done_line(["data: {\"x\":1}\n\n"]) is False
    assert _sse_buffers_include_done_line([]) is False


def test_correlation_from_request_prefers_state_over_headers() -> None:
    req = MagicMock()
    req.state = SimpleNamespace(request_id="rid-state", trace_id="tid-state")
    req.headers.get.return_value = None
    assert _correlation_from_request(req) == {
        "request_id": "rid-state",
        "trace_id": "tid-state",
    }


def test_correlation_from_request_fallback_headers_when_state_missing() -> None:
    req = MagicMock()
    req.state = SimpleNamespace()

    def _get(header: str, default=None):
        return {
            "X-Request-Id": "hdr-rid",
            "X-Trace-Id": "hdr-tid",
        }.get(header, default)

    req.headers.get.side_effect = _get
    assert _correlation_from_request(req) == {"request_id": "hdr-rid", "trace_id": "hdr-tid"}
