from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


try:
    from prometheus_client import Counter, Gauge, Histogram
except Exception:  # pragma: no cover - graceful fallback for environments without prometheus deps
    Counter = Gauge = Histogram = None  # type: ignore


@dataclass
class _NoopMetric:
    def labels(self, **_kwargs):  # type: ignore[no-untyped-def]
        return self

    def inc(self, _value: float = 1.0) -> None:
        return

    def dec(self, _value: float = 1.0) -> None:
        return

    def observe(self, _value: float) -> None:
        return


class PrometheusBusinessMetrics:
    def __init__(self) -> None:
        noop = _NoopMetric()
        if Counter is None or Gauge is None or Histogram is None:
            self.inference_latency_seconds = noop
            self.inference_requests_in_flight = noop
            self.inference_errors_total = noop
            self.agent_runs_total = noop
            self.agent_run_failures_total = noop
            return

        self.inference_latency_seconds = Histogram(
            "openvitamin_inference_latency_seconds",
            "Inference latency in seconds",
            labelnames=("operation", "provider", "model"),
        )
        self.inference_requests_in_flight = Gauge(
            "openvitamin_inference_requests_in_flight",
            "Current in-flight inference requests",
            labelnames=("operation",),
        )
        self.inference_errors_total = Counter(
            "openvitamin_inference_errors_total",
            "Total inference errors",
            labelnames=("operation", "provider"),
        )
        self.agent_runs_total = Counter(
            "openvitamin_agent_runs_total",
            "Total agent runtime runs",
            labelnames=("mode", "engine"),
        )
        self.agent_run_failures_total = Counter(
            "openvitamin_agent_run_failures_total",
            "Total failed agent runtime runs",
            labelnames=("mode", "engine"),
        )

    def observe_inference_started(self, operation: str) -> None:
        self.inference_requests_in_flight.labels(operation=operation).inc()

    def observe_inference_finished(self, *, operation: str, provider: str, model: str, latency_seconds: float) -> None:
        self.inference_requests_in_flight.labels(operation=operation).dec()
        self.inference_latency_seconds.labels(
            operation=operation,
            provider=provider or "unknown",
            model=model or "unknown",
        ).observe(max(0.0, float(latency_seconds)))

    def observe_inference_failed(self, *, operation: str, provider: str) -> None:
        self.inference_requests_in_flight.labels(operation=operation).dec()
        self.inference_errors_total.labels(operation=operation, provider=provider or "unknown").inc()

    def observe_agent_run(self, *, mode: str, engine: str, success: bool) -> None:
        norm_mode = mode or "unknown"
        norm_engine = engine or "unknown"
        self.agent_runs_total.labels(mode=norm_mode, engine=norm_engine).inc()
        if not success:
            self.agent_run_failures_total.labels(mode=norm_mode, engine=norm_engine).inc()


_metrics: Optional[PrometheusBusinessMetrics] = None


def get_prometheus_business_metrics() -> PrometheusBusinessMetrics:
    global _metrics
    if _metrics is None:
        _metrics = PrometheusBusinessMetrics()
    return _metrics
