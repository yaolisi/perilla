from __future__ import annotations

from core.system import roadmap


class _FakeStore:
    def __init__(self) -> None:
        self._data = {}

    def get_setting(self, key, default=None):
        return self._data.get(key, default)

    def set_setting(self, key, value):
        self._data[key] = value


def test_save_and_get_roadmap_kpis_merge_defaults() -> None:
    store = _FakeStore()
    saved = roadmap.save_roadmap_kpis({"p99_latency_ms_max": 1800}, store=store)
    assert saved["p99_latency_ms_max"] == 1800

    loaded = roadmap.get_roadmap_kpis(store=store)
    assert loaded["availability_min"] == roadmap.DEFAULT_ROADMAP_KPIS["availability_min"]
    assert loaded["p99_latency_ms_max"] == 1800


def test_evaluate_north_star_pass_and_fail() -> None:
    kpis = roadmap.DEFAULT_ROADMAP_KPIS
    snapshot_ok = {
        "online_error_rate": 0.0005,
        "p99_latency_ms": 1200,
        "rag_top5_recall": 0.9,
        "answer_usefulness": 0.93,
        "unit_cost_reduction": 0.35,
        "critical_security_incidents": 0,
        "observability_coverage": 1.0,
    }
    passed = roadmap.evaluate_north_star(snapshot_ok, kpis)
    assert passed.passed is True

    snapshot_bad = {
        **snapshot_ok,
        "p99_latency_ms": 4000,
        "critical_security_incidents": 1,
    }
    failed = roadmap.evaluate_north_star(snapshot_bad, kpis)
    assert failed.passed is False
    assert failed.score < 1.0


def test_evaluate_phase_gates_detects_missing_capabilities_and_kpi() -> None:
    snapshot = {
        "capabilities": {"fine_grained_permissions": True},
        "observability_coverage": 0.8,
        "critical_security_incidents": 0,
    }
    gates = {
        "phase0_foundation": {
            "required_capabilities": ["fine_grained_permissions", "audit_traceability"],
            "required_kpis": {"observability_coverage": 1.0},
        }
    }
    result = roadmap.evaluate_phase_gates(snapshot, gates)
    phase = result["phase0_foundation"]
    assert phase["passed"] is False
    assert "audit_traceability" in phase["missing_capabilities"]
    assert phase["kpi_results"]["observability_coverage"]["passed"] is False


def test_create_monthly_review_persists_history(monkeypatch) -> None:
    store = _FakeStore()
    monkeypatch.setattr(roadmap, "get_system_settings_store", lambda: store)
    monkeypatch.setattr(
        roadmap,
        "build_roadmap_snapshot",
        lambda _store=None: {
            "online_error_rate": 0.0005,
            "p99_latency_ms": 1000,
            "rag_top5_recall": 0.9,
            "answer_usefulness": 0.92,
            "unit_cost_reduction": 0.35,
            "critical_security_incidents": 0,
            "observability_coverage": 1.0,
            "capabilities": dict.fromkeys(
                [
                    "fine_grained_permissions",
                    "audit_traceability",
                    "observability_dashboard",
                    "rag_eval_baseline",
                    "dynamic_batching",
                    "hybrid_retrieval",
                    "function_calling_orchestration",
                    "agent_role_collaboration",
                    "multi_hop_retrieval",
                    "kg_augmented_rag",
                    "active_learning_reviewed_update",
                    "anomaly_detection",
                    "cluster_scaling",
                    "model_version_governance",
                    "sso_integration",
                    "multimodal_pilot",
                ],
                True,
            ),
            "throughput_gain": 3.0,
            "multi_hop_accuracy_gain": 0.2,
            "hallucination_reduction": 0.3,
            "auto_scaling_trigger_success_rate": 0.995,
            "rollback_time_seconds": 120,
        },
    )
    monkeypatch.setattr(roadmap, "_count_recent_audit_entries", lambda hours=720: 42)

    review = roadmap.create_monthly_review()
    assert review["go_no_go"] == "go"
    assert review["audit_entry_count"] == 42

    history = roadmap.list_monthly_reviews(limit=5)
    assert len(history) == 1
    assert history[0]["go_no_go"] == "go"
