# Managed browser sessions for Flow accounts

## Approved behavior

The user approved a per-account browser login button, a persistent isolated profile, automatic cookie synchronization, and a clear request to log in again when Google invalidates the session. Browser session management is independent of the CAPTCHA provider: existing `yescaptcha`, `browser`, `personal` or other CAPTCHA settings do not need to change.

## User flow

1. Open the browser-session dialog for an existing account.
2. Choose **Open browser to sign in**. A normal installed Chrome/Edge window opens on the computer running Flow2API, using the account's dedicated profile.
3. Complete Google/Flow login and any verification manually, then close all windows of this dedicated profile. The browser runs without automation or a remote debugging connection during sign-in. Flow2API does not type, capture or return the Google password.
4. After the normal browser exits, the bounded login watcher opens the profile in the background and reads the signed-in Flow identity. It saves cookies only when the identity matches the selected account and a current Flow RPC validates the session.
5. Explicit login success can reactivate the selected account. A background refresh must not reactivate an account that an administrator disabled.
6. Subsequent checks reuse the saved profile. A closed profile may be opened in a temporary headless context, synchronized and closed again.
7. An expired or revoked session shows **Needs login**. The application does not open unexpected background login windows or attempt to bypass Google verification.
8. **Stop synchronization** closes the account window, cancels pending login monitoring and disables this managed profile's scheduled synchronization. It retains the profile for a later explicit login.

## Components and ownership

- `src/services/managed_browser.py`: profile ownership, runtime contexts, bounded login watching, status persistence, scheduled checks and sanitized failure codes.
- `src/services/manual_login_browser.py`: locates installed Chrome/Edge and launches an ordinary dedicated-profile process without CDP or automation controls during human sign-in.
- Existing `TokenManager`: a dedicated save method uses the account refresh lock, checks identity again, validates current Flow RPC and commits cookie/access metadata. Existing manual cookie-import behavior is unchanged.
- Admin API: session status, explicit login, synchronize now and stop operations, all protected by the current admin session dependency.
- Application lifespan: initialize metadata, run the periodic managed-profile check and close service-owned contexts on shutdown.
- `static/managed-browser.js` and the management dialog: translated controls, status polling while visible and explicit user actions. No browser launches on page view.
- `src/core/integration_docs.py`: translated operation descriptions and representative response shapes, included by the existing exhaustive integration reference.

## Persistence and isolation

Profiles live under `data/managed_browser_profiles/token-{id}` with a fixed server-generated account ID; the request cannot choose a filesystem path. The existing `data` Git exclusion keeps browser credentials out of commits. Profiles contain sensitive session material and should be covered by the same access controls and backup policy as the local account database.

Chrome starts with session restoration enabled so expiryless cookies survive a clean browser close and reopen. A real-browser test verifies this using a synthetic loopback cookie, without signing in to Google. Control actions use a separate account lock from the long-running login watcher, allowing stop/shutdown to interrupt login while preventing a queued action from reopening the browser afterward.

Managed cookie commits atomically require the original cookie snapshot, email and login account to remain unchanged. Editing an account identity during the validation RPC therefore rejects the old profile's cookie candidate.

A separate `managed_browser_sessions` SQLite table stores only scheduling and status metadata, with a foreign key to `tokens(id)` and `ON DELETE CASCADE`. Status metadata includes enabled state, status, last synchronization/attempt times and a sanitized error code. The public status excludes cookies, passwords, proxy credentials, filesystem paths and exception text.

One account can own at most one active profile context. Account-level locks prevent simultaneous login/synchronization from opening the same profile twice or racing a cookie commit. Each managed profile is separate from the CAPTCHA runtime profiles and other accounts. The profile is never seeded with another account's cookies.

Account deletion first cancels/closes service-owned runtime resources; metadata is removed with the account. This version retains the on-disk profile rather than introducing automatic recursive deletion. Profile retention is distinct from Google logout.

## Scheduling and lifecycle

The scheduler observes all three opt-ins: the global protocol/session refresh switch, the account's auto-refresh switch, and the managed profile's enabled flag. It uses the account interval, normally 30 minutes, and a failure backoff to avoid repeated immediate retries. A disabled account can still have its managed profile checked to diagnose/recover login state, but background synchronization never re-enables the account.

Initialization does not launch a browser. Explicit login launches a headed window; the login watcher is bounded to ten minutes. A global shutdown cancels watchers, closes contexts and stops the Playwright runtime while preserving persisted profiles/settings. Restarted status must reflect the actual absence of an open runtime window rather than a stale in-progress state.

The browser uses the account request proxy, falling back to the configured global request proxy. Proxy credentials are internal launch options and must not appear in status or logs.

## API contract

All account operations require a live admin session. Missing accounts return HTTP 404. Requests do not accept Google passwords, profile paths or cookie payloads.

| Method and path | Behavior |
| --- | --- |
| `GET /api/tokens/{token_id}/browser-session` | Inspect status without launching a browser. |
| `POST /api/tokens/{token_id}/browser-session/login` | Begin explicit browser login asynchronously. |
| `POST /api/tokens/{token_id}/browser-session/sync` | Synchronize the managed profile now. |
| `POST /api/tokens/{token_id}/browser-session/stop` | Disable scheduled profile synchronization and close the context. |
| `GET /static/managed-browser.js` | Public interface asset; contains no runtime credentials. |

Representative response:

```json
{
  "success": true,
  "session": {
    "token_id": 1,
    "enabled": true,
    "status": "ready",
    "browser_open": false,
    "last_sync_at": "2026-10-27T12:00:00+00:00",
    "error_code": null,
    "interval_minutes": 30
  }
}
```

Statuses are `not_configured`, `opening`, `awaiting_login`, `syncing`, `ready`, `needs_login`, `error` and `stopped`. The HTTP operation can succeed while the session still needs user action; clients must inspect `session.status` and `error_code`. `ready` means the most recent synchronization succeeded, not that Google can never revoke the session. Public error codes are fixed enums; raw exception strings and account secrets are never reflected.

## Verification

- Fake browser contexts verify correct-identity save, wrong-account rejection, cookie-domain filtering, profile reuse, no duplicate opens, shutdown/cancellation and sanitized errors.
- Scheduler tests verify the three switches, interval/backoff behavior, restart persistence and disabled-account behavior.
- TokenManager tests verify RPC validation before saving, identity protection and explicit-only reactivation.
- Admin route tests verify authentication, missing account handling and the public response envelope.
- Browser UI tests mock admin operations to verify status transitions, retry/failure controls, dialog polling and translated copy without launching a real Google session.
- Integration-reference tests verify every new route has multilingual notes and contains no runtime secrets.

## Practical limits

A visible login window requires installed Chrome/Edge and an interactive desktop/display on the server. On remote or headless deployments the user needs access to that display; opening the local management page does not move the server browser to the user's computer. Google may reject a browser runtime, request additional verification or revoke a session at any time. Keeping and revisiting a profile improves continuity but does not guarantee indefinite login. End-to-end sign-in requires the user's own credentials and verification and must not be claimed as tested by fake-browser checks.

## Google sign-in compatibility correction (2026-10-28)

Google rejected the original Playwright-controlled login with “This browser or app may not be secure.” [Google account guidance](https://support.google.com/accounts/answer/7675428?hl=en) lists software-controlled browsers as a possible cause. The interactive path now uses an ordinary browser process; the user closes its windows after signing in before any background profile automation begins. The change does not attempt to hide automation or bypass Google verification. Login itself still requires validation by the user.
