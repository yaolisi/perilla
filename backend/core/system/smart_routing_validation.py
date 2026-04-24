import json

from api.errors import raise_api_error


_ALLOWED_STRATEGY = {
    "blue_green",
    "canary",
    "weighted",
    "least_loaded",
    "least_loaded_prefer_candidate",
}


def _ensure_alias(alias: object) -> str:
    if isinstance(alias, str) and alias.strip():
        return alias.strip()
    raise_api_error(
        status_code=400,
        code="system_config_invalid_smart_routing_policies_json",
        message="smart routing policy alias must be a non-empty string",
        details={"field": "alias"},
    )


def _ensure_policy_object(alias: str, policy: object) -> dict:
    if isinstance(policy, dict):
        return policy
    _raise_smart_routing_policy_error(alias, "policy", f"policy for alias '{alias}' must be an object")
    return {}


def _ensure_strategy(alias: str, policy: dict) -> str:
    strategy = str(policy.get("strategy") or "").strip().lower()
    if strategy in _ALLOWED_STRATEGY:
        return strategy
    _raise_smart_routing_policy_error(
        alias,
        "strategy",
        f"policy for alias '{alias}' has unsupported strategy '{strategy}'",
    )
    return ""


def _validate_stable_candidate(alias: str, policy: dict, strategy: str) -> None:
    stable = policy.get("stable")
    candidate = policy.get("candidate") if strategy != "canary" else policy.get("canary")
    if not isinstance(stable, str) or not stable.strip():
        _raise_smart_routing_policy_error(
            alias,
            "stable",
            f"policy for alias '{alias}' requires non-empty stable",
        )
    if not isinstance(candidate, str) or not candidate.strip():
        candidate_field = "canary" if strategy == "canary" else "candidate"
        _raise_smart_routing_policy_error(
            alias,
            candidate_field,
            f"policy for alias '{alias}' requires non-empty candidate/canary",
        )


def _validate_candidates_list(alias: str, policy: dict) -> None:
    candidates = policy.get("candidates")
    if isinstance(candidates, list) and candidates:
        return
    _raise_smart_routing_policy_error(
        alias,
        "candidates",
        f"policy for alias '{alias}' requires non-empty candidates list",
    )


def _raise_smart_routing_policy_error(alias: str, field: str, message: str) -> None:
    raise_api_error(
        status_code=400,
        code="system_config_invalid_smart_routing_policies_json",
        message=message,
        details={
            "alias": alias,
            "field": field,
            "hint": "Please update inferenceSmartRoutingPoliciesJson",
        },
    )


def validate_smart_routing_policies_json(raw: str) -> None:
    text = (raw or "").strip()
    if not text:
        return
    try:
        parsed = json.loads(text)
    except Exception:
        raise_api_error(
            status_code=400,
            code="system_config_invalid_smart_routing_policies_json",
            message="inferenceSmartRoutingPoliciesJson must be valid JSON",
        )
    if not isinstance(parsed, dict):
        raise_api_error(
            status_code=400,
            code="system_config_invalid_smart_routing_policies_json",
            message="inferenceSmartRoutingPoliciesJson must be an object keyed by model_alias",
        )

    for raw_alias, raw_policy in parsed.items():
        alias = _ensure_alias(raw_alias)
        policy = _ensure_policy_object(alias, raw_policy)
        strategy = _ensure_strategy(alias, policy)
        if strategy in {"blue_green", "canary", "least_loaded_prefer_candidate"}:
            _validate_stable_candidate(alias, policy, strategy)
        if strategy in {"weighted", "least_loaded"}:
            _validate_candidates_list(alias, policy)
