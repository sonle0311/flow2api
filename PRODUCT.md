# Flow2API

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users and purpose

Flow2API is an operator console and model-testing interface for a Google Flow API gateway. Users connect their own Google accounts, keep sessions usable, configure providers and proxies, diagnose requests, and connect compatible API clients. The current user works in Vietnamese and deploys with Docker Compose on a Linux VPS.

## Stack and operating context

Existing FastAPI backend, SQLite, server-served HTML and vanilla JavaScript. Management and model testing require an administrator session. Generation additionally uses the configured generation API key. The optional VPS desktop uses the existing authenticated noVNC flow.

## Capabilities and constraints

- Account browser onboarding, Cookie import, credential synchronization, status, credits, verified or unknown entitlement, generation limits and enable/disable controls.
- Independent configuration sections, request logs and complete copyable API integration instructions.
- Image/video testing through the published catalog, including Omni 1.2; model-specific reference images and source-video IDs, streamed progress and media results.
- Preserve zh-CN, English and Vietnamese, all endpoint contracts, authentication, browser/profile isolation and safeguards from commit `0f1cc3a`.
- Available statistics are account totals/active counts and image/video/error counts. There is no real latency series, success-rate chart, queue-depth endpoint or continuously refreshed request feed.

## Brand commitments

The name is Flow2API. The user has no supplied logo, color specification or reference and answered: “Chưa có, bạn tự đề xuất.” Visual direction is open; product functionality is not.

## Evidence and open decisions

`static/manage.html`, `static/test.html`, `static/login.html` and `static/browser-desktop.html` are the current implementation. The redesign first supplies three visual directions using clearly identified synthetic data. Choosing a direction does not change application credentials or trigger generation. The user selected A Instrument on2026-11-11 for the whole app, explicitly requiring all current features to remain. DESIGN.md records the approved graphite/orange world.

## Principles

Make account readiness and the next useful action clear. Distinguish unknown entitlement from Free. Give generation progress, failure and completion separate states. Keep credentials out of previews and copied examples. Preserve keyboard access and readable Vietnamese on desktop and mobile.
