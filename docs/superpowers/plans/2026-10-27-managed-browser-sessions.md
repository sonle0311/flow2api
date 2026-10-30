# Managed browser sessions implementation plan

> **For agentic workers:** Use subagent-driven-development for the independent service, interface and contract documentation tasks. Preserve the existing uncommitted translations and integration guide.

**Goal:** Let an administrator open a dedicated browser for an account, sign in manually once, and automatically synchronize validated Flow cookies from its persistent profile.

**Architecture:** A separate managed-browser service owns persistent profiles and metadata, independent of CAPTCHA services. The token manager validates cookies with the existing Flow RPC and serializes saves; its existing minute scheduler triggers due profile refreshes. Admin-only routes expose sanitized status and actions, and a translated dialog provides login, sync and stop controls.

**Tech stack:** FastAPI, SQLite/aiosqlite, Playwright persistent Chromium contexts, existing vanilla JavaScript/i18n, pytest and Playwright browser tests.

### Task 1: Persistent browser service

- [x] Add failing tests with fake browser contexts and temporary databases for profile isolation, correct identity, login polling, restart persistence, refresh intervals, stopped sessions and cleanup.
- [x] Implement `src/services/managed_browser.py` and `tests/test_managed_browser.py`. Store metadata in a separate table and profiles below ignored `data/managed_browser_profiles/`.
- [x] Keep login headed and explicitly triggered. Background checks never open windows or reenable accounts. Preserve profiles when stopping or shutting down.

### Task 2: Token lifecycle and authenticated API

- [x] Add failing tests in `tests/test_managed_browser_api.py` and `tests/test_managed_browser_tokens.py` for authorization, status/actions, strict identity, validation-before-save, explicit recovery and scheduler integration.
- [x] Add `src/api/browser_sessions.py`, lifecycle/static route registration in `src/main.py`, and targeted token-manager integration.
- [x] Use the token refresh lock around validation/save and existing compare-and-set cookie writes. Avoid acquiring this lock before calling the browser service.
- [x] Expose only enum errors and status metadata; no cookies, credentials or profile paths. Close managed runtime before deleting accounts.

### Task 3: Translated account dialog

- [x] Add browser tests for login/status transitions, missing sessions, failures, stopping and polling cleanup.
- [x] Add `static/managed-browser.js`, account action/modal in `static/manage.html`, and complete zh/en/vi strings in the manage catalog.
- [x] Show server-machine browser behavior, independent CAPTCHA operation, persistent profiles and manual reauthentication requirements. Refresh account state after explicit recovery.

### Task 4: Documentation and verification

- [x] Document every new route in the integration reference and usage in README; add the approved design document.
- [x] Run focused service/API/token/UI tests, cookie refresh regressions, catalog parity and exhaustive reference checks.
- [x] Review concurrency, identity isolation, browser cleanup and sanitized responses with a separate reviewer. Address findings.
- [x] Run the relevant full suite, restart local server and verify the real admin UI without opening a Google login or changing account credentials automatically.

The user approved the feature and proposed workflow before this plan. Do not commit or push the combined working tree unless requested.

## Verification evidence

- Full repository suite: 342 passed and 125 subtests passed before the final lifecycle regression additions.
- Focused managed service/token/API/UI suite after the final control-lock, shutdown and identity fixes: 50 passed.
- Catalog parity and exhaustive integration reference: 33 passed.
- Real headless Chrome: a synthetic expiryless loopback cookie survives clean profile close/reopen; no Google login was performed.
- Live local admin console on port 8000: Vietnamese dialog and real status API verified, zero JavaScript errors, no login/profile-launch requests and no account-credential changes.
- Local server was restarted successfully. Initial combined restart command was rejected; stopping only the verified server PID and launching it separately succeeded.
