#!/usr/bin/env python3
"""Compare Flow's live model table with MODEL_CONFIG.

Opens Flow headless with an account's managed browser profile (read-only: nothing is
generated), reads the model table the web app loads (RPC HTrJv) and prints what differs from
src/services/generation_handler.py::MODEL_CONFIG.

    .venv/bin/python scripts/flow_catalog.py                  # first account with a ready session
    .venv/bin/python scripts/flow_catalog.py --token-id 4
    .venv/bin/python scripts/flow_catalog.py --save /tmp/htrjv.txt
    .venv/bin/python scripts/flow_catalog.py --response-file /tmp/htrjv.txt   # offline, no browser

The profile must be signed in (admin UI: open the account's browser login first) and not in use
by the server at that moment. Exit status 1 when a reference-image limit differs, a local key is
unknown to Flow, or a retiring family is not tagged locally.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.services.flow_catalog import (  # noqa: E402
    RPC_ID,
    CatalogFormatError,
    compare,
    extract_payload,
    format_report,
    parse_catalog,
)

DB_PATH = ROOT / "data" / "flow.db"
PROFILE_ROOT = ROOT / "data" / "managed_browser_profiles"


def pick_account(token_id):
    conn = sqlite3.connect(DB_PATH)
    try:
        if token_id is None:
            row = conn.execute(
                "SELECT t.id, t.current_project_id FROM tokens t JOIN managed_browser_sessions s ON s.token_id = t.id "
                "WHERE s.status = 'ready' AND t.current_project_id IS NOT NULL ORDER BY t.id LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute("SELECT id, current_project_id FROM tokens WHERE id = ?", (token_id,)).fetchone()
    finally:
        conn.close()
    if not row or not row[1]:
        raise SystemExit("No account with a signed-in managed profile and a project was found.")
    return row[0], row[1]


async def fetch_response(profile: Path, project_id: str, timeout: int) -> str:
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    from playwright.async_api import async_playwright

    options = {"channel": "chrome", "headless": True, "args": ["--restore-last-session"], "timeout": 40000}
    if sys.platform == "darwin":
        # The profile was signed in with ordinary Chrome; Playwright's mock keychain cannot read it.
        options["ignore_default_args"] = ["--use-mock-keychain"]
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(str(profile), **options)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                async with page.expect_response(lambda r: f"rpcids={RPC_ID}" in r.url, timeout=timeout * 1000) as waiting:
                    await page.goto(f"https://flow.google.com/project/{project_id}", wait_until="domcontentloaded")
                response = await waiting.value
            except PlaywrightTimeout:
                hint = " (signed out: log this account in again)" if "/about" in page.url else ""
                raise SystemExit(f"Flow did not load its model table; page is at {page.url[:100]}{hint}")
            return await response.text()
        finally:
            await context.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--token-id", type=int, help="account whose managed profile to use")
    parser.add_argument("--response-file", type=Path, help="read a saved batchexecute response instead of opening Flow")
    parser.add_argument("--save", type=Path, help="write the raw response here")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--timeout", type=int, default=60, help="seconds to wait for the table")
    args = parser.parse_args()

    if args.response_file:
        text = args.response_file.read_text(encoding="utf-8")
    else:
        token_id, project_id = pick_account(args.token_id)
        profile = PROFILE_ROOT / f"token-{token_id}"
        print(f"Using account {token_id}, profile {profile.name}", file=sys.stderr)
        text = asyncio.run(fetch_response(profile, project_id, args.timeout))
    if args.save:
        args.save.write_text(text, encoding="utf-8")

    from src.services.generation_handler import MODEL_CONFIG

    try:
        report = compare(parse_catalog(extract_payload(text)), MODEL_CONFIG)
    except CatalogFormatError as exc:
        raise SystemExit(f"Cannot read Flow's model table: {exc}")
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    failed = report["limit_mismatches"] or report["obsolete_local_keys"] or any(
        row["local_untagged"] for row in report["retiring"]
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
