"""
model_params RAG 键的 API 校验（不启动 ASGI）。
"""

import pytest

from api.agents import _validate_model_params_rag
from api.errors import APIException


def test_allows_absent_or_empty() -> None:
    _validate_model_params_rag(None)
    _validate_model_params_rag({})
    _validate_model_params_rag({"intent_rules": []})


def test_allows_valid_full() -> None:
    _validate_model_params_rag(
        {
            "rag_top_k": 12,
            "rag_score_threshold": 1.2,
            "rag_retrieval_mode": "hybrid",
            "rag_min_relevance_score": 0.45,
            "rag_multi_hop_enabled": True,
            "rag_multi_hop_max_rounds": 3,
            "rag_multi_hop_min_chunks": 2,
            "rag_multi_hop_min_best_relevance": 0.6,
            "rag_multi_hop_relax_relevance": False,
            "rag_multi_hop_feedback_chars": 400,
        }
    )


def test_allows_boolish_strings() -> None:
    _validate_model_params_rag({"rag_multi_hop_enabled": "true"})
    _validate_model_params_rag({"rag_multi_hop_relax_relevance": "off"})


def test_rejects_rag_top_k_out_of_range() -> None:
    with pytest.raises(APIException) as exc:
        _validate_model_params_rag({"rag_top_k": 0})
    assert exc.value.status_code == 400
    assert exc.value.code == "agent_invalid_model_params_rag"


def test_rejects_rag_top_k_bool() -> None:
    with pytest.raises(APIException):
        _validate_model_params_rag({"rag_top_k": True})


def test_rejects_retrieval_mode() -> None:
    with pytest.raises(APIException):
        _validate_model_params_rag({"rag_retrieval_mode": "fulltext"})


def test_rejects_min_relevance_above_one() -> None:
    with pytest.raises(APIException):
        _validate_model_params_rag({"rag_min_relevance_score": 1.01})


def test_rejects_multi_hop_rounds_out_of_range() -> None:
    with pytest.raises(APIException):
        _validate_model_params_rag({"rag_multi_hop_max_rounds": 6})


def test_rejects_feedback_chars_too_low() -> None:
    with pytest.raises(APIException):
        _validate_model_params_rag({"rag_multi_hop_feedback_chars": 40})
