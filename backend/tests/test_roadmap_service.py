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
        "capability_details": {
            "audit_traceability": {
                "source": "manual",
                "enabled": False,
                "signals": {"reason": "not configured"},
            }
        },
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
    assert phase["missing_capability_details"]["audit_traceability"]["enabled"] is False
    assert phase["kpi_results"]["observability_coverage"]["passed"] is False
    assert isinstance(phase["readiness"], dict)
    assert phase["readiness"]["capability_total_count"] == 2
    assert phase["readiness"]["kpi_total_count"] == 1
    assert phase["readiness"]["score"] < 1.0


def test_evaluate_phase_gates_accepts_multi_hop_alias() -> None:
    snapshot = {
        "capabilities": {"multi_hop_retrieval_system": True},
        "capability_details": {
            "multi_hop_retrieval_system": {
                "source": "auto_detect",
                "enabled": True,
                "signals": {"manifest_exists": True},
            }
        },
        "multi_hop_accuracy_gain": 0.2,
    }
    gates = {
        "phase2_advanced": {
            "required_capabilities": ["multi_hop_retrieval"],
            "required_kpis": {"multi_hop_accuracy_gain": 0.15},
        }
    }
    result = roadmap.evaluate_phase_gates(snapshot, gates)
    phase = result["phase2_advanced"]
    assert phase["passed"] is True
    assert phase["missing_capabilities"] == []
    assert phase["readiness"]["score"] >= 0.9999


def test_evaluate_phase_gates_missing_capability_has_fallback_detail() -> None:
    snapshot = {
        "capabilities": {},
        "capability_details": {},
        "multi_hop_accuracy_gain": 0.1,
    }
    gates = {
        "phase2_advanced": {
            "required_capabilities": ["anomaly_detection"],
            "required_kpis": {"multi_hop_accuracy_gain": 0.15},
        }
    }
    result = roadmap.evaluate_phase_gates(snapshot, gates)
    detail = result["phase2_advanced"]["missing_capability_details"]["anomaly_detection"]
    assert detail["enabled"] is False
    assert detail["source"] == "gate_evaluator"
    assert detail["signals"]["requested_capability"] == "anomaly_detection"


def test_build_roadmap_snapshot_includes_anomaly_signals(monkeypatch) -> None:
    store = _FakeStore()
    store.set_setting("chaosFailRateWarn", 0.01)
    store.set_setting("chaosP95WarnMs", 2000)
    store.set_setting("chaosNetErrWarn", 10)
    monkeypatch.setattr(
        roadmap,
        "collect_operational_baseline",
        lambda: {
            "online_error_rate": 0.05,
            "p95_latency_ms": 3500,
            "failed_requests": 12,
        },
    )
    monkeypatch.setattr(roadmap, "_load_manual_quality_metrics", lambda _store: {})

    snapshot = roadmap.build_roadmap_snapshot(store=store)
    anomaly = snapshot.get("anomaly_signals", {})
    assert anomaly.get("anomaly_detected") is True
    assert set(anomaly.get("breached_metrics") or []) == {"online_error_rate", "p95_latency_ms", "failed_requests"}


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

    capabilities = dict.fromkeys(
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
    )
    review = roadmap.create_monthly_review(
        capabilities=capabilities,
        capability_details={"dynamic_batching": {"enabled": True, "source": "runtime_settings", "signals": {}}},
    )
    assert review["go_no_go"] == "go"
    assert review["audit_entry_count"] == 42
    assert review["snapshot"]["capabilities"]["dynamic_batching"] is True
    assert review["snapshot"]["capability_details"]["dynamic_batching"]["enabled"] is True
    assert isinstance(review["phase_gate"]["blocking_capabilities"], list)
    assert review["phase_gate"]["blocking_capabilities"] == []
    assert review["go_no_go_reasons"][0]["type"] == "summary"
    assert review["top_blocker_capability"] is None

    history = roadmap.list_monthly_reviews(limit=5)
    assert len(history) == 1
    assert history[0]["go_no_go"] == "go"


def test_build_blocking_capabilities_aggregates_and_sorts() -> None:
    phase_status = {
        "phase1_core": {
            "passed": False,
            "missing_capabilities": ["hybrid_retrieval", "dynamic_batching"],
            "missing_capability_details": {
                "hybrid_retrieval": {"enabled": False, "source": "rag_plugin_manifest", "signals": {}},
                "dynamic_batching": {"enabled": False, "source": "runtime_settings", "signals": {}},
            },
            "kpi_results": {},
        },
        "phase2_advanced": {
            "passed": False,
            "missing_capabilities": ["hybrid_retrieval"],
            "missing_capability_details": {
                "hybrid_retrieval": {"enabled": False, "source": "rag_plugin_manifest", "signals": {}},
            },
            "kpi_results": {},
        },
    }
    items = roadmap.build_blocking_capabilities(phase_status)
    assert len(items) == 2
    assert items[0]["capability"] == "hybrid_retrieval"
    assert items[0]["phase_count"] == 2
    assert set(items[0]["blocked_phases"]) == {"phase1_core", "phase2_advanced"}


def test_build_phase_readiness_summary_picks_lowest_phase() -> None:
    phase_status = {
        "phase1_core": {"readiness": {"score": 0.85}},
        "phase2_advanced": {"readiness": {"score": 0.65}},
        "phase3_scale": {"readiness": {"score": 0.9}},
    }
    summary = roadmap.build_phase_readiness_summary(phase_status, low_threshold=0.7)
    assert summary["lowest_phase"] == "phase2_advanced"
    assert abs(float(summary["lowest_score"]) - 0.65) < 1e-9
    assert summary["phases_below_threshold"] == ["phase2_advanced"]
    assert summary["average_score"] > 0.0


def test_build_go_no_go_reasons_for_no_go_prefers_blockers() -> None:
    reasons = roadmap.build_go_no_go_reasons(
        go_no_go="no_go",
        north_star=roadmap.RoadmapEvaluation(score=0.6, passed=False, reasons=["kpi gap"]),
        blocking_capabilities=[
            {"capability": "hybrid_retrieval", "phase_count": 2, "blocked_phases": ["phase1_core", "phase2_advanced"]},
            {"capability": "dynamic_batching", "phase_count": 1, "blocked_phases": ["phase1_core"]},
        ],
        anomaly_signals={"anomaly_detected": True, "breached_metrics": ["online_error_rate"]},
        readiness_summary={"lowest_phase": "phase2_advanced", "lowest_score": 0.62, "low_threshold": 0.7},
        max_items=5,
    )
    assert reasons[0]["type"] == "capability_blocker"
    assert reasons[0]["capability"] == "hybrid_retrieval"
    assert any(item.get("type") == "anomaly_risk" for item in reasons)
    assert any(item.get("type") == "readiness_risk" for item in reasons)
    assert any(item.get("type") == "north_star" for item in reasons)


def test_build_go_no_go_summary_for_go_and_no_go() -> None:
    go_summary = roadmap.build_go_no_go_summary(
        north_star=roadmap.RoadmapEvaluation(score=1.0, passed=True, reasons=[]),
        gate_score=0.8,
        blocking_capabilities=[],
    )
    assert go_summary["go_no_go"] == "go"
    assert go_summary["top_blocker_capability"] is None
    assert go_summary["go_no_go_reasons"][0]["type"] == "summary"

    no_go_summary = roadmap.build_go_no_go_summary(
        north_star=roadmap.RoadmapEvaluation(score=0.5, passed=False, reasons=["kpi gap"]),
        gate_score=0.5,
        blocking_capabilities=[{"capability": "hybrid_retrieval", "phase_count": 2, "blocked_phases": ["phase1_core"]}],
        anomaly_signals={"anomaly_detected": True, "breached_metrics": ["p95_latency_ms"]},
        readiness_summary={"lowest_phase": "phase1_core", "lowest_score": 0.5, "low_threshold": 0.7},
    )
    assert no_go_summary["go_no_go"] == "no_go"
    assert no_go_summary["top_blocker_capability"] == "hybrid_retrieval"
    assert no_go_summary["go_no_go_reasons"][0]["type"] == "capability_blocker"
    assert any(item.get("type") == "anomaly_risk" for item in no_go_summary["go_no_go_reasons"])
    assert any(item.get("type") == "readiness_risk" for item in no_go_summary["go_no_go_reasons"])


def test_create_monthly_review_sets_top_blocker_capability(monkeypatch) -> None:
    store = _FakeStore()
    monkeypatch.setattr(roadmap, "get_system_settings_store", lambda: store)
    monkeypatch.setattr(
        roadmap,
        "build_roadmap_snapshot",
        lambda _store=None: {
            "online_error_rate": 0.2,
            "p99_latency_ms": 9000,
            "rag_top5_recall": 0.3,
            "answer_usefulness": 0.3,
            "unit_cost_reduction": 0.0,
            "critical_security_incidents": 2,
            "observability_coverage": 0.1,
            "throughput_gain": 1.0,
        },
    )
    monkeypatch.setattr(roadmap, "_count_recent_audit_entries", lambda hours=720: 1)
    monkeypatch.setattr(
        roadmap,
        "get_phase_gates",
        lambda _store=None: {
            "phase1_core": {
                "required_capabilities": ["hybrid_retrieval", "dynamic_batching"],
                "required_kpis": {"throughput_gain": 2.5},
            }
        },
    )
    review = roadmap.create_monthly_review(
        capabilities={"dynamic_batching": False, "hybrid_retrieval": False},
        capability_details={
            "dynamic_batching": {"enabled": False, "source": "runtime_settings", "signals": {}},
            "hybrid_retrieval": {"enabled": False, "source": "rag_plugin_manifest", "signals": {}},
        },
    )
    assert review["go_no_go"] == "no_go"
    assert review["top_blocker_capability"] in {"dynamic_batching", "hybrid_retrieval"}
    assert isinstance(review["phase_gate"].get("readiness_summary"), dict)


def test_list_monthly_reviews_filter_by_top_blocker(monkeypatch) -> None:
    store = _FakeStore()
    store.set_setting(
        "roadmap_monthly_reviews",
        [
            {"created_at": "2026-01-01T00:00:00Z", "top_blocker_capability": "hybrid_retrieval"},
            {"created_at": "2026-01-02T00:00:00Z", "top_blocker_capability": "dynamic_batching"},
            {"created_at": "2026-01-03T00:00:00Z", "top_blocker_capability": "hybrid_retrieval"},
        ],
    )
    monkeypatch.setattr(roadmap, "get_system_settings_store", lambda: store)

    items = roadmap.list_monthly_reviews(limit=10, top_blocker_capability="hybrid_retrieval")
    assert len(items) == 2
    assert items[0]["created_at"] == "2026-01-03T00:00:00Z"
    assert items[1]["created_at"] == "2026-01-01T00:00:00Z"


def test_list_monthly_reviews_filter_by_go_no_go(monkeypatch) -> None:
    store = _FakeStore()
    store.set_setting(
        "roadmap_monthly_reviews",
        [
            {"created_at": "2026-01-01T00:00:00Z", "go_no_go": "go", "top_blocker_capability": None},
            {"created_at": "2026-01-02T00:00:00Z", "go_no_go": "no_go", "top_blocker_capability": "dynamic_batching"},
            {"created_at": "2026-01-03T00:00:00Z", "go_no_go": "no_go", "top_blocker_capability": "hybrid_retrieval"},
        ],
    )
    monkeypatch.setattr(roadmap, "get_system_settings_store", lambda: store)

    items = roadmap.list_monthly_reviews(limit=10, go_no_go="no_go")
    assert len(items) == 2
    assert items[0]["created_at"] == "2026-01-03T00:00:00Z"
    assert items[1]["created_at"] == "2026-01-02T00:00:00Z"


def test_list_monthly_reviews_supports_offset_pagination(monkeypatch) -> None:
    store = _FakeStore()
    store.set_setting(
        "roadmap_monthly_reviews",
        [
            {"created_at": "2026-01-01T00:00:00Z", "go_no_go": "go"},
            {"created_at": "2026-01-02T00:00:00Z", "go_no_go": "go"},
            {"created_at": "2026-01-03T00:00:00Z", "go_no_go": "go"},
        ],
    )
    monkeypatch.setattr(roadmap, "get_system_settings_store", lambda: store)

    page1 = roadmap.list_monthly_reviews(limit=1, offset=0)
    page2 = roadmap.list_monthly_reviews(limit=1, offset=1)
    assert page1[0]["created_at"] == "2026-01-03T00:00:00Z"
    assert page2[0]["created_at"] == "2026-01-02T00:00:00Z"


def test_list_monthly_reviews_page_returns_items_and_total(monkeypatch) -> None:
    store = _FakeStore()
    store.set_setting(
        "roadmap_monthly_reviews",
        [
            {"created_at": "2026-01-01T00:00:00Z", "go_no_go": "go", "top_blocker_capability": None},
            {"created_at": "2026-01-02T00:00:00Z", "go_no_go": "no_go", "top_blocker_capability": "dynamic_batching"},
            {"created_at": "2026-01-03T00:00:00Z", "go_no_go": "no_go", "top_blocker_capability": "hybrid_retrieval"},
        ],
    )
    monkeypatch.setattr(roadmap, "get_system_settings_store", lambda: store)

    items, total = roadmap.list_monthly_reviews_page(limit=1, offset=0, go_no_go="no_go")
    assert total == 2
    assert len(items) == 1
    assert items[0]["created_at"] == "2026-01-03T00:00:00Z"


def test_list_monthly_reviews_page_supports_combined_filters(monkeypatch) -> None:
    store = _FakeStore()
    store.set_setting(
        "roadmap_monthly_reviews",
        [
            {"created_at": "2026-01-01T00:00:00Z", "go_no_go": "no_go", "top_blocker_capability": "hybrid_retrieval"},
            {"created_at": "2026-01-02T00:00:00Z", "go_no_go": "go", "top_blocker_capability": None},
            {"created_at": "2026-01-03T00:00:00Z", "go_no_go": "no_go", "top_blocker_capability": "dynamic_batching"},
            {"created_at": "2026-01-04T00:00:00Z", "go_no_go": "no_go", "top_blocker_capability": "hybrid_retrieval"},
        ],
    )
    monkeypatch.setattr(roadmap, "get_system_settings_store", lambda: store)

    items, total = roadmap.list_monthly_reviews_page(
        limit=10,
        offset=0,
        go_no_go="no_go",
        top_blocker_capability="hybrid_retrieval",
    )
    assert total == 2
    assert [item["created_at"] for item in items] == [
        "2026-01-04T00:00:00Z",
        "2026-01-01T00:00:00Z",
    ]
