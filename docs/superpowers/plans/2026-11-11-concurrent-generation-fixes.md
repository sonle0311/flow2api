# Concurrent image/video generation fixes

> **For agentic workers:** Use superpowers:subagent-driven-development for independent implementation chunks. Track acceptance and verification below. The user explicitly requested fixing all ten findings; execute without another approval handoff. Do not commit, push, deploy or call real providers as part of this request.

**Goal:** Fix F01–F10 from `C:/Users/letha/.codex/reviews/flow2api-load-20261111-99cac6ed/review-report.json` while preserving current cache-origin fixes and the unrelated interface drafts.

**Architecture:** Keep existing per-account concurrency and load-balancing components, but acquire actual finite capacity and hold stable ownership through cancellation-safe cleanup. Share same-account validation work, repair browser reservation/rebuild lifecycle, preserve structured provider failures, and move media decoding/writes off the event loop with bounded workers and safe publication.

**Tech stack:** Python3.12, asyncio, FastAPI, curl_cffi, nodriver, SQLite/aiosqlite, pytest and mocked browser/provider transports. Existing worktree/branch remain in place; no framework or datastore replacement.

## Baseline and boundaries

- Existing source changes: `src/api/routes.py`, `tests/test_media_cache_boundary.py` fix the cache request origin. Preserve them.
- Existing untracked `PRODUCT.md` and `design-demos/` are unrelated; do not edit or stage them.
- Python: `C:/Users/letha/.codex/venvs/flow2api-tests/Scripts/python.exe -X utf8 -B`.
- Set `PLAYWRIGHT_BROWSERS_PATH=C:/Users/letha/AppData/Local/ms-playwright` before tests/imports to prevent browser downloads.
- Original load audit has130passing tests/51subtests and synthetic reproductions of all ten findings. Reproduction scripts assert the old defects, so convert their scenarios into positive regression expectations rather than expecting the old scripts to remain green.

## Chunk1 — account dispatch and validation (worker)

Own `src/services/generation_handler.py`, `src/services/token_manager.py`, and concurrency/load-balancer helpers only if required. Create `tests/test_load_generation_limits.py` and `tests/test_load_token_validation.py`; coordinate edits to existing test helpers.

- [x] F01 red: real generation handler + fake providers; finite limit1 never permits more than1 image/video request into provider concurrently. Saturated requests use existing overload response semantics, not an unbounded new queue. Multiple accounts distribute within each capacity; explicit unlimited remains unlimited.
- [x] Implement actual atomic reservations. Avoid counting the same request as both pending and inflight, avoid nested/double acquisition, and release the stable reserved token ID on success, failure, retry/failover, generator close and cancellation.
- [x] F04 red: cancel at the first post-selection log await, then assert pending and inflight are zero and a subsequent request can use the account. Move ownership cleanup before that await; test cancellation during cleanup as well.
- [x] F05 red:25same-account cold-cache/expired-cache validations share one get_credits result and one persistence operation. Use task-owned registry cleanup and shield shared validation from a cancelled waiter; different accounts proceed independently. Preserve credential-change/stale-write safeguards and existing refresh coalescing.
- [x] Run new regressions red/green, token-quota/failover/accounting tests and self-review.

## Chunk2 — personal browser pool lifecycle (worker)

Own `src/services/browser_captcha_personal.py`. Create `tests/test_load_browser_lifecycle.py` using fake nodriver contexts; preserve existing context-isolation fixes and intentional action-shared CAPTCHA pool behavior.

- [x] F02 red: reserve tabA while solve_lock is unlocked; allocation for accountB at capacity must not evict A. Use the common busy predicate and atomic eviction ownership under resident lock; avoid waiting on solve locks while holding the global resident lock.
- [x] F03 red: rebuild an actively solving slot; neither context nor tab may be disposed until the solve owner releases it. Retire the slot from new allocation, then wait for exclusive ownership before disposal.
- [x] F06 red: cancel a rebuild waiter; the shielded rebuild stays tracked until completion, a second waiter reuses it, and shutdown can find it. Task completion owns registry cleanup, including exceptions.
- [x] F07 red: persistent immediate refill failures cannot schedule a tight loop. Use bounded/cancellation-safe failure backoff or the periodic maintainer, preserve successful replenishment and waiter notification.
- [x] Test reservation cancellation/release, shutdown, pool-full waiting and backoff with deterministic events/clocks rather than real browser/network calls; run existing personal-browser/isolation tests.

## Chunk3 — provider overload and CAPTCHA errors (worker)

Own `src/services/flow_client.py` and `src/services/flow_frontend.py`/`flow_current.py` only if needed. Create `tests/test_load_provider_errors.py`.

- [x] F08 red: actual active image/video batchexecute paths receiving HTTP429/503 with HTML/text retain status and reach the intended retry/overload policy. Preserve framed RPC errors, XSRF recovery, cancellation cleanup and uncertain-submission no-resubmit guarantees. Do not blindly retry a possibly accepted paid submission.
- [x] F09 red: terminal getTaskResult errorId/errorCode stops polling immediately and retains the provider cause. Transient processing still polls, success still returns token/UA, and network failures obey existing retry bounds. No new provider calls outside mocks.
- [x] Run new regressions red/green and generation transport/uncertainty/fingerprint tests; self-review exact retry side effects.

## Chunk4 — nonblocking media cache (root)

Own `src/services/file_cache.py`; create `tests/test_load_cache_io.py`.

- [x] F10 red: concurrent cache completions with a controlled slow write must not stop an event-loop heartbeat. Cover image/video base64 and HTTP-download output writes.
- [x] Move the entire decode/write transaction into bounded executor work, preserving filename semantics, safe atomic publication, download deduplication and partial-file cleanup.
- [x] Keep ownership until a running worker stops on cancellation, including repeated cancellation; queued cancelled work must not publish a late final file or leak worker slots. Protect staging paths from concurrent cache cleanup.
- [x] Run new regressions red/green and existing file-cache cancellation/cleanup tests.

## Integration and completion

- [x] Root inspects every worker diff and checks every F01–F10 criterion; request separate spec and quality reviews with no code edits by reviewers.
- [x] Resolve any integration failures without removing meaningful assertions or weakening limits.
- [x] Run the complete local pytest suite once sources are integrated; avoid live accounts, actual CAPTCHA solves or real generation.
- [x] Confirm `git diff --check`, source syntax as appropriate, and final source snapshot. Record exact test counts and any remaining live-VPS benchmark limitation in an external fix report beside the original review.
- [x] Report completed behavior and evidence. Do not claim measured RPS or deploy/restart another checkout's server.

## Final verification — 2026-11-11

- All ten findings fixed; separate spec reviews and a final independent quality review approved the integrated source.
- Added endpoint-level SSE ownership regressions for both protocols, including send failure, disconnect and repeated cancellation. Quality follow-ups also cover stable browser reservation ownership and accepted RPC payloads on HTTP error statuses.
- Full local suite on frozen source: **655 tests and 261 subtests passed**, 169 existing dependency deprecation warnings, 418.88 seconds.
- Final independent focused review: **107 tests and 94 subtests passed**; no remaining actionable findings.
- API/dispatch/cache-origin integration subset: **56 tests and 12 subtests passed**.
- All 17 changed Python source/test files parsed; their hashes remained unchanged through the full suite. Whitespace validation passed.
- External evidence: `C:/Users/letha/.codex/reviews/flow2api-load-20261111-99cac6ed/fix-report.json`, `fix-full-suite.log` and `fix-source-snapshot.json`.
- Tests used synthetic provider/browser transports. No live VPS throughput benchmark, generation, deployment, server restart, commit or push was performed. Existing cache-origin changes and UI drafts were preserved.
