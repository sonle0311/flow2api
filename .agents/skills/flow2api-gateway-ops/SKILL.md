---
name: flow2api-gateway-ops
description: Operates, debugs and changes the Flow2API gateway server in this repo (FastAPI proxy over Google Flow - Veo, Omni, Nano Banana images; accounts, managed Chrome profiles, reCAPTCHA, queue, /v1/jobs, credit ledger). Use for server-side work - investigating a failed job or error (UNUSUAL_ACTIVITY, recaptcha_unavailable, "Failed to obtain reCAPTCHA token", 429, credit_budget_exceeded), an account that needs login, restarting or deploying the server, editing MODEL_CONFIG or the model table - even when the user only says "job lỗi", "kiểm tra lỗi", "đăng nhập lại tài khoản" or "restart server". Do NOT use it to make images or videos, even through this gateway; that is the job of the flow2api client skill.
license: Proprietary
metadata:
  project: flow2api
---

# Flow2API gateway ops

Flow is a closed web app that changes without notice, and every generation costs real credits. Most mistakes here come from trusting a symptom's name instead of its cause, or from touching the running server while the user is generating.

## Where to look

| Situation | Go to |
|---|---|
| An error in a job, a request log or `logs/server.log` | [references/operations.md](references/operations.md), "Reading failures" |
| Restart or deploy | [references/operations.md](references/operations.md), "Restart procedure" |
| Extend, edit, request headers, reCAPTCHA scoring, credit costs | `docs/flow-omni-edit-extend-protocol.md` |
| Where a behaviour lives, which table holds what | [references/architecture.md](references/architecture.md) |
| What Flow officially offers or retires (models, plans, dates) | [references/flow-product-facts.md](references/flow-product-facts.md) |

## Rules

- **Never generate without the user's approval.** Credits are charged when Flow accepts the submission, so a request that fails afterwards is still paid for; one that fails earlier (for example at image upload) is not. For a paid check use the cheapest shape (Omni 360p, 3 s, about 3 credits) and report the cost.
- **Restart only when idle.** A restart kills in-flight generations, and the user usually is generating. Run `scripts/preflight.py` first; it exits 1 when something is running.
- **Trust what Flow answers now over what any page says.** The live catalog (`/api/admin/catalog-status`, `scripts/flow_catalog.py`) and the real error beat docs, memory and web results. When they disagree, record the difference.
- **Never print secrets**: master API key, password hashes, `st`/`at`, cookies, `login_password`. Read the master key from `admin_config.api_key` only to send a request; `scripts/smoke.py` does exactly that.
- Admin APIs answer 401 `password_change_required` until the user sets a new admin password. Do not reset it; `/v1/*` with the master key still works.
- Debug logging is off on purpose. The always-on diagnostics are the `[managed-captcha]` and `[managed-browser]` lines in `logs/server.log`.
- Do not resend a request after a timeout before checking `request_logs` and `jobs`: upstream may still be running. Poll an operation by its **operation** id, never its media id.

## Gotchas

- `PUBLIC_ERROR_UNUSUAL_ACTIVITY` is not always a bad reCAPTCHA token. For Omni extend/edit it also means a stale source operation or a wrong frame count in the request header (read both fresh every time). When the request was correct, the cause of rejected tokens was Playwright's `--enable-automation` flag; `ManagedBrowserService._launch_browser` removes it. Do not add it back.
- `recaptcha_unavailable` after about 60 s is usually a **signed-out** managed profile, not a captcha outage: Flow redirects to `flow.google.com/about`. Current code fails fast as `login_required` and marks the account `needs_login`.
- A managed Chrome profile keeps its sign-in only if Chrome **exits cleanly**. SIGTERM right after login drops unflushed cookies (token 5 lost its session this way). Login hand-off ends with CDP `Browser.close`, waits for exit, then requires `profile_keeps_google_session` before marking the account ready.
- The cookies stored in the database cannot restore a signed-out profile (tried: a fresh Chrome lands on `/about`). Only an interactive login from the console works, and the agent cannot do it.
- Finishing a manual login must read the signed-in `/project` tab, not the `/about` landing tab.
- `as29s` with a media id answers `code=[5]` forever; polling must fail fast on it.
- Extend/edit must run on the account and project that own the source video (`video_sources`). A video made elsewhere needs `extend://ID?project=<project id>`.
- Flow's own image aspect-ratio enum has 3:4 and 4:3 swapped; the code compensates (commit 2964985). Do not "fix" it.
- `origin` is a fork that merges upstream. When merging, keep the local features (Vietnamese UI, managed browser, queue, client keys).
- Tests: `tests/conftest.py` sets `PLAYWRIGHT_BROWSERS_PATH=0`; the full suite takes about 3 minutes, so run only the files covering the change, and the full suite once at the end in the background.

## Verify on the real surface

| Check | Command | Cost |
|---|---|---|
| Server idle? accounts logged in? | `.venv/bin/python3.11 .agents/skills/flow2api-gateway-ops/scripts/preflight.py` | free |
| Gateway up, models listed | `.venv/bin/python3.11 .agents/skills/flow2api-gateway-ops/scripts/smoke.py` | free |
| Flow's model table vs `MODEL_CONFIG` | `.venv/bin/python scripts/flow_catalog.py` (needs a signed-in profile the server is not using) | free |
| A real generation | `POST /v1/jobs`, Omni 360p 3 s, only with approval | about 3 credits |

Both scripts accept `--json` and print no secrets. A unit test passing is not proof for browser, captcha or login behaviour: check the log line or the response.
