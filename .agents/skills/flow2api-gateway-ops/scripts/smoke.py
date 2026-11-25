#!/usr/bin/env python3
"""Free smoke check of the running gateway: no generation, no credits, no secrets printed.

    .venv/bin/python3.11 .agents/skills/flow2api-gateway-ops/scripts/smoke.py [--base URL] [--db PATH] [--json]

Checks, in order: GET /health; GET /v1/models with the master key read from the database
(admin_config.api_key, never printed) and that Omni and Gemini image models are listed.
Exit status 0 = all passed, 1 = a check failed, 2 = could not run (no database or key).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def fetch(url: str, key: str | None = None, timeout: float = 10.0):
    request = urllib.request.Request(url)
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, str(exc).encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--db", default=str(ROOT / "data" / "flow.db"))
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    args = parser.parse_args()

    try:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=5)
        row = conn.execute("SELECT api_key FROM admin_config LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        print(f"cannot read {args.db}: {exc}", file=sys.stderr)
        return 2
    if not row or not row[0]:
        print("no master API key in admin_config; cannot call /v1/models", file=sys.stderr)
        return 2

    base = args.base.rstrip("/")
    checks = []

    status, _ = fetch(f"{base}/health")
    checks.append({"check": "health", "ok": status == 200, "detail": f"HTTP {status}"})

    status, body = fetch(f"{base}/v1/models", key=row[0])
    ids: list[str] = []
    if status == 200:
        try:
            ids = [item["id"] for item in json.loads(body).get("data", [])]
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
    checks.append({"check": "models listed", "ok": status == 200 and bool(ids), "detail": f"HTTP {status}, {len(ids)} models"})
    for prefix in ("omni-1.2-flash", "gemini-"):
        found = sum(1 for model in ids if model.startswith(prefix))
        checks.append({"check": f"models starting with {prefix}", "ok": found > 0, "detail": str(found)})

    ok = all(item["ok"] for item in checks)
    if args.json:
        print(json.dumps({"ok": ok, "checks": checks}))
    else:
        for item in checks:
            print(f"{'PASS' if item['ok'] else 'FAIL'}  {item['check']}: {item['detail']}")
        print("RESULT:", "all passed" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
