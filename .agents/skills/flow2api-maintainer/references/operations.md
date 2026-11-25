# Operations (local macOS deployment)

## Service

- launchd label `com.flow2api.server`, working dir the repo, interpreter `.venv/bin/python`, port 8000, log `logs/server.log` (stdout and stderr).
- Health: `curl -s -o /dev/null -w '%{http_code}' localhost:8000/health` must be 200.

## Restart procedure

1. `.venv/bin/python3.11 .agents/skills/flow2api-maintainer/scripts/preflight.py`. If it reports in-flight requests or active jobs, **wait**: a restart kills them and the user's paid generations with them.
2. `launchctl kickstart -k gui/$(id -u)/com.flow2api.server`
3. Poll `/health` until 200 (a few seconds), then re-run preflight to confirm accounts are as before.

Never use `launchctl bootout`/`unload` unless asked.

## Reading failures

| Log line / error | Meaning | Action |
|---|---|---|
| `[managed-captcha] token=N <ACTION> gave up ...: signed out` | profile has no Google session | user logs account N in again from the console (account row, browser login) |
| `... last: RuntimeError: recaptcha_unavailable` | page reached project but reCAPTCHA never became ready (not signed out) | check `captcha-diagnostics`; Flow page change? |
| `PUBLIC_ERROR_UNUSUAL_ACTIVITY` | token scored low, or stale/incorrect extend/edit header | protocol doc, "Request header" and "reCAPTCHA" |
| `[managed-browser] token=N the browser profile did not keep the sign-in` | Chrome did not persist cookies | login again; if repeated, inspect profile cookies DB |
| HTTP 429 `queue_full` / client key limits | admission queue or client-key rule | expected; see queue settings |
| `credit_budget_exceeded` | client key's monthly budget used | raise the budget or wait |

## Accounts and logins

- Statuses are in `managed_browser_sessions`; a session `needs_login` means the managed profile is not signed in, whatever the DB cookies say.
- Login is interactive (Chrome window on the user's desktop): the agent cannot do it and must not try to bypass it. Tell the user which account and where (console `/manage`, the account's browser-login button).
- `FLOW2API_MANUAL_LOGIN_AUTODETECT=0` disables the automatic hand-off after login.
- Profile cookie check (read-only, copy the file first because Chrome locks it): `data/managed_browser_profiles/token-<id>/Default/Cookies` (newer Chrome: `Default/Network/Cookies`); a signed-in profile has `SID`, `__Secure-1PSID`, `__Secure-3PSID` on `.google.com` (about 30 Google cookies; token 5 after a correct login: 29). Fewer than 5 Google cookies and no `SID` means signed out.

## Tests

- Narrow: `.venv/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_managed_captcha.py tests/test_managed_browser.py`
- Full: about 3 minutes; run once at the end of a broad change, in the background.
- Do not write tests that merely mirror implementation; add a regression test for a bug that had none.

## Live verification menu (cheapest first)

1. `GET /health`, `GET /v1/models` (free).
2. `scripts/flow_catalog.py` (free; needs a signed-in profile not in use by the server).
3. Omni 360p 3 s text-to-video through `POST /v1/jobs` (about 3 credits) with the user's approval.
4. Extend/edit (3 credits per second extension, 9+ credits edit) only when that path changed.
