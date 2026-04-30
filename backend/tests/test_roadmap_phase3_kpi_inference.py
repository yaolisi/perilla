from __future__ import annotations

from contextlib import nullcontext

import pytest

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
