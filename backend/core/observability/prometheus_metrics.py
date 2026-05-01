from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config.settings import settings

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

    def set(self, _value: float) -> None:
        return


class PrometheusBusinessMetrics:
    def __init__(self) -> None:
        noop = _NoopMetric()
        if Counter is None or Gauge is None or Histogram is None:
            self.inference_latency_seconds = noop
            self.inference_requests_in_flight = noop
            self.inference_errors_total = noop
            self.inference_cancelled_total = noop
            self.chat_stream_wall_clock_limit_total = noop
            self.chat_stream_client_disconnect_stop_total = noop
            self.chat_stream_resume_upstream_cancel_total = noop
            self.stream_resume_store_pressure_evictions_total = noop
            self.stream_resume_store_sessions = noop
            self.chat_stream_resume_wait_timeouts_total = noop
            self.agent_runs_total = noop
            self.agent_run_failures_total = noop
            self.workflow_scheduler_platform_max_concurrency = noop
            self.event_bus_published_total = noop
            self.event_bus_publish_latency_seconds = noop
            self.health_ready_event_bus_degraded = noop
            self.health_ready_inference_cache_redis_degraded = noop
            self.http_rate_limit_blocked_total = noop
            self.http_rate_limit_redis_backend_errors_total = noop
            self.health_ready_api_rate_limit_redis_degraded = noop
            self.health_ready_shutting_down = noop
            self._legacy_mirror = False
            return

        self.inference_latency_seconds = Histogram(
            "perilla_inference_latency_seconds",
            "Inference latency in seconds",
            labelnames=("operation", "provider", "model"),
        )
        self.inference_requests_in_flight = Gauge(
            "perilla_inference_requests_in_flight",
            "Current in-flight inference requests",
            labelnames=("operation",),
        )
        self.inference_errors_total = Counter(
            "perilla_inference_errors_total",
            "Total inference errors",
            labelnames=("operation", "provider"),
        )
        self.inference_cancelled_total = Counter(
            "perilla_inference_cancelled_total",
            "Stream inference cancelled (client disconnect / task cancellation); does not increment errors_total",
            labelnames=("operation", "provider"),
        )
        self.chat_stream_wall_clock_limit_total = Counter(
            "perilla_chat_stream_wall_clock_limit_total",
            "Chat SSE stopped due to chat_stream_wall_clock_max_seconds",
            labelnames=(),
        )
        self.chat_stream_client_disconnect_stop_total = Counter(
            "perilla_chat_stream_client_disconnect_stop_total",
            "Chat SSE stopped early (client disconnected, stream resume disabled)",
            labelnames=(),
        )
        self.chat_stream_resume_upstream_cancel_total = Counter(
            "perilla_chat_stream_resume_upstream_cancel_total",
            "Chat SSE: resume enabled but upstream cancelled on disconnect (chat_stream_resume_cancel_upstream_on_disconnect)",
            labelnames=(),
        )
        self.stream_resume_store_pressure_evictions_total = Counter(
            "perilla_stream_resume_store_pressure_evictions_total",
            "Oldest stream resume session evicted because chat_stream_resume_max_sessions reached with unfinished buffers",
            labelnames=(),
        )
        self.stream_resume_store_sessions = Gauge(
            "perilla_stream_resume_store_sessions",
            "Stream resume buffer sessions currently in the in-memory store (includes finished until TTL eviction)",
            labelnames=(),
        )
        self.stream_resume_store_sessions.set(0.0)
        self.chat_stream_resume_wait_timeouts_total = Counter(
            "perilla_chat_stream_resume_wait_timeouts_total",
            "POST /v1/chat/completions/stream/resume iter_resume_chunks wait_for(cond) exceeded chat_stream_resume_wait_timeout_seconds",
            labelnames=(),
        )
        self.agent_runs_total = Counter(
            "perilla_agent_runs_total",
            "Total agent runtime runs",
            labelnames=("mode", "engine"),
        )
        self.agent_run_failures_total = Counter(
            "perilla_agent_run_failures_total",
            "Total failed agent runtime runs",
            labelnames=("mode", "engine"),
        )

        self.workflow_scheduler_platform_max_concurrency = Gauge(
            "perilla_workflow_scheduler_platform_max_concurrency",
            "Effective workflow DAG parallel node cap (runtime_settings / env WORKFLOW_SCHEDULER_MAX_CONCURRENCY)",
            labelnames=(),
        )
        self.event_bus_published_total = Counter(
            "perilla_event_bus_published_total",
            "Event bus publish operations completed",
            labelnames=("backend",),
        )
        self.event_bus_publish_latency_seconds = Histogram(
            "perilla_event_bus_publish_latency_seconds",
            "Wall time for event bus publish (includes in-process handler execution for InProcessEventBus)",
            labelnames=("backend",),
            buckets=(0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 60.0),
        )
        self.health_ready_event_bus_degraded = Gauge(
            "perilla_health_ready_event_bus_degraded",
            "1 if the last /api/health/ready check reported event bus degraded (else 0)",
            labelnames=(),
        )
        self.health_ready_event_bus_degraded.set(0.0)
        self.health_ready_inference_cache_redis_degraded = Gauge(
            "perilla_health_ready_inference_cache_redis_degraded",
            "1 if the last /api/health/ready check reported inference-cache Redis degraded (else 0)",
            labelnames=(),
        )
        self.health_ready_inference_cache_redis_degraded.set(0.0)

        self.health_ready_api_rate_limit_redis_degraded = Gauge(
            "perilla_health_ready_api_rate_limit_redis_degraded",
            "1 if the last /api/health/ready check reported API rate-limit Redis degraded (else 0)",
            labelnames=(),
        )
        self.health_ready_api_rate_limit_redis_degraded.set(0.0)
        self.health_ready_shutting_down = Gauge(
            "perilla_health_ready_shutting_down",
            "1 while the application is in graceful shutdown (readiness should fail)",
            labelnames=(),
        )
        self.health_ready_shutting_down.set(0.0)

        self.http_rate_limit_blocked_total = Counter(
            "perilla_http_rate_limit_blocked_total",
            "Requests rejected by API rate limit middleware (429)",
            labelnames=("reason", "identity_type", "backend"),
        )
        self.http_rate_limit_redis_backend_errors_total = Counter(
            "perilla_http_rate_limit_redis_backend_errors_total",
            "Redis-backed rate limit operations that raised (before fail-open or fail-closed)",
            labelnames=("phase",),
        )

        self._legacy_mirror = bool(getattr(settings, "metrics_legacy_openvitamin_names_enabled", True))
        if self._legacy_mirror:
            self._legacy_inference_latency_seconds = Histogram(
                "openvitamin_inference_latency_seconds",
                "Inference latency in seconds (legacy alias; same series as perilla_*)",
                labelnames=("operation", "provider", "model"),
            )
            self._legacy_inference_requests_in_flight = Gauge(
                "openvitamin_inference_requests_in_flight",
                "Current in-flight inference requests (legacy alias)",
                labelnames=("operation",),
            )
            self._legacy_inference_errors_total = Counter(
                "openvitamin_inference_errors_total",
                "Total inference errors (legacy alias)",
                labelnames=("operation", "provider"),
            )
            self._legacy_inference_cancelled_total = Counter(
                "openvitamin_inference_cancelled_total",
                "Stream inference cancelled (legacy alias)",
                labelnames=("operation", "provider"),
            )
            self._legacy_agent_runs_total = Counter(
                "openvitamin_agent_runs_total",
                "Total agent runtime runs (legacy alias)",
                labelnames=("mode", "engine"),
            )
            self._legacy_agent_run_failures_total = Counter(
                "openvitamin_agent_run_failures_total",
                "Total failed agent runtime runs (legacy alias)",
                labelnames=("mode", "engine"),
            )
        else:
            self._legacy_inference_latency_seconds = noop
            self._legacy_inference_requests_in_flight = noop
            self._legacy_inference_errors_total = noop
            self._legacy_inference_cancelled_total = noop
            self._legacy_agent_runs_total = noop
            self._legacy_agent_run_failures_total = noop

    def observe_inference_started(self, operation: str) -> None:
        self.inference_requests_in_flight.labels(operation=operation).inc()
        if self._legacy_mirror:
            self._legacy_inference_requests_in_flight.labels(operation=operation).inc()

    def observe_inference_finished(self, *, operation: str, provider: str, model: str, latency_seconds: float) -> None:
        self.inference_requests_in_flight.labels(operation=operation).dec()
        lat = max(0.0, float(latency_seconds))
        self.inference_latency_seconds.labels(
            operation=operation,
            provider=provider or "unknown",
            model=model or "unknown",
        ).observe(lat)
        if self._legacy_mirror:
            self._legacy_inference_requests_in_flight.labels(operation=operation).dec()
            self._legacy_inference_latency_seconds.labels(
                operation=operation,
                provider=provider or "unknown",
                model=model or "unknown",
            ).observe(lat)

    def observe_inference_failed(self, *, operation: str, provider: str) -> None:
        self.inference_requests_in_flight.labels(operation=operation).dec()
        self.inference_errors_total.labels(operation=operation, provider=provider or "unknown").inc()
        if self._legacy_mirror:
            self._legacy_inference_requests_in_flight.labels(operation=operation).dec()
            self._legacy_inference_errors_total.labels(operation=operation, provider=provider or "unknown").inc()

    def observe_chat_stream_wall_clock_limit(self) -> None:
        self.chat_stream_wall_clock_limit_total.inc()

    def observe_chat_stream_client_disconnect_stop(self) -> None:
        self.chat_stream_client_disconnect_stop_total.inc()

    def observe_chat_stream_resume_upstream_cancel(self) -> None:
        self.chat_stream_resume_upstream_cancel_total.inc()

    def observe_stream_resume_store_pressure_eviction(self) -> None:
        self.stream_resume_store_pressure_evictions_total.inc()

    def set_stream_resume_store_sessions(self, n: int) -> None:
        self.stream_resume_store_sessions.set(max(0.0, float(int(n))))

    def observe_chat_stream_resume_wait_timeout(self) -> None:
        self.chat_stream_resume_wait_timeouts_total.inc()

    def observe_inference_cancelled(self, *, operation: str, provider: str) -> None:
        """
        释放 stream 请求的 in-flight 计数，不计入 errors_total，不写 latency histogram。
        """
        self.inference_requests_in_flight.labels(operation=operation).dec()
        self.inference_cancelled_total.labels(operation=operation, provider=provider or "unknown").inc()
        if self._legacy_mirror:
            self._legacy_inference_requests_in_flight.labels(operation=operation).dec()
            self._legacy_inference_cancelled_total.labels(operation=operation, provider=provider or "unknown").inc()

    def observe_agent_run(self, *, mode: str, engine: str, success: bool) -> None:
        norm_mode = mode or "unknown"
        norm_engine = engine or "unknown"
        self.agent_runs_total.labels(mode=norm_mode, engine=norm_engine).inc()
        if not success:
            self.agent_run_failures_total.labels(mode=norm_mode, engine=norm_engine).inc()
        if self._legacy_mirror:
            self._legacy_agent_runs_total.labels(mode=norm_mode, engine=norm_engine).inc()
            if not success:
                self._legacy_agent_run_failures_total.labels(mode=norm_mode, engine=norm_engine).inc()

    def set_workflow_scheduler_platform_max_concurrency(self, n: int) -> None:
        v = float(max(1, min(256, int(n))))
        self.workflow_scheduler_platform_max_concurrency.set(v)

    def observe_event_bus_publish(self, *, backend: str, latency_seconds: float) -> None:
        b = backend or "unknown"
        lat = max(0.0, float(latency_seconds))
        self.event_bus_published_total.labels(backend=b).inc()
        self.event_bus_publish_latency_seconds.labels(backend=b).observe(lat)

    def set_health_ready_event_bus_degraded(self, degraded: bool) -> None:
        self.health_ready_event_bus_degraded.set(1.0 if degraded else 0.0)

    def set_health_ready_inference_cache_redis_degraded(self, degraded: bool) -> None:
        self.health_ready_inference_cache_redis_degraded.set(1.0 if degraded else 0.0)

    def set_health_ready_api_rate_limit_redis_degraded(self, degraded: bool) -> None:
        self.health_ready_api_rate_limit_redis_degraded.set(1.0 if degraded else 0.0)

    def set_health_ready_shutting_down(self, shutting_down: bool) -> None:
        self.health_ready_shutting_down.set(1.0 if shutting_down else 0.0)

    def observe_rate_limit_blocked(self, *, reason: str, identity_type: str, backend: str) -> None:
        r = reason if reason in ("window", "concurrency") else "window"
        it = identity_type if identity_type in ("user", "api_key", "ip", "unknown") else "unknown"
        b = backend if backend in ("memory", "redis") else "memory"
        self.http_rate_limit_blocked_total.labels(reason=r, identity_type=it, backend=b).inc()

    def observe_rate_limit_redis_backend_error(self, *, phase: str) -> None:
        p = phase if phase in ("allow", "acquire", "release") else "allow"
        self.http_rate_limit_redis_backend_errors_total.labels(phase=p).inc()


_metrics: Optional[PrometheusBusinessMetrics] = None


def get_prometheus_business_metrics() -> PrometheusBusinessMetrics:
    global _metrics
    if _metrics is None:
        _metrics = PrometheusBusinessMetrics()
    return _metrics
