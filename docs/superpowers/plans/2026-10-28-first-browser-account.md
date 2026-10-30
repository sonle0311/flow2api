# First account through browser login

**Goal:** Let a user open the sign-in browser when the account list is empty, supplying only their Google email.

**Architecture:** An admin-only email endpoint prepares a disabled pending account and starts the existing normal-browser login workflow. No cookie, password, Flow RPC or project creation is needed to prepare it. The existing strict identity and Flow RPC checks activate it only after successful manual sign-in. An existing email reuses its account without changing its settings. Flow projects continue to be created lazily on the first generation.

- [x] Add failing tests for empty database, input validation, concurrent duplicate prevention, existing account reuse, authenticated launch, response filtering and origin protection.
- [x] Implement TokenManager.prepare_browser_account and POST /api/browser-sessions/accounts, registering concurrency only for new drafts.
- [x] Add an always-visible toolbar action and empty state, an accessible email-only form, pending status and translated UI tests.
- [x] Document endpoint and approved design, review pending-account safety, and run relevant regressions.
- [x] Restart local safely and verify the real UI with existing accounts, plus an empty-list browser test. Do not create fake live accounts or interrupt a manual Google login silently.

Preserve all existing local changes and browser profiles. No commit or push was requested.

## Verification evidence

- Full repository suite: 388 passed, 130 subtests passed.
- Independent review: three rounds of twelve concurrent callers on separate SQLite connections created one inactive draft each; strict identity, pending-enable protection and existing-account preservation approved.
- Live local UI: global action and email-only dialog work in Vietnamese; an intercepted empty account list also shows the action. No account-creation request was sent and existing live records stayed unchanged.
- Local server restarted on port 8000 and health check passed with the existing account still active.
- JavaScript syntax, Python compilation and git diff checks passed.
