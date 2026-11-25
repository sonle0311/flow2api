#!/usr/bin/env python3
"""Read-only state check before a restart or a debugging session.

    .venv/bin/python3.11 .agents/skills/flow2api-maintainer/scripts/preflight.py [--db data/flow.db]

Prints: in-flight requests, active jobs, the latest requests, each account's login state.
Never prints secrets (no tokens, cookies, keys). Exit status 0 = idle (safe to restart),
1 = something is running, 2 = the database could not be read.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def _when(value) -> str:
    """Jobs store epoch seconds, request logs a UTC text timestamp."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(ROOT / "data" / "flow.db"))
    args = parser.parse_args()

    try:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        in_flight = conn.execute(
            "SELECT id, token_id, operation, progress, created_at FROM request_logs "
            "WHERE progress < 100 AND (status_code IS NULL OR status_code = 0) ORDER BY id"
        ).fetchall()
        jobs = conn.execute(
            "SELECT id, model, status, created_at FROM jobs WHERE status IN ('queued', 'running') ORDER BY created_at"
        ).fetchall()
        recent = conn.execute(
            "SELECT id, token_id, operation, status_code, progress, created_at FROM request_logs ORDER BY id DESC LIMIT 5"
        ).fetchall()
        accounts = conn.execute(
            "SELECT t.id, t.email, t.is_active, t.credits, t.user_paygate_tier, "
            "COALESCE(m.status, '-') AS session, COALESCE(m.error_code, '') AS error "
            "FROM tokens t LEFT JOIN managed_browser_sessions m ON m.token_id = t.id ORDER BY t.id"
        ).fetchall()
    except sqlite3.Error as exc:
        print(f"cannot read {args.db}: {exc}", file=sys.stderr)
        return 2

    print(f"in-flight requests: {len(in_flight)}")
    for row in in_flight:
        print(f"  #{row['id']} token={row['token_id']} {row['operation']} progress={row['progress']} since {row['created_at']}")
    print(f"active jobs: {len(jobs)}")
    for row in jobs:
        print(f"  {row['id']} {row['model']} {row['status']} since {_when(row['created_at'])}")
    print("latest requests (UTC):")
    for row in recent:
        print(f"  #{row['id']} token={row['token_id']} {row['operation']} status={row['status_code']} progress={row['progress']} {row['created_at']}")
    print("accounts:")
    for row in accounts:
        active = "active" if row["is_active"] else "disabled"
        print(
            f"  token={row['id']} {row['email']} {active} credits={row['credits']} "
            f"tier={row['user_paygate_tier']} session={row['session']} {row['error']}".rstrip()
        )

    idle = not in_flight and not jobs
    print("RESULT:", "idle, safe to restart" if idle else "BUSY, do not restart")
    return 0 if idle else 1


if __name__ == "__main__":
    raise SystemExit(main())
