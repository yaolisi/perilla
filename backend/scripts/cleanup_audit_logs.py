"""
Cleanup audit logs by retention days.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from core.data.base import db_session
from core.data.models.audit import AuditLogORM


def run_cleanup(retention_days: int, dry_run: bool = True) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))
    with db_session() as db:
        q = db.query(AuditLogORM).filter(AuditLogORM.created_at < cutoff)
        count = int(q.count() or 0)
        if not dry_run and count > 0:
            q.delete(synchronize_session=False)
    return count


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--retention-days", type=int, default=30)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    n = run_cleanup(args.retention_days, dry_run=args.dry_run)
    print({"deleted_or_candidates": n, "dry_run": bool(args.dry_run)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
