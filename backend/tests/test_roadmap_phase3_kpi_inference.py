from __future__ import annotations

from contextlib import nullcontext

import pytest

from api.system import (
    RoadmapKpisReadResponse,
    RoadmapKpisUpdateResponse,
    RoadmapMonthlyReviewCreateResponse,
    RoadmapPhaseGatesUpdateResponse,
    RoadmapQualityMetricsReadResponse,
    RoadmapQualityMetricsUpdateResponse,
    SystemJsonMap,
)
from core.system import roadmap


class _Store:
    def __init__(self, data: dict | None = None) -> None:
        self._data = dict(data or {})

    def get_setting(self, key: str, default: object = None) -> object:
        if key in self._data:
            return self._data[key]
        return default

    def set_setting(self, key: str, value: object) -> None:
        self._data[key] = value


def test_save_manual_quality_metrics_tracks_explicit_keys() -> None:
    store = _Store()
    roadmap.save_manual_quality_metrics({"rag_top5_recall": 0.9}, store=store)
    assert set(store._data.get("roadmap_quality_metrics_explicit_keys") or []) == {"rag_top5_recall"}
    roadmap.save_manual_quality_metrics({"throughput_gain": 2.0}, store=store)
    keys = set(store._data.get("roadmap_quality_metrics_explicit_keys") or [])
    assert keys >= {"rag_top5_recall", "throughput_gain"}


def test_roadmap_kpis_read_response_validates() -> None:
    RoadmapKpisReadResponse.model_validate({"kpis": roadmap.get_roadmap_kpis()})


def test_roadmap_kpis_update_response_validates() -> None:
    RoadmapKpisUpdateResponse.model_validate(
        {"success": True, "kpis": {"availability_min": 0.99, "p99_latency_ms_max": 2500.0}},
    )


def test_roadmap_phase_gates_update_response_validates() -> None:
    RoadmapPhaseGatesUpdateResponse.model_validate(
        {
            "success": True,
            "phase_gates": {
                "phase0_foundation": {"required_capabilities": [], "required_kpis": {}},
            },
        },
    )


def test_roadmap_monthly_review_create_response_validates() -> None:
    RoadmapMonthlyReviewCreateResponse.model_validate(
        {
            "success": True,
            "review": {
                "created_at": "2026-05-01T00:00:00+00:00",
                "snapshot": {},
                "north_star": {"score": 1.0, "passed": True, "reasons": []},
                "phase_gate": {
                    "score": 1.0,
                    "passed": True,
                    "phases": {},
                    "blocking_capabilities": [],
                    "readiness_summary": {},
                },
                "go_no_go": "go",
                "go_no_go_reasons": [],
                "top_blocker_capability": None,
                "audit_entry_count": 0,
            },
        },
    )


def test_roadmap_quality_metrics_update_response_validates_save_payload() -> None:
    store = _Store()
    merged = roadmap.save_manual_quality_metrics({"rag_top5_recall": 0.71}, store=store)
    model = RoadmapQualityMetricsUpdateResponse.model_validate({"success": True, "quality_metrics": merged})
    assert model.success is True
    assert model.quality_metrics.model_dump().get("rag_top5_recall") == pytest.approx(0.71)


def test_roadmap_quality_metrics_read_response_validates_describe_payload() -> None:
    store = _Store()
    payload = roadmap.describe_roadmap_quality_metrics(store=store)
    model = RoadmapQualityMetricsReadResponse.model_validate(payload)
    assert model.explicit_metric_keys_tracked is False
    assert model.explicit_metric_keys is None
    assert isinstance(model.phase3_kpi_inference_probe, SystemJsonMap)


def test_describe_roadmap_quality_metrics_returns_stable_shape() -> None:
    store = _Store()
    out = roadmap.describe_roadmap_quality_metrics(store=store)
    assert set(out.keys()) == {
        "quality_metrics",
        "explicit_metric_keys",
        "explicit_metric_keys_tracked",
        "phase3_kpi_inference_probe",
    }
    assert isinstance(out["quality_metrics"], dict)
    assert out["explicit_metric_keys"] is None
    assert out["explicit_metric_keys_tracked"] is False
    assert isinstance(out["phase3_kpi_inference_probe"], dict)


def test_describe_roadmap_quality_metrics_lists_explicit_keys_when_tracked() -> None:
    store = _Store(
        {
            "roadmap_quality_metrics": {"rag_top5_recall": 0.82},
            "roadmap_quality_metrics_explicit_keys": ["rag_top5_recall"],
        },
    )
    out = roadmap.describe_roadmap_quality_metrics(store=store)
    assert out["explicit_metric_keys_tracked"] is True
    assert out["explicit_metric_keys"] == ["rag_top5_recall"]
    assert out["quality_metrics"].get("rag_top5_recall") == pytest.approx(0.82)


def test_build_snapshot_fills_phase3_kpis_when_quality_metrics_not_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store()
    monkeypatch.setattr(roadmap, "get_system_settings_store", lambda: store)
    monkeypatch.setattr(roadmap, "collect_operational_baseline", lambda: {"online_error_rate": 0.001})
    monkeypatch.setattr(
        roadmap,
        "collect_phase3_kpi_inference",
        lambda: {"auto_scaling_trigger_success_rate": 0.991, "rollback_time_seconds": 240.0},
    )
    snap = roadmap.build_roadmap_snapshot(store=store)
    assert snap["auto_scaling_trigger_success_rate"] == pytest.approx(0.991)
    assert snap["rollback_time_seconds"] == pytest.approx(240.0)


def test_build_snapshot_skips_phase3_inference_when_quality_metrics_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store(
        {
            "roadmap_quality_metrics": {
                "auto_scaling_trigger_success_rate": 0.4,
                "rollback_time_seconds": 999,
            },
            "roadmap_quality_metrics_explicit_keys": [
                "auto_scaling_trigger_success_rate",
                "rollback_time_seconds",
            ],
        },
    )
    monkeypatch.setattr(roadmap, "get_system_settings_store", lambda: store)
    monkeypatch.setattr(roadmap, "collect_operational_baseline", lambda: {"online_error_rate": 0.001})
    monkeypatch.setattr(
        roadmap,
        "collect_phase3_kpi_inference",
        lambda: {"auto_scaling_trigger_success_rate": 0.999, "rollback_time_seconds": 1.0},
    )
    snap = roadmap.build_roadmap_snapshot(store=store)
    assert snap["auto_scaling_trigger_success_rate"] == pytest.approx(0.4)
    assert snap["rollback_time_seconds"] == pytest.approx(999.0)


def test_build_snapshot_infers_phase3_when_only_other_metrics_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store(
        {
            "roadmap_quality_metrics": {
                "rag_top5_recall": 0.91,
                "auto_scaling_trigger_success_rate": 0.0,
                "rollback_time_seconds": 999999,
            },
            "roadmap_quality_metrics_explicit_keys": ["rag_top5_recall"],
        },
    )
    monkeypatch.setattr(roadmap, "get_system_settings_store", lambda: store)
    monkeypatch.setattr(roadmap, "collect_operational_baseline", lambda: {"online_error_rate": 0.001})
    monkeypatch.setattr(
        roadmap,
        "collect_phase3_kpi_inference",
        lambda: {"auto_scaling_trigger_success_rate": 0.991, "rollback_time_seconds": 240.0},
    )
    snap = roadmap.build_roadmap_snapshot(store=store)
    assert snap["auto_scaling_trigger_success_rate"] == pytest.approx(0.991)
    assert snap["rollback_time_seconds"] == pytest.approx(240.0)
    assert snap["rag_top5_recall"] == pytest.approx(0.91)


def test_build_snapshot_legacy_overrides_phase3_when_still_default(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store(
        {
            "roadmap_quality_metrics": {
                "rag_top5_recall": 0.91,
                "auto_scaling_trigger_success_rate": 0.0,
                "rollback_time_seconds": 999999,
            },
        },
    )
    monkeypatch.setattr(roadmap, "get_system_settings_store", lambda: store)
    monkeypatch.setattr(roadmap, "collect_operational_baseline", lambda: {"online_error_rate": 0.001})
    monkeypatch.setattr(
        roadmap,
        "collect_phase3_kpi_inference",
        lambda: {"auto_scaling_trigger_success_rate": 0.991, "rollback_time_seconds": 240.0},
    )
    snap = roadmap.build_roadmap_snapshot(store=store)
    assert snap["auto_scaling_trigger_success_rate"] == pytest.approx(0.991)
    assert snap["rollback_time_seconds"] == pytest.approx(240.0)


def test_infer_auto_scaling_rate_none_without_slo_traffic(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.runtime as runtime_mod

    class _M:
        def get_metrics(self) -> dict:
            return {"by_priority_summary": {"high": {"requests": 5, "slo_target_ms": 0, "slo_met_count": 0}}}

    monkeypatch.setattr(runtime_mod, "get_runtime_metrics", lambda: _M())
    assert roadmap._infer_auto_scaling_trigger_success_rate_from_runtime() is None


def test_infer_auto_scaling_rate_from_slo_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.runtime as runtime_mod

    class _M:
        def get_metrics(self) -> dict:
            return {
                "by_priority_summary": {
                    "high": {"requests": 10, "slo_target_ms": 1000, "slo_met_count": 9},
                    "medium": {"requests": 0, "slo_target_ms": 0, "slo_met_count": 0},
                    "low": {"requests": 10, "slo_target_ms": 500, "slo_met_count": 10},
                },
            }

    monkeypatch.setattr(runtime_mod, "get_runtime_metrics", lambda: _M())
    assert roadmap._infer_auto_scaling_trigger_success_rate_from_runtime() == pytest.approx(19 / 20)


def test_infer_rollback_seconds_none_when_no_audit_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roadmap, "db_session", nullcontext)
    monkeypatch.setattr(roadmap, "count_audit_events_matching", lambda *a, **k: 0)
    assert roadmap._infer_rollback_time_seconds_from_audit() is None


def test_infer_rollback_seconds_uses_idle_ttl_when_audit_match(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.system.runtime_settings as rs

    monkeypatch.setattr(roadmap, "db_session", nullcontext)
    monkeypatch.setattr(roadmap, "count_audit_events_matching", lambda *a, **k: 2)
    monkeypatch.setattr(rs, "get_runtime_release_idle_ttl_seconds", lambda: 222)
    assert roadmap._infer_rollback_time_seconds_from_audit() == pytest.approx(222.0)
