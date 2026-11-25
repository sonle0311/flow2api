---
name: flow2api-maintainer
description: Maintain, debug, operate and extend the Flow2API gateway in this repository (FastAPI wrapper over Google Flow - Veo, Omni, Nano Banana/Gemini image; accounts, managed Chrome profiles, reCAPTCHA, queue, jobs API, credit ledger, catalog monitor). Use for any change or incident in this repo - model or MODEL_CONFIG changes, generation failures (UNUSUAL_ACTIVITY, recaptcha_unavailable, 429, credits), account or browser-profile login problems, restarts and deploys - and BEFORE web-searching anything about Google Flow, Veo, Omni or Gemini image models, plans, credits, retirements or Flow's undocumented web RPCs. Not for generating media from another project (use the flow2api client skill for that).
license: Proprietary
metadata:
  project: flow2api
  knowledge-verified: "2026-11-25"
---

# Flow2API maintainer

Flow is a closed web app that changes **without notice** (Veo Extend retired and Omni extend/edit appeared silently in Nov 2026). Everything here is ranked by how much you can trust it. Work top-down and stop at the first level that settles the question.

## 1. Where the truth is (trust order)

| Rank | Source | Use it for |
|---|---|---|
| 1 | **What Flow answers right now**: live catalog (`GET /api/admin/catalog-status`, `scripts/flow_catalog.py`), the real error in `logs/server.log`, a captured web-app request | which models, reference limits, credit costs, RPC shapes exist today |
| 2 | **This repo**: `MODEL_CONFIG` in `src/services/generation_handler.py`, `docs/flow-omni-edit-extend-protocol.md`, tests | what the gateway does and why |
| 3 | **Official Google pages** (support.google.com/flow, blog.google Labs, ai.google.dev, aistudio.google.com/docs) | announced features, plan entitlements, retirement dates |
| 4 | Press and SEO "pricing 2026" blogs | leads only; never the sole basis for code |

Web search cannot tell you Flow's internal RPC ids or payloads. Those come only from capturing the real web app or from rank 1. A search result that contradicts rank 1 is stale or wrong: trust rank 1, record the discrepancy.

## 2. Researching Flow, Veo, Omni, Gemini image (web search / deep search)

Read [references/upstream-research.md](references/upstream-research.md) **before the first search of a task**. Core rules:

1. Check local truth first (section 1, rank 1-2). Search only for what lives outside the repo.
2. Query with exact model names in quotes, `site:` for official hosts, and `recency`/`after:` for anything time-sensitive. Include no cookies, tokens, emails, project ids or API keys: queries go to third-party providers.
3. A snippet is not evidence. `read` the page, quote the sentence, note the date and the page's variant (Help pages differ by `co=`/platform, plan and region).
4. Anything that changes code, prices or user-facing claims needs two independent sources, or one official page plus a live check. Otherwise label it `[INFERENCE]`.
5. Open-ended questions ("why does X fail?") get a deep-search pass: split into sub-questions, one scout per sub-question, each returning URL + quote + date. Single facts do not get agents.
6. Before shipping a finding, verify live (catalog compare, or one small paid call only with the user's approval), then write the dated source into the doc or commit message.

## 3. Hard rules (cost, safety)

- **Every generation costs credits and is charged at submission.** Never generate to "test" without the user's approval; use the cheapest shape (Omni 360p, 3 s) and say what it cost. A failure after submission is still charged; before submission (e.g. image upload) it is not.
- **Never resend blindly.** A timeout does not mean upstream stopped; check `request_logs`/jobs first. Poll by **operation** id, not media id (see protocol doc).
- **Restart only when idle**: run `scripts/preflight.py` first; deploy with `launchctl kickstart -k gui/$(id -u)/com.flow2api.server`, then wait for `/health` 200. Details in [references/operations.md](references/operations.md).
- **Secrets**: never print the master API key, admin password hash, `st`/`at`, cookies, `login_password`. Read the master key from `admin_config.api_key` only to send a request.
- Admin password is bcrypt with a forced first change; every admin API returns 401 `password_change_required` until the user sets one. Do not reset it. API-key endpoints (`/v1/*`) still work.
- Debug logging is off by design; do not enable it without need. The always-on diagnostics are the `[managed-captcha]` and `[managed-browser]` lines in `logs/server.log`.

## 4. Gotchas that already cost hours

- `PUBLIC_ERROR_UNUSUAL_ACTIVITY` is not always reCAPTCHA. For Omni extend/edit it also means a stale source operation or a wrong frame count in the request header. When the request was correct, the root cause of rejected tokens was Playwright's `--enable-automation` flag; `ManagedBrowserService._launch_browser` removes it. Do not re-add it.
- `recaptcha_unavailable` after ~60 s usually means the managed profile is signed out (Flow shows `/about`), not a captcha outage. Current code reports `login_required` fast and marks the account `needs_login`.
- A managed Chrome profile only keeps its sign-in if Chrome **exits cleanly**. SIGTERM right after login drops unflushed cookies (token 5, Nov 2026). Login finish uses CDP `Browser.close`, waits, then `profile_keeps_google_session` must be true before `ready`.
- Cookies stored in the DB cannot be injected into a fresh profile to restore a session (tested: lands on `/about`). The user must log in again from the console.
- `video_sources` maps media to project and account; extend/edit must run on that account. A video made elsewhere needs `extend://ID?project=<project id>`.
- Poll fail-fast on `code=[5]`: `as29s` with a media id answers `[5]` forever.
- A model that appears in the code but not in Flow's table is either retiring or never existed. Veo 3.1 Fast/Quality and Omni 1.1 retire 2026-12-05; Veo Extend retired 2026-11-05 (official Help page, checked 2026-11-25).
- Test environment: `tests/conftest.py` sets `PLAYWRIGHT_BROWSERS_PATH=0`; the full suite takes about 3 minutes; run the narrow files for your change first.

## 5. Working procedure

Copy and tick:

- [ ] State the question and which file or doc would change.
- [ ] Section 1 ranks 1-2 checked; `scripts/preflight.py` run if the server state matters.
- [ ] Research (section 2) only for outside facts; sources recorded with date.
- [ ] Change made in the existing pattern (see [references/architecture.md](references/architecture.md)); callers migrated, no shims.
- [ ] Narrow tests green; a failing behaviour has a regression test.
- [ ] Verified on the real surface (HTTP call, console page, log line), not only unit tests.
- [ ] Docs updated when behaviour changed (`docs/`, README model tables, `static/locales`).
- [ ] Deploy only when idle; report what was and was not verified.
