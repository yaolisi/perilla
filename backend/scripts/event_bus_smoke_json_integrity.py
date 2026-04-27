from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_json_sha256(payload: dict[str, Any]) -> str:
    canonical = canonical_json_dumps(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
