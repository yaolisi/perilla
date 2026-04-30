from __future__ import annotations

from scripts import roadmap_acceptance_smoke as smoke


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_run_smoke_happy_path(monkeypatch):
    seq = [
        _FakeResponse(200, {"kpis": {"availability_min": 0.99}}),
        _FakeResponse(200, {"success": True, "kpis": {"availability_min": 0.99}}),
        _FakeResponse(200, {"success": True, "quality_metrics": {"rag_top5_recall": 0.88}}),
        _FakeResponse(200, {"snapshot": {}, "north_star": {"score": 1.0}, "phase_gate": {"score": 1.0}}),
        _FakeResponse(200, {"review": {"go_no_go": "go"}}),
        _FakeResponse(200, {"items": [{"go_no_go": "go"}]}),
    ]

    def _fake_request(method, url, headers=None, json=None, timeout=20):  # noqa: ANN001
        _ = (method, url, headers, json, timeout)
        return seq.pop(0)

    monkeypatch.setattr(smoke.requests, "request", _fake_request)
    smoke.run_smoke("http://127.0.0.1:8000", api_key=None)


def test_run_smoke_raises_on_server_error(monkeypatch):
    def _fake_request(method, url, headers=None, json=None, timeout=20):  # noqa: ANN001
        _ = (method, url, headers, json, timeout)
        return _FakeResponse(500, {"detail": "internal error"})

    monkeypatch.setattr(smoke.requests, "request", _fake_request)
    try:
        smoke.run_smoke("http://127.0.0.1:8000", api_key=None)
        assert False, "expected run_smoke to raise"
    except AssertionError as exc:
        assert "failed with 500" in str(exc)
