# Vietnamese Upstream i18n Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development. Steps use checkbox syntax for tracking.

**Goal:** Stop the local server, synchronize main with upstream, and add Vietnamese alongside Chinese and English.

**Architecture:** Keep upstream source messages, middleware boundaries, and translation catalogs. Add a complete `vi` catalog to each existing JSON file; recognize Vietnamese browser/request preferences and expose it in all language selectors. Preserve diagnostic text and application data.

**Tech Stack:** FastAPI, JSON catalogs, vanilla JavaScript, pytest, Playwright.

## Chunk 1: Synchronization and catalogs

- [x] Stop the verified local uvicorn processes and switch to main.
- [x] Fetch upstream/main and merge, keeping upstream changes where equivalent historical commits conflict.
- [x] Add Vietnamese values with identical keys and interpolation parameters to static/locales/manage.json and backend.json.
- [x] Add Vietnamese to common.json, login.json, test.json, and extension/locales.json.

## Chunk 2: Language selection and verification

- [x] Extend failing negotiation/catalog/API/browser tests to cover vi and vi-VN.
- [x] Add vi to static/i18n.js and src/core/i18n.py without changing default fallback behavior.
- [x] Add Vietnamese options to login/manage/test/extension and extension preference detection.
- [x] Verify language switching preserves form input, state, and raw diagnostics.
- [x] Run Python tests, browser tests, syntax/catalog checks and review the complete diff.
- [x] Report main/upstream status and the verified Vietnamese support; leave the local server stopped.

Validation: catalog parity and script syntax passed; full Python run passed 258 tests with 19 browser skips (browser coverage run separately). Reviewed locale and raw-data boundaries. Local port 8000 remains stopped.
Final i18n verification: 47 API/browser tests passed after Vietnamese auth expectation alignment; independent API rerun: 28 passed. Code review approved.
