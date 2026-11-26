# Architecture map

Read when you must change behaviour and need to know where it lives.

## Request path

```
client -> src/api/routes.py (/v1/chat/completions, /v1beta/..., /v1/models)
       -> client_keys (rate limit, concurrency, model allow-list)   credit_ledger (monthly budget)
       -> admission_queue (bounded FIFO wait for a free account slot; 429 when full)
       -> load_balancer + token_manager (pick account, refresh AT from ST)
       -> generation_handler (MODEL_CONFIG, option validation, upload, polling, result)
       -> flow_client / flow_current / flow_frontend (batchexecute RPCs to flow.google.com)
              reCAPTCHA token: managed_captcha (account's own Chrome profile, default),
              or browser_captcha*, twocaptcha / yescaptcha etc. (config/setting.toml [captcha])
```

`POST /v1/jobs` (src/api/jobs.py, src/services/jobs.py) runs the same generation asynchronously with `Idempotency-Key` replay (202 / 200 replay / 409 conflict).

## Modules

| Concern | File |
|---|---|
| Model table, option checks, generation/extend/edit flow | `src/services/generation_handler.py` (`MODEL_CONFIG` near line 47) |
| Flow RPC calls, source operation/length lookups | `src/services/flow_client.py`, `flow_current.py`, `flow_frontend.py` |
| Live model table decode/compare (`HTrJv`) | `src/services/flow_catalog.py`, `scripts/flow_catalog.py`, `catalog_monitor.py` |
| Accounts, credits, tier, projects | `src/services/token_manager.py`, `src/core/` (db, config, models) |
| Managed Chrome profile login/sync | `src/services/managed_browser.py`, `manual_login_browser.py`, `src/api/browser_sessions.py` |
| Captcha minted in the profile | `src/services/managed_captcha.py` (`SignedOutError`, stats, diagnostics) |
| Cookie-only login validation | `src/services/protocol_login.py`, `flow_cookies.py` |
| Which account owns a video | `src/services/video_sources.py` (table `video_sources`) |
| Input images already uploaded to Flow | `src/services/upload_cache.py` (table `upload_cache`; `FLOW2API_UPLOAD_CACHE_HOURS`, default 24, 0 = off). Each project in an account's pool of 4 needs its own upload, so a new image misses up to 4 times per account. Request logs show `performance.upload_cache` (hits, misses, `stale_evicted`); a media id Flow rejects (`code=[5]`) is dropped and uploaded again once |
| Alerts (webhook, edge-triggered) | `src/services/alerts.py` |
| Credits per client/model | `src/services/credit_ledger.py` (table `credit_usage`) |
| Admin API, console | `src/api/admin.py`, `static/manage.html`, `static/*.js`, `static/locales/*` |

## Data (SQLite `data/flow.db`)

`tokens` (accounts; secrets inside), `managed_browser_sessions` (status `ready|needs_login|opening|awaiting_login|syncing`, `error_code`), `request_logs` (progress < 100 and no status = in flight), `jobs` (times are epoch seconds), `video_sources`, `upload_cache` (media id of an input image per account, project and SHA-256), `credit_usage`, `client_keys`, `catalog_snapshot`, `alert_settings`, `admin_config`. Browser profiles live in `data/managed_browser_profiles/token-<token id>/`.

## Project conventions

- User-facing strings go through `static/i18n.js` and `static/locales/`; add a key to every locale file.
- `docs/flow-omni-edit-extend-protocol.md` is the single protocol reference; when you learn a new RPC fact, add it there with the capture date.
