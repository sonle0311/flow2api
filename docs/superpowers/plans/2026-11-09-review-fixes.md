# Review Findings Remediation Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Follow the existing review evidence and add a failing regression before each production fix.

**Goal:** Resolve all 15 findings from the OCR delegate review of commit `138fa15`, while retaining Vietnamese localization, Omni 1.2, managed login and VPS support.

**Architecture:** Keep the current FastAPI/service/browser boundaries. Repair the faulty control flow at its owner; use synthetic providers, temporary databases and isolated browser contexts for verification. Work in the existing dedicated Codex worktree; do not modify the separate running checkout or its accounts.

**Tech Stack:** Python, FastAPI, SQLite/aiosqlite, curl_cffi, nodriver, Playwright, vanilla JavaScript, pytest/unittest.

Review input: `C:/Users/letha/.codex/reviews/flow2api-20261109-138fa15/review-report.json` (F01–F15).

## Chunk 1: API and test interface (root)

**Files:** `src/api/routes.py`, `static/test.html`; new focused cache/security and browser UI regression tests under `tests/`.

- [x] F01: Reproduce cache-boundary violations using temporary synthetic files. Resolve local cache references only within the cache directory, reject traversal/symlink escapes and malformed forwarded authorities; preserve valid generated media URLs and proxy deployments.
- [x] F14: Reproduce a batch exceeding the model image limit. Reserve available image slots before asynchronous reads; preserve selected order and discard callbacks belonging to an old model selection.
- [x] F15: Reproduce HTTP 200 SSE errors and truncated streams. Treat them as failed results, preserve visible diagnostics, and require completed framing plus final media content before rendering success.
- [x] Run each new test before and after its fix; run relevant existing API/i18n/UI tests.

## Chunk 2: Browser and CAPTCHA isolation (browser worker)

**Files:** `src/services/browser_captcha_personal.py`, `src/services/recaptcha_runtime.py`; corresponding regression tests.

- [x] F02: Prove that two headed resident accounts have distinct cookie stores. Use isolated browser contexts for account-bound tabs in headed and headless modes; ensure cookie set/read/clear operations and teardown use those context IDs. Retain the separate manual human-login workflow.
- [x] F05: Reproduce a missing bound execute capture on a non-empty document. Try the available execute safely; if rendering is necessary, use a dedicated empty element and retain correct action handling, timeout and cleanup.
- [x] Run new tests red/green and existing browser/personal/recaptcha tests. No external CAPTCHA calls or real profiles.

## Chunk 3: Generation and cache (generation worker)

**Files:** `src/services/flow_client.py`, `src/services/flow_current.py`, `src/services/file_cache.py`, `src/services/generation_handler.py`; focused generation regressions.

- [x] F03: Exercise the real mutating RPC transport with an ambiguous post-send timeout. Preserve an uncertainty marker/cause through wrappers and stop image/video resubmission; keep safe bootstrap/pre-submission retries working.
- [x] F04: Separate entitlement from credit balance. Use actual tier metadata when available; represent unknown entitlement without inventing Free/Pro. Coordinate token-manager persistence semantics with the account worker; verified tiers must survive balance-only responses and new accounts must not gain unverified Ultra rights.
- [x] F08: Reproduce event-loop blocking by fallback downloads. Offload bounded subprocess execution or use asynchronous subprocesses without changing proxy, timeout or cleanup behavior.
- [x] F09: Exercise the direct-media video branch and assert exactly one successful usage/statistics update per logical request.
- [x] F10: Exercise original generation followed by upscale. Carry the original persisted task identity through polling and finalize its actual outcome and delivered URL.
- [x] Run new tests red/green and existing Omni, rollout, failover, asset-resolution and video tests.

## Chunk 4: Accounts and administration (account worker)

**Files:** `src/services/token_manager.py`, `src/core/database.py`, `src/api/admin.py`; focused account/config regression tests.

- [x] F06: An ordinary metadata edit must preserve manual disabled state and ban metadata; explicit login/plugin reactivation stays controlled by its existing intent/flag.
- [x] F07: CapSolver connectivity-only diagnostics return no fabricated score/status. Return `score: null` and an explicit unverified/connectivity-only state; retain normal verified score results.
- [x] F11: Shield shared refresh tasks from individual waiters' cancellation. Preserve deliberate task cancellation when deleting an account.
- [x] F12: Increment usage atomically in SQLite alongside last-used time; exercise repeated and concurrent updates.
- [x] F13: Distinguish synthetic frontend expiry from actual expired credentials during 429 recovery. Revalidate Cookie sessions after the cooldown, retain bans when login is invalid and respect manual disable rules.
- [x] Coordinate balance-only tier persistence with Chunk 3; no writes to its owned Flow client files.
- [x] Run each regression red/green and existing token-refresh, managed-browser, plugin, quota and daily-stat tests.

## Chunk 5: Integration and verification (root and reviewers)

- [x] Check every F01–F15 acceptance criterion against the resulting code and tests.
- [x] Perform an independent spec review, then a quality/security review of the integrated diff. Address actionable regressions before completion.
- [x] Run the complete local suite with `PLAYWRIGHT_BROWSERS_PATH=C:/Users/letha/AppData/Local/ms-playwright` using `C:/Users/letha/.codex/venvs/flow2api-tests/Scripts/python.exe -X utf8 -B -m pytest -q`.
- [x] Check diff whitespace, Python/JavaScript syntax as appropriate and Git status; record exact verification evidence.
- [x] Report results and remaining live-provider/VPS verification limits. Do not push or deploy as part of this fix request.

The user has authorized implementation of all findings; execute this plan directly without an additional approval handoff. No source-of-truth harness files exist in this application checkout, so preserve its existing implementation/testing workflow rather than creating an unrelated harness.

## Final verification

- Full frozen-source suite: **562 passed, 211 subtests passed, 0 failed, 0 skipped** in 254.09 seconds.
- Existing dependency deprecations: 160 warnings (SQLite datetime adapters and Starlette/AnyIO).
- Command: `PLAYWRIGHT_BROWSERS_PATH=C:/Users/letha/AppData/Local/ms-playwright C:/Users/letha/.codex/venvs/flow2api-tests/Scripts/python.exe -X utf8 -B -m pytest -q --tb=short`.
- All fifteen acceptance criteria passed independent spec review. Independent quality review approved the final uncertainty, entitlement and download-lifecycle follow-ups; its account/generation check passed 36 tests and 69 subtests.
- Changed Python modules parse; six inline JavaScript blocks pass Node syntax checks; translation key parity and Git whitespace checks pass.
- Validation used synthetic responses, isolated Chromium contexts and temporary SQLite databases. No paid generation, real account/profile mutation or VPS deployment was performed.
- Unknown account entitlement is stored as null and displayed as Unknown, with conservative premium-model filtering. Historical credit-inferred tiers cannot be independently repaired without actual provider entitlement metadata.
- Work remains in the current Codex worktree for review; no commit, push, merge or server restart was performed.
