# Upstream Omni 1.2 merge implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development to execute independent UI, runtime, and review work while the parent resolves backend conflicts.

**Goal:** Merge upstream `2cf700d` into local main while preserving Vietnamese localization, integration references, managed browser accounts, and Linux VPS deployment.

**Architecture:** Keep the upstream Omni 1.2 catalog and account failover behavior. Resolve conflicts by combining local account error classification and UI capabilities with upstream improvements; retain the existing Python/FastAPI deployment and API compatibility.

**Tech Stack:** Python 3.12, FastAPI, pytest, Playwright, JavaScript, Docker Compose.

## Verification and merge

- [x] Restore a test environment outside Temp and verify the clean original checkout with focused baseline tests.
- [x] Resolve `generation_handler.py` conflicts, retaining content-filter exemptions and upstream quota/risk handling.
- [x] Resolve `static/test.html` and `tests/test_i18n_browser.py`, retaining Vietnamese UI, model categories, and account/browser features; translate new catalog keys.
- [x] Confirm managed browser refresh hooks survive the auto-merged `token_manager.py` and all existing integration/VPS files remain present.
- [x] Verify Omni 1.2 catalog keys, duration/orientation restrictions, legacy aliases, and text/reference submission using isolated tests without paid upstream generation.
- [x] Run the full suite, locale parity, JavaScript syntax, and diff checks; review the merged result.
- [ ] Create the merge commit, fast-forward the original `main`, and clean up the temporary managed worktree.
- [ ] Restart the local service if idle and verify `/v1/models` exposes Omni 1.2; keep all credentials and profiles local.

## Scope limits

Only merged upstream main is included. Open PRs #195/#196 are outside this merge. No push or paid video generation is part of this request.

## Results

- Original clean-checkout baseline: 88 tests passed.
- Exact catalog comparison: all previous 82 public IDs retained, with exactly 22 new Omni 1.2 IDs (104 total).
- Mocked text/reference RPC tests verify `macaron_cookie_t2v_8s`, `macaron_cookie_r2v_15s`, reference images, and portrait orientation.
- Account filtering errors retain the local no-ban policy alongside upstream quota/risk failover.
- Full merged suite: 476 tests and 138 subtests passed, with no skipped tests (200.43 seconds). Existing deprecation warnings remain.
- Browser runs use the installed global Chromium through `PLAYWRIGHT_BROWSERS_PATH`; the stable test environment lives outside Temp.
- Vietnamese/English/Chinese failover notices and nested reasons retain IDs and unknown diagnostics; browser regression tests cover language changes in every direction.
- JavaScript syntax, locale key/placeholder parity, and `git diff --check` passed. Independent review found no remaining merge blockers.
