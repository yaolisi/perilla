"""
API 层对 execution_strategy / max_parallel_nodes 与 model_params 一致性的单元测试。
（不启动 ASGI，只测 api.agents 中的校验逻辑。）
"""

import pytest

from api.agents import _validate_kernel_opts_consistency
from api.errors import APIException


def test_no_raise_when_only_model_params_or_only_top():
    _validate_kernel_opts_consistency(None, None, {"execution_strategy": "serial"})
    _validate_kernel_opts_consistency("parallel_kernel", None, {})
    _validate_kernel_opts_consistency(
        "serial", 2, {"other": 1}
    )


def test_no_raise_when_both_match():
    _validate_kernel_opts_consistency(
        "serial", 3, {"execution_strategy": "serial", "max_parallel_nodes": 3}
    )
    _validate_kernel_opts_consistency(
        "parallel_kernel",
        4,
        {"execution_strategy": "parallel_kernel", "max_parallel_nodes": 4},
    )


def test_raises_on_execution_strategy_mismatch():
    with pytest.raises(APIException) as exc:
        _validate_kernel_opts_consistency(
            "serial",
            None,
            {"execution_strategy": "parallel_kernel"},
        )
    assert exc.value.status_code == 400
    assert "execution_strategy conflicts" in exc.value.message


def test_raises_on_max_parallel_mismatch():
    with pytest.raises(APIException) as exc:
        _validate_kernel_opts_consistency(
            None,
            2,
            {"max_parallel_nodes": 4},
        )
    assert exc.value.status_code == 400
    assert "max_parallel_nodes conflicts" in exc.value.message


def test_raises_on_invalid_execution_strategy_in_model_params():
    with pytest.raises(APIException) as exc:
        _validate_kernel_opts_consistency(None, None, {"execution_strategy": "invalid"})
    assert exc.value.status_code == 400


def test_raises_on_max_parallel_out_of_range_in_model_params():
    with pytest.raises(APIException) as exc:
        _validate_kernel_opts_consistency(None, None, {"max_parallel_nodes": 99})
    assert exc.value.status_code == 400
