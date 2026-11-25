# Upstream research protocol (web search and deep search)

Load this before the first search of a task. Goal: get facts about Google Flow that are correct **today**, and know how sure you are.

## What search can and cannot answer

| Question | Search? | Better source |
|---|---|---|
| Which models/features does Flow advertise, which are retiring, plan entitlements | yes, official pages | live catalog confirms |
| Credit cost of a shape | partly (Help page "Manage your Google Flow credits") | `catalog-status` / ledger measured (360p 3 s = 3 credits) |
| RPC ids, payload shapes, error meanings (`HTrJv`, `fZytfe`, `jIps6`, `as29s`) | **no** (undocumented) | `docs/flow-omni-edit-extend-protocol.md`, capture the web app |
| Why `UNUSUAL_ACTIVITY` / reCAPTCHA score | only for general reCAPTCHA Enterprise behaviour | our own experiments, `captcha-diagnostics` |
| Chrome/Playwright/CDP behaviour (flags, profile flush) | yes, vendor docs | a throwaway experiment, as done for `Browser.close` |
| Gemini API (`ai.google.dev`) behaviour | yes, but it is a **different product** from Flow's web RPCs | never copy API parameters into Flow requests |

## Source tiers

1. **Official**: `support.google.com/flow/...`, `blog.google/.../google-labs/...`, `ai.google.dev`, `aistudio.google.com/docs`, `developers.google.com`.
2. **Reputable secondary** that links or quotes the official text.
3. **SEO/pricing blogs and news-desk sites**: one search in Nov 2026 returned several "pricing 2026" posts that agreed with the Help page, but also look auto-generated. Use them to find the official page, then cite the official page.

When tiers disagree, the higher tier wins; when the live catalog disagrees with any page, the live catalog wins.

## Procedure

1. **Frame**: one sentence question + the decision it drives (code constant, doc line, user answer).
2. **Local first**: `MODEL_CONFIG`, protocol doc, `/api/admin/catalog-status`, `git log -S"<term>"` for history.
3. **Query**: short, specific, exact names in quotes.
   - Official only: `site:support.google.com "Google Flow" "Omni Flash 1.2"`.
   - Freshness: set `recency` (`week`/`month`) or `after:YYYY-MM-DD`; for Flow anything older than about a month may be stale.
   - Retirements/pricing: `"Veo 3.1" retire`, `"Flow credits" cost 360p`.
   - Forums/practitioners: add `site:news.ycombinator.com` or `site:reddit.com` only for symptoms, never for facts.
   - Do not put cookies, tokens, emails, project ids, key fragments in a query.
4. **Read the page** with `read <url>` (the `web_search` snippet is cut to ~240 chars and may be an answer-synthesis without the exact sentence). Quote the sentence and note: URL, page date or "as of" date, platform/plan/region variant.
5. **Cross-check** anything that changes behaviour: two independent sources, or one official source plus a live check. Single-source facts are `[INFERENCE]`.
6. **Live check**: `scripts/flow_catalog.py` (read-only) or the console "Operations" card; a paid real call only with approval.
7. **Record**: dated source in the doc/commit message, e.g. "official Help page, checked 2026-11-25".

## Deep search (open-ended investigations)

Use when the cause or design is open (e.g. "why are tokens rejected in automated Chrome", "what replaced Veo Extend").

1. Split into 3-5 independent sub-questions; each with the tier it should be answered from.
2. One read-only `scout` per sub-question, in a single batch. Each task states: sub-question, allowed source tiers, the exact return format `claim | URL | quoted sentence | date | confidence`, and "do not edit files".
3. Synthesize yourself: list agreements, contradictions, gaps. A claim backed only by a tier-3 source is dropped or marked `[INFERENCE]`.
4. Turn the surviving claims into a falsifiable experiment on this repo (a probe script, a catalog compare), run it, and keep the experiment's result as the evidence. Delete throwaway probe scripts afterwards.

Do **not** spawn agents for a single lookup, for facts already in the repo, or to "double check" something a live call already settled.

## Verified snapshot (official Flow Help page, read 2026-11-25; re-verify before relying)

- Omni Flash 1.2: text/frames/ingredients to video and video-to-video; 3-10 s without a Google AI plan, 3-15 s with Plus/Pro/Ultra; **Extend** (3-10 s, up to 3 images) and Upscale (to 1080p, 4K for Ultra) need a plan; Omni 360p costs one third of 720p.
- Veo 3.1 Lite: t2v and frames 4/6/8 s, references 8 s only; no video-to-video, no extend.
- Veo Extend retired 2026-11-05. Veo 3.1 Fast, Veo 3.1 Quality and Omni Flash 1.1 retire **2026-12-05**.
- Image models named by Flow: Nano Banana Pro (default for Ultra), Nano Banana 2 Lite (free default), Nano Banana 2.1.
- Credits: Flow credits come from the Google AI plan or a daily free grant; check the in-app prompt-box settings for the current cost before quoting a number.

This snapshot is a dated lead. The repo's own `MODEL_CONFIG` and the live catalog decide what the gateway exposes.
