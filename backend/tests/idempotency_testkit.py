from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Optional

from core.workflows.models.workflow_execution import WorkflowExecution, WorkflowExecutionState


@dataclass
class FakeClaim:
    conflict: bool
    is_new: bool
    record_id: int
    response_ref: Optional[str] = None

    @property
    def record(self) -> SimpleNamespace:
        return SimpleNamespace(id=self.record_id, response_ref=self.response_ref)


class DummyDb:
    def close(self) -> None:
        return None


def build_fixed_idempotency_service(claim: FakeClaim):
    class _FixedIdempotencyService:
        def __init__(self, _db):
            self._db = _db

        def claim(self, **kwargs):
            return claim

    return _FixedIdempotencyService


def build_keyed_hash_idempotency_service(record_id: int = 1):
    class _KeyedHashIdempotencyService:
        _seen: dict[tuple[str, str, str], str] = {}

        def __init__(self, _db):
            self._db = _db

        def claim(self, *, scope, owner_id, key, request_hash, tenant_id=None, ttl_seconds=86400):
            _ = ttl_seconds
            tid = (str(tenant_id or "default").strip() or "default")
            idx = (tid, scope, owner_id, key)
            prev = self._seen.get(idx)
            if prev is None:
                self._seen[idx] = request_hash
                return FakeClaim(conflict=False, is_new=True, record_id=record_id)
            if prev != request_hash:
                return FakeClaim(conflict=True, is_new=False, record_id=record_id)
            return FakeClaim(conflict=False, is_new=False, record_id=record_id)

        def mark_succeeded(self, **kwargs):
            return None

        def mark_failed(self, **kwargs):
            return None

    return _KeyedHashIdempotencyService


def make_workflow_execution_create_stub(execution_id: str):
    def _create_execution(self, request, triggered_by=None):
        return WorkflowExecution(
            execution_id=execution_id,
            workflow_id=request.workflow_id,
            version_id=request.version_id or "v-test",
            state=WorkflowExecutionState.PENDING,
            input_data=request.input_data,
            global_context=request.global_context,
            node_states=[],
            trigger_type=request.trigger_type,
            triggered_by=triggered_by,
        )

    return _create_execution
