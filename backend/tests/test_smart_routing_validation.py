import pytest

from api.errors import APIException
from core.system.smart_routing_validation import validate_smart_routing_policies_json


def test_validate_smart_routing_policies_json_accepts_empty() -> None:
    validate_smart_routing_policies_json("")
    validate_smart_routing_policies_json("   ")


def test_validate_smart_routing_policies_json_rejects_invalid_strategy() -> None:
    with pytest.raises(APIException) as exc:
        validate_smart_routing_policies_json(
            '{"reasoning-model":{"strategy":"random","stable":"a","candidate":"b"}}'
        )
    assert exc.value.code == "system_config_invalid_smart_routing_policies_json"


def test_validate_smart_routing_policies_json_requires_candidates_for_weighted() -> None:
    with pytest.raises(APIException) as exc:
        validate_smart_routing_policies_json(
            '{"reasoning-model":{"strategy":"weighted"}}'
        )
    assert exc.value.code == "system_config_invalid_smart_routing_policies_json"
