from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from core.security.audit_service import query_audit_logs
from core.system.settings_store import SystemSettingsStore, get_system_settings_store
from core.data.base import db_session


DEFAULT_ROADMAP_KPIS: Dict[str, Any] = {
    "availability_min": 0.999,
    "p99_latency_ms_max": 2500,
    "rag_top5_recall_min": 0.85,
    "answer_usefulness_min": 0.90,
    "unit_cost_reduction_min": 0.30,
    "critical_security_incidents_max": 0,
    "observability_coverage_min": 1.00,
    "online_error_rate_max": 0.002,
}

DEFAULT_PHASE_GATES: Dict[str, Dict[str, Any]] = {
    "phase0_foundation": {
        "required_capabilities": [
            "fine_grained_permissions",
            "audit_traceability",
            "observability_dashboard",
            "rag_eval_baseline",
        ],
        "required_kpis": {
            "observability_coverage": 1.00,
            "critical_security_incidents": 0,
        },
    },
    "phase1_core": {
        "required_capabilities": [
            "dynamic_batching",
            "hybrid_retrieval",
            "function_calling_orchestration",
            "agent_role_collaboration",
        ],
        "required_kpis": {
            "throughput_gain": 2.5,
            "online_error_rate": 0.002,
        },
    },
    "phase2_advanced": {
        "required_capabilities": [
            "multi_hop_retrieval",
            "kg_augmented_rag",
            "active_learning_reviewed_update",
            "anomaly_detection",
        ],
        "required_kpis": {
            "multi_hop_accuracy_gain": 0.15,
            "hallucination_reduction": 0.20,
        },
    },
    "phase3_scale": {
        "required_capabilities": [
            "cluster_scaling",
            "model_version_governance",
            "sso_integration",
            "multimodal_pilot",
        ],
        "required_kpis": {
            "auto_scaling_trigger_success_rate": 0.99,
            "rollback_time_seconds": 300,
        },
    },
}


@dataclass
class RoadmapEvaluation:
    score: float
    passed: bool
    reasons: List[str]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_roadmap_kpis(store: SystemSettingsStore | None = None) -> Dict[str, Any]:
    settings_store = store or get_system_settings_store()
    persisted = settings_store.get_setting("roadmap_kpis", None)
    if isinstance(persisted, dict):
        return {**DEFAULT_ROADMAP_KPIS, **persisted}
    return dict(DEFAULT_ROADMAP_KPIS)


def save_roadmap_kpis(payload: Dict[str, Any], store: SystemSettingsStore | None = None) -> Dict[str, Any]:
    settings_store = store or get_system_settings_store()
    merged = {**get_roadmap_kpis(settings_store), **payload}
    settings_store.set_setting("roadmap_kpis", merged)
    settings_store.set_setting(
        "roadmap_kpis_meta",
        {
            "updated_at": _utc_now_iso(),
            "keys": sorted(payload.keys()),
        },
    )
    return merged


def get_phase_gates(store: SystemSettingsStore | None = None) -> Dict[str, Dict[str, Any]]:
    settings_store = store or get_system_settings_store()
    persisted = settings_store.get_setting("roadmap_phase_gates", None)
    if not isinstance(persisted, dict):
        return DEFAULT_PHASE_GATES
    out: Dict[str, Dict[str, Any]] = {}
    for phase, gate in DEFAULT_PHASE_GATES.items():
        if not isinstance(persisted.get(phase), dict):
            out[phase] = gate
            continue
        out[phase] = {
            "required_capabilities": persisted[phase].get("required_capabilities", gate["required_capabilities"]),
            "required_kpis": {**gate["required_kpis"], **(persisted[phase].get("required_kpis") or {})},
        }
    return out


def save_phase_gates(payload: Dict[str, Dict[str, Any]], store: SystemSettingsStore | None = None) -> Dict[str, Dict[str, Any]]:
    settings_store = store or get_system_settings_store()
    current = get_phase_gates(settings_store)
    merged: Dict[str, Dict[str, Any]] = {}
    for phase, gate in current.items():
        updated = payload.get(phase) or {}
        merged[phase] = {
            "required_capabilities": updated.get("required_capabilities", gate["required_capabilities"]),
            "required_kpis": {**gate["required_kpis"], **(updated.get("required_kpis") or {})},
        }
    settings_store.set_setting("roadmap_phase_gates", merged)
    return merged


def collect_operational_baseline() -> Dict[str, Any]:
    from core.runtime import get_runtime_metrics

    metrics = get_runtime_metrics().get_metrics()
    summary = metrics.get("summary") or {}
    total_requests = int(summary.get("total_requests") or 0)
    failed_requests = int(summary.get("total_requests_failed") or 0)
    failure_rate = (failed_requests / total_requests) if total_requests else 0.0
    avg_latency_ms = float(summary.get("avg_latency_ms") or 0.0)
    p95_latency_ms = float(summary.get("p95_latency_ms") or 0.0)
    p99_latency_ms = float(summary.get("p99_latency_ms") or p95_latency_ms)
    models_count = int(summary.get("models_count") or 0)

    return {
        "requests": total_requests,
        "failed_requests": failed_requests,
        "online_error_rate": round(failure_rate, 6),
        "avg_latency_ms": avg_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "p99_latency_ms": p99_latency_ms,
        "models_count": models_count,
    }


def _load_manual_quality_metrics(store: SystemSettingsStore) -> Dict[str, Any]:
    raw = store.get_setting("roadmap_quality_metrics", None)
    if isinstance(raw, dict):
        return raw
    return {
        "rag_top5_recall": 0.0,
        "answer_usefulness": 0.0,
        "unit_cost_reduction": 0.0,
        "observability_coverage": 0.0,
        "critical_security_incidents": 0,
        "throughput_gain": 1.0,
        "multi_hop_accuracy_gain": 0.0,
        "hallucination_reduction": 0.0,
        "auto_scaling_trigger_success_rate": 0.0,
        "rollback_time_seconds": 999999,
    }


def save_manual_quality_metrics(payload: Dict[str, Any], store: SystemSettingsStore | None = None) -> Dict[str, Any]:
    settings_store = store or get_system_settings_store()
    merged = {**_load_manual_quality_metrics(settings_store), **payload}
    settings_store.set_setting("roadmap_quality_metrics", merged)
    return merged


def build_roadmap_snapshot(store: SystemSettingsStore | None = None) -> Dict[str, Any]:
    settings_store = store or get_system_settings_store()
    automatic = collect_operational_baseline()
    manual = _load_manual_quality_metrics(settings_store)
    return {
        **automatic,
        **manual,
        "snapshot_at": _utc_now_iso(),
    }


def _check_kpi_threshold(metric_name: str, current_value: float, threshold_value: float) -> Tuple[bool, str]:
    if metric_name.endswith("_max"):
        ok = current_value <= threshold_value
    elif metric_name.endswith("_min"):
        ok = current_value >= threshold_value
    else:
        # 默认按“越大越好”处理，特殊指标由 phase gate 的 required_kpis 精确约束
        ok = current_value >= threshold_value
    relation = ">=" if ok else "<"
    return ok, f"{metric_name}: current={current_value} threshold={threshold_value} relation={relation}"


def evaluate_north_star(snapshot: Dict[str, Any], kpis: Dict[str, Any]) -> RoadmapEvaluation:
    checks = [
        ("availability_min", 1.0 - float(snapshot.get("online_error_rate") or 0.0)),
        ("p99_latency_ms_max", float(snapshot.get("p99_latency_ms") or 0.0)),
        ("rag_top5_recall_min", float(snapshot.get("rag_top5_recall") or 0.0)),
        ("answer_usefulness_min", float(snapshot.get("answer_usefulness") or 0.0)),
        ("unit_cost_reduction_min", float(snapshot.get("unit_cost_reduction") or 0.0)),
        ("critical_security_incidents_max", float(snapshot.get("critical_security_incidents") or 0.0)),
        ("observability_coverage_min", float(snapshot.get("observability_coverage") or 0.0)),
    ]
    reasons: List[str] = []
    passed_count = 0
    for key, value in checks:
        threshold = float(kpis.get(key, DEFAULT_ROADMAP_KPIS[key]))
        ok, reason = _check_kpi_threshold(key, value, threshold)
        reasons.append(reason)
        if ok:
            passed_count += 1
    score = passed_count / len(checks) if checks else 0.0
    return RoadmapEvaluation(score=score, passed=score >= 0.9999, reasons=reasons)


def _evaluate_gate_kpis(snapshot: Dict[str, Any], required_kpis: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    kpi_results: Dict[str, Any] = {}
    kpi_ok_count = 0
    for metric_name, threshold in required_kpis.items():
        current = float(snapshot.get(metric_name) or 0.0)
        threshold_value = float(threshold)
        if metric_name in {"online_error_rate", "rollback_time_seconds"}:
            ok = current <= threshold_value
        else:
            ok = current >= threshold_value
        if ok:
            kpi_ok_count += 1
        kpi_results[metric_name] = {
            "current": current,
            "target": threshold_value,
            "passed": ok,
        }
    return kpi_ok_count, kpi_results


def evaluate_phase_gates(snapshot: Dict[str, Any], gates: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    capabilities_raw = snapshot.get("capabilities") or {}
    capabilities = capabilities_raw if isinstance(capabilities_raw, dict) else {}
    phase_status: Dict[str, Dict[str, Any]] = {}

    for phase, gate in gates.items():
        required_capabilities = list(gate.get("required_capabilities") or [])
        required_kpis = gate.get("required_kpis") or {}
        missing_capabilities = [name for name in required_capabilities if not bool(capabilities.get(name))]
        kpi_ok_count, kpi_results = _evaluate_gate_kpis(snapshot, required_kpis)
        gate_passed = (not missing_capabilities) and (kpi_ok_count == len(required_kpis))
        phase_status[phase] = {
            "passed": gate_passed,
            "missing_capabilities": missing_capabilities,
            "kpi_results": kpi_results,
        }
    return phase_status


def _count_recent_audit_entries(hours: int = 720) -> int:
    with db_session() as db:
        since = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))
        rows, total = query_audit_logs(db, since=since, limit=1, offset=0)
        return total if isinstance(total, int) else len(rows)


def create_monthly_review() -> Dict[str, Any]:
    store = get_system_settings_store()
    snapshot = build_roadmap_snapshot(store)
    kpis = get_roadmap_kpis(store)
    gates = get_phase_gates(store)

    north_star = evaluate_north_star(snapshot, kpis)
    phase_status = evaluate_phase_gates(snapshot, gates)
    phase_passed_count = sum(1 for item in phase_status.values() if item.get("passed"))
    gate_score = phase_passed_count / len(phase_status) if phase_status else 0.0
    audit_total = _count_recent_audit_entries()

    review = {
        "created_at": _utc_now_iso(),
        "snapshot": snapshot,
        "north_star": {
            "score": round(north_star.score, 4),
            "passed": north_star.passed,
            "reasons": north_star.reasons,
        },
        "phase_gate": {
            "score": round(gate_score, 4),
            "passed": gate_score >= 0.75,
            "phases": phase_status,
        },
        "go_no_go": "go" if north_star.passed and gate_score >= 0.75 else "no_go",
        "audit_entry_count": audit_total,
    }

    history = store.get_setting("roadmap_monthly_reviews", [])
    if not isinstance(history, list):
        history = []
    history.append(review)
    store.set_setting("roadmap_monthly_reviews", history[-24:])
    return review


def list_monthly_reviews(limit: int = 12) -> List[Dict[str, Any]]:
    store = get_system_settings_store()
    reviews = store.get_setting("roadmap_monthly_reviews", [])
    if not isinstance(reviews, list):
        return []
    size = max(1, min(36, int(limit)))
    return list(reviews)[-size:][::-1]
