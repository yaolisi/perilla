"""
V2.8 Inference Gateway Layer - Model Router

Resolves model_alias to (provider, model_id) with fallback support.
"""
from typing import Any, Optional
from dataclasses import dataclass
import hashlib
import json
from log import logger
from core.runtime.manager.runtime_metrics import get_runtime_metrics
from core.system.runtime_settings import (
    get_inference_smart_routing_enabled,
    get_inference_smart_routing_policies_json,
)

from core.inference.registry.model_registry import (
    InferenceModelRegistry,
    ModelAlias,
    get_inference_model_registry,
)


@dataclass
class RoutingResult:
    """
    Result of model alias resolution.
    
    Attributes:
        alias: The resolved ModelAlias (None if direct passthrough)
        provider: Provider name (e.g., 'openai', 'ollama')
        model_id: Concrete model ID to use
        resolved_via: How the resolution was done ('alias', 'direct', 'fallback')
    """
    alias: Optional[ModelAlias]
    provider: str
    model_id: str
    resolved_via: str  # "alias", "direct", "fallback"


class ModelRouter:
    """
    Resolves model_alias to (provider, model_id).
    
    Resolution order:
    1. Exact alias match (if enabled)
    2. Fallback chain (if alias has fallback)
    3. Direct passthrough (treat alias as model_id)
    
    Usage:
        router = ModelRouter()
        result = router.resolve("reasoning-model")
        print(f"Provider: {result.provider}, Model: {result.model_id}")
    """
    
    def __init__(self, registry: Optional[InferenceModelRegistry] = None):
        self.registry = registry or get_inference_model_registry()

    @staticmethod
    def _to_ratio(percent: Any, default_ratio: float = 0.0) -> float:
        try:
            p = float(percent)
        except Exception:
            return default_ratio
        return max(0.0, min(1.0, p / 100.0))

    @staticmethod
    def _deterministic_bucket(seed: str) -> float:
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        value = int(digest[:8], 16)
        return value / 0xFFFFFFFF

    @staticmethod
    def _routing_seed(model_alias: str, metadata: Optional[dict[str, Any]]) -> str:
        meta = metadata or {}
        for key in ("routing_key", "request_id", "trace_id", "session_id", "user_id", "x_user_id"):
            val = meta.get(key)
            if isinstance(val, str) and val.strip():
                return f"{model_alias}:{val.strip()}"
        return f"{model_alias}:default"

    @staticmethod
    def _queue_size(model_id: str) -> int:
        metrics = get_runtime_metrics().get_model_metrics(model_id) or {}
        try:
            return max(0, int(metrics.get("queue_size", 0) or 0))
        except Exception:
            return 0

    def _load_policy(self, model_alias: str) -> Optional[dict[str, Any]]:
        if not get_inference_smart_routing_enabled():
            return None
        raw = get_inference_smart_routing_policies_json().strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except Exception:
            logger.warning("[ModelRouter] invalid inference_smart_routing_policies_json")
            return None
        if not isinstance(data, dict):
            return None
        policy = data.get(model_alias)
        return policy if isinstance(policy, dict) else None

    @staticmethod
    def _has_cycle(visited: set[str], current: str, source: str) -> bool:
        if current in visited:
            logger.warning(f"[ModelRouter] Circular fallback detected for '{source}'")
            return True
        return False

    def _resolve_alias_or_direct(self, target: str, max_depth: int = 10) -> RoutingResult:
        result = self.resolve(target, max_depth=max_depth, request_metadata=None, _skip_policy=True)
        return result

    def _apply_smart_policy(
        self,
        model_alias: str,
        request_metadata: Optional[dict[str, Any]],
    ) -> Optional[RoutingResult]:
        policy = self._load_policy(model_alias)
        if not policy:
            return None

        strategy = str(policy.get("strategy") or "none").strip().lower()
        seed = self._routing_seed(model_alias, request_metadata)
        role = str((request_metadata or {}).get("role") or "").strip().lower()
        is_admin = bool((request_metadata or {}).get("is_admin")) or role == "admin"

        if strategy == "blue_green":
            return self._route_blue_green(policy, seed, is_admin)
        if strategy == "canary":
            return self._route_canary(policy, seed, is_admin)
        if strategy == "weighted":
            return self._route_weighted(policy, seed)
        if strategy == "least_loaded":
            return self._route_least_loaded(policy)
        if strategy == "least_loaded_prefer_candidate":
            return self._route_least_loaded_prefer_candidate(policy, is_admin)

        return None

    def _route_blue_green(self, policy: dict[str, Any], seed: str, is_admin: bool) -> Optional[RoutingResult]:
        stable = str(policy.get("stable") or "").strip()
        candidate = str(policy.get("candidate") or "").strip()
        if not stable or not candidate:
            return None
        candidate_ratio = self._to_ratio(policy.get("candidate_percent", 0), 0.0)
        if is_admin:
            pick = stable
        else:
            pick = candidate if self._deterministic_bucket(seed) < candidate_ratio else stable
        chosen = self._resolve_alias_or_direct(pick)
        chosen.resolved_via = f"{chosen.resolved_via}+blue_green"
        return chosen

    def _route_canary(self, policy: dict[str, Any], seed: str, is_admin: bool) -> Optional[RoutingResult]:
        stable = str(policy.get("stable") or "").strip()
        canary = str(policy.get("canary") or "").strip()
        if not stable or not canary:
            return None
        canary_ratio = self._to_ratio(policy.get("canary_percent", 10), 0.1)
        if is_admin:
            pick = stable
        else:
            pick = canary if self._deterministic_bucket(seed) < canary_ratio else stable
        chosen = self._resolve_alias_or_direct(pick)
        chosen.resolved_via = f"{chosen.resolved_via}+canary"
        return chosen

    def _route_weighted(self, policy: dict[str, Any], seed: str) -> Optional[RoutingResult]:
        valid = self._parse_weighted_candidates(policy)
        if not valid:
            return None
        total = sum(w for _, w in valid)
        bucket = self._deterministic_bucket(seed) * total
        cursor = 0.0
        pick = valid[-1][0]
        for target, w in valid:
            cursor += w
            if bucket <= cursor:
                pick = target
                break
        chosen = self._resolve_alias_or_direct(pick)
        chosen.resolved_via = f"{chosen.resolved_via}+weighted"
        return chosen

    @staticmethod
    def _parse_weighted_candidates(policy: dict[str, Any]) -> list[tuple[str, float]]:
        candidates = policy.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return []
        valid: list[tuple[str, float]] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            target = str(item.get("target") or item.get("model_id") or "").strip()
            if not target:
                continue
            try:
                weight = float(item.get("weight", 0))
            except Exception:
                continue
            if weight > 0:
                valid.append((target, weight))
        return valid

    def _route_least_loaded(self, policy: dict[str, Any]) -> Optional[RoutingResult]:
        candidates = policy.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return None
        resolved: list[RoutingResult] = []
        for target in candidates:
            if not isinstance(target, str) or not target.strip():
                continue
            resolved.append(self._resolve_alias_or_direct(target.strip()))
        if not resolved:
            return None
        resolved.sort(key=lambda x: self._queue_size(x.model_id))
        chosen = resolved[0]
        chosen.resolved_via = f"{chosen.resolved_via}+least_loaded"
        return chosen

    def _route_least_loaded_prefer_candidate(
        self, policy: dict[str, Any], is_admin: bool
    ) -> Optional[RoutingResult]:
        stable = str(policy.get("stable") or "").strip()
        candidate = str(policy.get("candidate") or "").strip()
        if not stable or not candidate:
            return None
        stable_r = self._resolve_alias_or_direct(stable)
        candidate_r = self._resolve_alias_or_direct(candidate)
        stable_q = self._queue_size(stable_r.model_id)
        candidate_q = self._queue_size(candidate_r.model_id)
        threshold = max(0, int(policy.get("candidate_max_extra_queue", 1) or 1))
        if is_admin or candidate_q > stable_q + threshold:
            stable_r.resolved_via = f"{stable_r.resolved_via}+least_loaded_prefer_candidate"
            return stable_r
        candidate_r.resolved_via = f"{candidate_r.resolved_via}+least_loaded_prefer_candidate"
        return candidate_r

    def resolve(
        self,
        model_alias: str,
        max_depth: int = 10,
        request_metadata: Optional[dict[str, Any]] = None,
        _skip_policy: bool = False,
    ) -> RoutingResult:
        """
        Resolve an alias to provider + model_id.
        
        Args:
            model_alias: The alias to resolve
            
        Returns:
            RoutingResult with resolution details
        """
        visited = set()
        current = model_alias
        for _ in range(max_depth):
            if self._has_cycle(visited, current, model_alias):
                break
            visited.add(current)

            alias = self.registry.resolve(current)
            if not alias:
                break
            if alias.enabled:
                return self._resolve_enabled_alias(
                    model_alias=model_alias,
                    alias=alias,
                    request_metadata=request_metadata,
                    skip_policy=_skip_policy,
                )
            if not alias.fallback:
                break
            logger.info(
                f"[ModelRouter] Alias '{current}' disabled, trying fallback '{alias.fallback}'"
            )
            current = alias.fallback
        
        # 3. Direct passthrough - treat alias as model_id
        # This allows backward compatibility with existing model_ids
        logger.debug(
            f"[ModelRouter] No alias found for '{model_alias}', "
            f"using as direct model_id"
        )
        return RoutingResult(
            alias=None,
            provider="auto",  # Let existing system determine provider
            model_id=current,
            resolved_via="direct"
        )

    def _resolve_enabled_alias(
        self,
        *,
        model_alias: str,
        alias: ModelAlias,
        request_metadata: Optional[dict[str, Any]],
        skip_policy: bool,
    ) -> RoutingResult:
        base_result = RoutingResult(
            alias=alias,
            provider=alias.provider,
            model_id=alias.model_id,
            resolved_via="alias",
        )
        if skip_policy:
            return base_result
        policy_result = self._apply_smart_policy(model_alias, request_metadata)
        if policy_result is not None:
            return policy_result
        return base_result
    
    def resolve_with_fallback_chain(
        self,
        model_alias: str,
        max_depth: int = 5
    ) -> RoutingResult:
        """
        Resolve with explicit fallback chain tracking.
        
        Args:
            model_alias: The alias to resolve
            max_depth: Maximum fallback depth to prevent infinite loops
            
        Returns:
            RoutingResult with resolution details
        """
        visited = set()
        current_alias = model_alias
        
        for _ in range(max_depth):
            if current_alias in visited:
                logger.warning(
                    f"[ModelRouter] Circular fallback detected for '{model_alias}'"
                )
                break
            
            visited.add(current_alias)
            result = self.resolve(current_alias)
            
            if result.resolved_via != "fallback":
                return result
            
            # Continue with fallback
            alias = self.registry.resolve(current_alias)
            if alias and alias.fallback:
                current_alias = alias.fallback
            else:
                break
        
        # Final resolution
        return self.resolve(current_alias)
    
    def list_available_models(self) -> list:
        """
        List all available model aliases.
        
        Returns:
            List of alias names that can be resolved
        """
        return self.registry.list_aliases()
    
    def is_alias_registered(self, alias_name: str) -> bool:
        """Check if an alias is registered"""
        return self.registry.resolve(alias_name) is not None
