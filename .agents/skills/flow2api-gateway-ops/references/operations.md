# Operations (local macOS deployment)

Contents: Service, Restart procedure, Reading failures, Accounts and logins, Tests.

## Service

launchd label `com.flow2api.server`; working dir is the repo; interpreter `.venv/bin/python`; port 8000; stdout and stderr go to `logs/server.log`. Health: `GET /health` must answer 200.

## Restart procedure

Run exactly this sequence; do not substitute `bootout`/`unload`.

1. `.venv/bin/python3.11 .agents/skills/flow2api-gateway-ops/scripts/preflight.py`. Exit 1 means requests or jobs are running: **stop and wait**, a restart kills them.
2. `launchctl kickstart -k gui/$(id -u)/com.flow2api.server`
3. Poll `/health` until 200 (a few seconds), then run `scripts/preflight.py` again to confirm accounts are as before.

## Reading failures

| What you see | Meaning | Action |
|---|---|---|
| `[managed-captcha] token=N <ACTION> gave up ...: signed out` | the profile of account N has no Google session | the user logs in again (console `/manage`, the account's browser login) |
| `... last: RuntimeError: recaptcha_unavailable` | the project page loaded but reCAPTCHA never became ready; not signed out | `GET /api/admin/captcha-diagnostics`; has the Flow page changed? |
| `PUBLIC_ERROR_UNUSUAL_ACTIVITY` | low-scored token, or stale/wrong extend/edit header | protocol doc, sections "Request header" and "reCAPTCHA" |
| `[managed-browser] token=N the browser profile did not keep the sign-in` | Chrome did not persist its cookies | login again; if it repeats, inspect the profile cookies (below) |
| HTTP 429 with `Retry-After` (`queue_full`, per-key limits) | admission queue or client-key rule | expected back-pressure; client retries after the delay |
| `credit_budget_exceeded` | the client key's monthly budget is used | raise the budget or wait for the new month |
| `Failed to obtain reCAPTCHA token for image upload` | minting failed before Flow accepted anything, so nothing was charged | look at the `[managed-captcha]` line just above it |

## Accounts and logins

- Login state lives in `managed_browser_sessions` (`ready`, `needs_login`, `opening`, `awaiting_login`, `syncing`). `needs_login` means the managed profile is not signed in, whatever cookies the `tokens` row holds.
- Login is interactive (a Chrome window on the user's desktop). The agent cannot do it and must not try to bypass it: name the account and say where (console `/manage`, the account's browser login button).
- `FLOW2API_MANUAL_LOGIN_AUTODETECT=0` turns off the automatic hand-off after login.
- Profile cookie check (read-only; copy the file first because Chrome locks it): `data/managed_browser_profiles/token-<id>/Default/Cookies`, or `Default/Network/Cookies` on newer Chrome. A signed-in profile has `SID`, `__Secure-1PSID` and `__Secure-3PSID` on `.google.com` (about 30 Google cookies; token 5 after a correct login had 29). A profile with a handful of Google cookies and no `SID` is signed out.

## Tests

- Narrow: `.venv/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_managed_captcha.py tests/test_managed_browser.py`
- Full suite: about 3 minutes; run once at the end of a broad change, in the background.
- Fakes for browsers and Flow clients already exist in `tests/test_managed_*.py`; extend them instead of adding new ones.
