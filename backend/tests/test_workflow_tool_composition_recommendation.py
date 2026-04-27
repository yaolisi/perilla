from typing import Any, Dict

from core.workflows.recommendation import WorkflowToolCompositionRecommender


class _FakeStore:
    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._data[key] = value


def test_record_usage_and_recommend(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(
        "core.workflows.recommendation.get_system_settings_store",
        lambda: store,
    )
    recommender = WorkflowToolCompositionRecommender()
    recommender.record_usage(
        workflow_id="wf_1",
        user_id="u_1",
        template_id="travel_planning",
        tool_sequence=["weather.query", "flight.booking"],
    )

    ranked = recommender.recommend(
        workflow_id="wf_1",
        user_id="u_1",
        current_tools=["weather.query", "hotel.recommendation"],
        limit=5,
    )
    assert ranked
    assert ranked[0]["id"] == "travel_planning"
    assert int(ranked[0]["signals"]["user_uses"]) >= 1
    assert int(ranked[0]["signals"]["overlap"]) >= 1


def test_transition_probability_signal(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(
        "core.workflows.recommendation.get_system_settings_store",
        lambda: store,
    )
    recommender = WorkflowToolCompositionRecommender()
    # 多次写入，构建 weather.query -> flight.booking 的高转移计数
    for _ in range(3):
        recommender.record_usage(
            workflow_id="wf_2",
            user_id="u_2",
            template_id="travel_planning",
            tool_sequence=["weather.query", "flight.booking", "hotel.recommendation"],
        )

    ranked = recommender.recommend(
        workflow_id="wf_2",
        user_id="u_2",
        current_tools=["weather.query"],
        limit=2,
    )
    assert ranked
    assert ranked[0]["id"] == "travel_planning"
    assert int(ranked[0]["signals"]["transition_score"]) > 0
    assert float(ranked[0]["signals"]["transition_confidence"]) > 0
    assert isinstance(ranked[0]["signals"].get("transition_pairs"), list)
    assert ranked[0]["signals"]["transition_pairs"]


def test_record_runtime_sequence_without_template_use(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(
        "core.workflows.recommendation.get_system_settings_store",
        lambda: store,
    )
    recommender = WorkflowToolCompositionRecommender()
    recommender.record_runtime_sequence(
        workflow_id="wf_3",
        user_id="u_3",
        tool_sequence=["weather.query", "flight.booking"],
    )

    payload = store.get_setting("workflow_tool_composition_usage_v1", {})
    assert isinstance(payload, dict)
    assert payload.get("global_template_uses", {}) == {}
    gt = payload.get("global_tool_transitions", {})
    assert int(gt.get("weather.query", {}).get("flight.booking", 0)) >= 1

