"""
Storage strategy helpers for production readiness.
"""
from __future__ import annotations

from typing import Dict


def detect_storage_backend(db_path: str) -> str:
    p = (db_path or "").lower()
    if p.startswith("postgresql://") or p.startswith("postgres://"):
        return "postgresql"
    if p.startswith("mysql://"):
        return "mysql"
    return "sqlite"


def storage_readiness(db_path: str) -> Dict[str, str]:
    backend = detect_storage_backend(db_path)
    if backend == "sqlite":
        return {
            "backend": backend,
            "level": "dev",
            "advice": "For production HA, migrate to PostgreSQL and enable backup drills.",
        }
    return {"backend": backend, "level": "prod-ready", "advice": "Ensure PITR backup and replica monitoring are enabled."}
