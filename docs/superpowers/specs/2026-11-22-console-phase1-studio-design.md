# Console, phase 1: shell and Studio

## Problem and intended outcome

The fork's admin UI is the upstream `manage.html` / `test.html` markup with an "Instrument" stylesheet layered on top. The owner wants the whole interface redone: new visual style, layout and navigation. They chose direction **B, "dark control panel"** (dark, horizontal tabs, information-dense; its tokens and layout are recorded under "Visual system" below) and chose to build it as a **separate new frontend** rather than editing upstream's pages.

The owner uses Flow2API mainly through its API from other projects and generates in volume. The first thing to deliver is the trial-generation screen ("Studio"), which must look professional and replace the long list of variant model ids (`…-landscape-2k`, `…-8s-portrait`) with a **short list of base models plus parameters**.

Success for phase 1: an admin signs in, opens `/console`, picks a base model, sets parameters, generates an image or video, sees the result, and can copy the equivalent API request, without ever seeing a variant model id unless they open the request view.

## Scope

Phase 1 delivers the console shell and Studio only. Accounts, Logs, Settings and Integration are later phases with their own specs; until then their tabs link to the matching section of the existing `/manage` page. `/manage`, `/test`, `/login` and every existing static file stay untouched so upstream merges remain clean. `/` keeps serving the current login page; switching the default landing page to the console is phase 4.

Not in phase 1: any change to generation, captcha, account or database logic; a per-account "slots in use" display; a light theme; server-side result history.

## Architecture

All new frontend files live in `static/console/`:

| File | Responsibility |
|---|---|
| `index.html` | Document skeleton: top bar, tab strip, system status strip, one `<main>` outlet. No inline scripts. |
| `console.css` | Design tokens and shell/component styles. |
| `studio.css` | Studio-only layout. |
| `app.js` | Boot: session check, locale load, tab routing by hash (`#studio`). |
| `api.js` | `adminRequest(path, options)` (session cookie, same-origin, redirects to `/login` on 401) and `generationRequest(body, signal)` (Bearer API key, streaming). |
| `models.js` | Pure functions over the parameter contracts: list base models, list valid values, resolve defaults, validate a selection. No DOM. |
| `studio.js` | Studio view: form state, rendering, submit, results. |
| `request-preview.js` | Builds the displayed `curl` / JSON from the same body object that is sent. |

No build step and no framework: plain ES modules, served by FastAPI. The project has no Node toolchain and phase 1 has one screen.

Server changes are limited to `src/main.py`:

- `GET /console` serves `static/console/index.html` behind the existing `_ensure_admin_page_session` guard, with the existing no-cache headers.
- `GET /static/console/{asset_name}` serves only an explicit allowlist of the files above with fixed media types, following the existing `_INSTRUMENT_ASSETS` pattern. Unknown names return 404; path separators cannot be supplied because the parameter is a single path segment.

Locale strings live in `static/console/locales.json` (vi, en, zh-CN, keyed by id) and are served through the same allowlist. The console has its own small lookup in `app.js` and shares the `flow2api.language` preference with the classic pages. It does not use `static/locales/` or `i18n.js`: those catalogues are keyed by Chinese source strings, and the existing catalogue test enforces that shape on every file in that folder. The fonts already shipped (`Be Vietnam Pro`) are reused.

## Data sources

- **Models and parameters:** `GET /api/integration/reference` (admin session). Studio uses `model_parameters` (one contract per base model: `id`, `type`, `defaults`, `mode_defaults`, `parameters`, `variants`) and `capacity`. Display names come from `models[].display_name` of the contract's default variant, falling back to the contract id.
- **API key:** `GET /api/admin/config` already returns `api_key` to an authenticated admin. The console reads it once per page load and keeps it in memory only; it is never written to `localStorage`, never rendered in full (the request preview shows `$FLOW2API_API_KEY`), and never logged.
- **Generation:** `POST /v1/chat/completions` with `stream: true`, as the current test page does.

## Studio behaviour

**Model.** One select, grouped Image / Video, listing only contracts with `listed: true`. Variant ids never appear in the form.

**Parameters.** Rendered from the selected contract, never hard-coded:

- Image: aspect ratio (`parameters.aspectRatio.values`), size (`parameters.imageSize.values`).
- Video: mode (`parameters.mode.values`; hidden when there is a single mode or the only mode is `auto`), duration, aspect ratio.

Each control is a segmented button group when it has five or fewer values, otherwise a select. A value is selectable only if some entry in `variants` matches it together with the other current selections; choosing a value that invalidates another control resets that control to the nearest valid value and briefly marks it as changed. Changing the model applies `defaults`; changing video mode applies `mode_defaults[mode]`.

**Reference inputs.** Derived from the matching variant: the image drop zone is shown when `supports_images` is true, accepts up to `max_images`, and states the minimum (`locally_validated_min_images`). For `mode: extend` a "source video media id" field replaces the drop zone. Images are read as data URLs and limited to 10 MB each with an inline error otherwise.

**Request.** The body sent is the base model id plus parameters, not a variant id:

```json
{"model": "<contract.id>", "stream": true,
 "messages": [{"role": "user", "content": [...]}],
 "generationConfig": {"imageConfig": {"aspectRatio": "16:9", "imageSize": "2K"}}}
```

Video uses `generationConfig.videoConfig` with `durationSeconds`, `aspectRatio` and `mode`, as given by the contract's `config_path`. The implementation plan must first confirm with an existing server test that the base id plus `generationConfig` path resolves for every listed contract; if any contract does not, Studio sends the matching `variants[].id` for that contract instead, and the request preview shows what is actually sent.

**Count.** 1–4. Each item is its own request, started with the server-reported `launch_stagger_ms` between them. The maximum offered is `min(4, capacity.<kind>.recommended_max_parallel_requests)`; when capacity is 0 or unknown the generate button is disabled with the reason shown.

**Results.** A grid of tiles, newest first. A running tile shows the latest progress text from the stream and a cancel button; a finished tile shows the image or video with open-full-size, download, and "reuse settings". A failed tile shows the server's error message and a retry button. Results live in memory for the page session; nothing is persisted.

**Request preview.** A collapsible panel showing the current selection as `curl` and as JSON, generated from the same body builder used for sending, with a copy button. Data-URL images are abbreviated in the preview.

**Status strip.** Captcha method, parallel capacity for images and videos, and service health, from `capacity` and `/health`, refreshed when the tab regains focus.

## Visual system

Tokens (dark only in phase 1): background `#0b0d12`, surface `#0e1016`, raised `#141821`, border `#1e222c` / `#2a2f3b`, text `#e6e8ee`, muted `#9aa1b2`, accent `#34d399` with ink `#052e1f`, info `#60a5fa`, warning `#fbbf24`, danger `#f87171`. All text pairs meet 4.5:1. Type: Be Vietnam Pro 13–14px for UI, 11px uppercase labels with letter-spacing, system monospace with tabular numerals for ids, numbers and code. Radius 6–8px, 1px borders, no shadows except dialogs.

Layout: 52px top bar (brand, tabs, status strip); Studio is a two-column grid, a 380px form column and a fluid results column, collapsing to one column below 900px with the form first. Interactive targets are at least 36px high on desktop and 44px below 760px. Visible focus rings, `prefers-reduced-motion` respected, icons are inline SVG, state is never conveyed by colour alone.

## Errors

- No admin session: redirect to `/login`.
- Reference fetch fails: Studio shows an inline error with a retry button; the form is not rendered from stale or built-in fallbacks.
- Generation errors: shown on the affected tile only; other tiles keep running.
- Stream ends without a result: the tile is marked failed with "no result returned".

## Testing

- Python: `/console` requires an admin session; `/static/console/<allowed>` returns the right media type; unknown asset names return 404.
- JavaScript logic in `models.js` and the body builder is pure and is covered by the repo's existing approach for static scripts (Python tests that assert on file contents and run logic through fixtures where present); the plan picks the concrete harness after reading the existing `test_integration_*` tests.
- Manual, in the browser at 375, 768, 1024 and 1440px: every listed contract renders, invalid combinations cannot be selected, the preview matches the sent body. Real generations are run only when the owner asks, because each one costs captcha fees and credits.

## Later phases (outline only)

2. Accounts: table, add/edit/import/export, browser login, live activity column; decides whether a small read endpoint for in-use slots is needed.
3. Logs and Settings.
4. Integration; make the console the default landing page.

Upstream UI features do not appear in the console automatically; each upstream merge needs a check for admin-UI changes to port.

## Amendment (2026-11-23): shared shell on the classic pages

The owner asked for the new look on every page, not only Studio, so the "classic pages stay untouched" rule above no longer holds:

- `/login` is rebuilt (brand panel plus form card) and lands on `/console` after sign-in.
- `/manage` keeps its markup and handlers, but `instrument-shell.js` now builds the same left sidebar as the console, moves the account actions beside the page title, adds client-side search and status filters to the account and log tables, and gives Settings a single column with a table of contents.
- `instrument*.css` use the console palette; `/console` uses the same sidebar instead of top tabs.
- `/test` still works by URL but is no longer linked; the Studio entry points to `/console`.
