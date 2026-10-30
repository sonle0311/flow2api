# AI Integration Guide Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development. Steps use checkbox syntax for tracking.

**Goal:** Add an admin tab with complete, copyable instructions an AI agent can use to integrate the deployed Flow2API service into an existing tool.

**Architecture:** Preserve the upstream multilingual UI. A dedicated integration script builds a plain-text prompt from localized documentation and verified API examples. An editable server root defaults to the current origin; API keys remain environment-variable placeholders. No generation or configuration writes occur when viewing or copying the guide.

**Tech Stack:** Vanilla JavaScript, FastAPI static-file response, JSON catalogs, pytest and Playwright.

## Chunk 1: Guide and tests

- [x] Verify endpoints, authentication, response formats and timeout behavior against source.
- [x] Write failing browser tests for tab visibility, guide contents, origin override, clipboard and fallback, locale switching and invalid URL recovery.
- [x] Add three-language integration catalog, preserving interpolation placeholders.

## Chunk 2: UI implementation and verification

- [x] Add integration tab, accessible fields/status/preview and responsive layout matching the existing console.
- [x] Add isolated guide rendering/copy behavior and serve its JavaScript explicitly.
- [x] Load integration catalog only for the manage page; preserve existing tab behavior.
- [x] Run focused API/browser tests and syntax/catalog checks; review source/API consistency.
- [x] Verify the live local page on desktop/mobile and show the new tab to the user.

Verification: 51 focused API/browser tests passed, live desktop/mobile checks passed without overflow or JavaScript errors, clipboard/fallback and locale scenarios passed. Read-only code/API review found no actionable issues. Existing console design detector warnings are outside the new panel.

## Chunk 3: Exhaustive reference requested by user

- [x] Add an admin-authenticated, read-only reference endpoint deriving every route, schema, model and alias from the running registries.
- [x] Add precise three-language endpoint notes, body/query constraints and request/response examples.
- [x] Add comprehensive runnable recipes for image/video workflows, resolution, extension, Gemini, Python/OpenAI SDK, JavaScript SSE and arbitrary-tool adapters.
- [x] Render browsable/searchable endpoint/model/alias tables and include their complete contents in the copied guide.
- [x] Disable copying if the exhaustive reference cannot be loaded; provide retry and preserve URL/language/filter behavior.
- [x] Verify route/model coverage and absence of runtime secrets, browser copy/filter/retry and existing UI behavior.
- [x] Review, restart local server and verify the complete live reference on desktop/mobile.

Exhaustive reference verification: 84 route/method/mount entries, 279 model IDs, 59 aliases, 28 schemas, 65 response examples. Full suite: 265 passed/24 browser skips; separate browser run: 24 passed. Final endpoint/recipe/schema tests: 5 passed after correcting email examples. Live desktop/mobile: no overflow or JavaScript errors. Reviewer findings for WebSocket notes and R2V configured-vs-local image minimum resolved.
