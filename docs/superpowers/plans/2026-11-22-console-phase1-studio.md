# Console phase 1: shell and Studio

**Spec:** `docs/superpowers/specs/2026-11-22-console-phase1-studio-design.md`

**Goal:** A separate admin frontend at `/console` in the approved dark control-panel style, with a Studio that offers base models plus parameters instead of variant ids.

**Architecture:** New files only, under `static/console/`, as plain ES modules with no build step. Two new read-only routes in `src/main.py`. Existing pages, static files and generation logic are not edited.

**Constraints:** Work on a branch, not `main`. No real generation during development or verification (each one costs captcha fees and credits); use a mocked `fetch`. Never print, log or persist the API key. Commit only when the owner asks.

**Verified before planning:** all 8 base-model contracts (119 parameter combinations) resolve to the expected variant through `model` = base id plus `generationConfig.imageConfig` / `videoConfig` on `ChatCompletionRequest`, so Studio always sends the base id. The spec's variant-id fallback is not needed and is not built.

## Task 1: Routes and asset allowlist

- [ ] Test first (`tests/test_console_routes.py`, FastAPI `TestClient`, no lifespan): `/console` without an admin session redirects like `/manage`; with a session returns the HTML with no-cache headers; `/static/console/console.css` and each `.js` return the right media type; an unknown name and an encoded traversal return 404; `/manage` and `/test` still respond as before.
- [ ] `src/main.py`: `_CONSOLE_ASSETS` allowlist (`console.css`, `studio.css`, `app.js`, `api.js`, `models.js`, `studio.js`, `request-preview.js`), `GET /static/console/{asset_name}`, `GET /console` behind `_ensure_admin_page_session`. Register the specific route before the existing `/static/{asset_name}` handler.

## Task 2: Pure model logic

- [ ] Test first (`tests/test_console_models.py`, Node subprocess as in `test_integration_agent_prompt.py`, fed the real `get_model_parameter_contracts(MODEL_CONFIG)`):
  - only `listed` contracts are offered, grouped image / video;
  - defaults and `mode_defaults` are applied on model and mode change;
  - for every contract and every variant, `findVariant(selection)` returns that variant, and every value `validValues()` offers for one control has a matching variant given the other selections;
  - an invalidated selection is repaired to a valid one and reports which control changed;
  - `buildBody()` output, passed back into Python `resolve_model_name`, yields the same variant id for all 119 combinations;
  - reference-input rules (`supports_images`, `max_images`, minimum, `extend` needs a media id) match the variant.
- [ ] `static/console/models.js`: `listModels`, `initialSelection`, `validValues`, `applyChange`, `findVariant`, `referenceRules`, `buildBody`. No DOM, exported both as ES module and attachable to a plain object for the Node tests.
- [ ] `static/console/request-preview.js`: `toJson(body)` and `toCurl(origin, body)` from the same body object; data URLs abbreviated; key shown as `$FLOW2API_API_KEY`. Test that the real key string can never appear in the output.

## Task 3: Shell

- [ ] `static/console/index.html`: top bar (brand, tabs Studio / Accounts / Integration / Logs / Settings, status strip, language select, sign out), `<main id="view">`. Non-Studio tabs are plain links to `/manage#tokens`, `#integration`, `#logs`, `#settings`. No inline scripts or styles.
- [ ] `static/console/console.css`: tokens from the spec, base, top bar, buttons, segmented groups, fields, tiles, focus rings, reduced-motion, breakpoints at 900px and 760px.
- [ ] `static/console/api.js`: `adminRequest` (same-origin cookie, 401 redirects to `/login`), `loadReference`, `loadApiKey` (memory only), `streamGeneration(body, {signal, onProgress})` parsing the existing SSE format read from `static/test.html`.
- [ ] `static/console/app.js`: boot, locale load via `i18n.js`, status strip from `capacity` and `/health`, refresh on focus, sign out via the existing endpoint.
- [ ] `static/locales/console.json`: vi, en, zh-CN; test that all three have identical key sets and no empty values.

## Task 4: Studio view

- [ ] `static/console/studio.css` and `static/console/studio.js`: model select; parameter controls rendered from `validValues` (segmented when five or fewer values, otherwise select); prompt; reference drop zone or media-id field per `referenceRules` with the 10 MB check; count 1–4 capped by capacity; generate button with disabled reason.
- [ ] Results grid: running tile with progress text and cancel (`AbortController`), finished tile with open, download and "reuse settings", failed tile with message and retry; staggered start using `launch_stagger_ms`.
- [ ] Request preview panel with JSON / curl switch and copy.
- [ ] Reference load failure shows an inline error with retry and renders no form.
- [ ] Static test (`tests/test_console_studio_ui.py`): the HTML has no inline script, no variant id literal appears in any console file, the API key is not written to `localStorage` / `sessionStorage` / `console.*`, every control has a label.

## Task 5: Verification

- [ ] Full test suite: no new failures beyond the 8 known pre-existing ones.
- [ ] Restart the local service; in the browser pane with `fetch` to `/v1/chat/completions` mocked, check Studio at 375, 768, 1024 and 1440px: each of the 7 listed models renders, mode / duration / ratio repair works, count cap follows capacity, tiles show running / done / failed, preview equals the sent body, keyboard-only use works, no horizontal scroll.
- [ ] Confirm `/manage`, `/test` and `/login` are byte-identical to before.
- [ ] Report results with screenshots; one real generation only if the owner asks for it.
