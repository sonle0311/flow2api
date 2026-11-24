# Flow Omni 1.2 edit and extend: protocol

Captured on 2026-11-24 from the Flow web app (account 4, Ultra) and then confirmed by real sends
through Flow2API (extend: 4 s appended to an 8 s video, 1280×720 result of 11.8 s; edit: a 3 s frog
turned orange, 1280×720, 3.0 s). Tokens and per-request IDs are redacted.

Both calls are `POST https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=<RPC>`
with form fields `f.req` and `at`, like `YhhmEf` (text to video) and `MZZa6b` (reference images).
The `source-path` query parameter must be the editor page of the source video,
`/project/<project id>/edit/<media id>`.

Flow2API exposes them as `omni-1.2-flash-extend-{3..10}s-{landscape,portrait}` and
`omni-1.2-flash-edit-{3..15}s-{landscape,portrait}` (720p only; 360p was not tested). The source video
is named with the existing `extend://ID` marker in an `image_url` part.

## Identifiers: operation vs media

A *media* ID names the video as it appears in the project. An *operation* ID names one generation
job. They differ, and the `data-media-id` Flow2API returns is the **operation** ID of the job that
produced the video. Extending or editing a video keeps the same media ID and gives it a new
current operation. Lookups used by `FlowClient.get_source_state`:

| Need | RPC | Argument | Answer |
|---|---|---|---|
| media of an operation | `as29s` | `[<operation id>]` | record `[operation, project, media, …]`; `code=[5]` if the ID is not an operation |
| current operation of a media | `Zzl0ze` | `["projects/<project id>", null, null, null, [1]]` | list of `[media, null, null, [title, [ts], null, null, <current operation>, …], project]` |
| length of an operation | `as29s` | `[<operation id>]` | contains `[null, null, [<seconds>]]` |

## Request header

Both RPCs start with a header naming the source's **current** operation and its **total** length in
frames (24 fps). A stale operation or a wrong length is answered with `PUBLIC_ERROR_UNUSUAL_ACTIVITY`
(the same error as a bad reCAPTCHA token), so Flow2API reads both fresh before every request.

### Edit (video to video), RPC `jIps6`

```json
[[[[null, "<current operation>", 0, <seconds*24>, null, [], [<seconds>]],
   [null, null, [["<prompt>"]]],
   "macaron_cookie_edit",
   2,
   [null, "<media id>", null, null, "<request uuid, upper case>"]]],
 [null, 22, null, null, null, "<project id>", null, null, null, null, ["<recaptcha token>", 1]],
 ["<session uuid>", 2]]
```

### Extend, RPC `fZytfe`

```json
[[[[null, "<current operation>", 0, <seconds*24>],
   [null, null, [["<prompt>"]]],
   "macaron_cookie_extend_<N>s",
   2,
   null,
   [null, "<media id>", null, null, "<request uuid, upper case>"]]],
 [null, 22, null, null, null, "<project id>", null, null, null, null, ["<recaptcha token>", 1]],
 ["<session uuid>", 2]]
```

## Response and polling

The answer to `fZytfe`/`jIps6` has the same shape as `YhhmEf`: `[null, <credits>, [[<new operation>,
<project>, <media>, …]]]`. Poll the **new operation** with `jwpduf`; when it is done, `as29s([<new
operation>])` returns the signed `https://flow-content.google/video/…` URL of the *whole* resulting
video (source plus extension for extend, the rewritten video for edit). Polling `as29s` with a media
ID answers `code=[5]` forever, which is why a request that polls the wrong ID never ends.

## reCAPTCHA

Same site key and action (`VIDEO_GENERATION`) as generation, but Flow scores these two RPCs
more strictly:

- a token minted by `grecaptcha.enterprise.execute` in an automated Chrome is rejected with
  `PUBLIC_ERROR_UNUSUAL_ACTIVITY` even when every field of the request is right;
- the same token from an ordinary Chrome profile is accepted once the page has seen mouse movement;
- after removing Playwright's `--enable-automation` flag (and adding
  `--disable-blink-features=AutomationControlled`) the managed browser is accepted.

`ManagedBrowserService._launch_browser` therefore always drops the automation flag, and
`ManagedCaptchaService.get_token(..., interact=True)` moves the mouse over the page before minting
for extend/edit. Other mints are untouched. `personal`/`browser` captcha methods were not tested
for extend/edit.

## Account and project

Extend/edit must run in the project holding the source video, on the account owning that project.
Every successful video generation records `media → project, account` in the table `video_sources`
(created on first use); `extend://ID?project=<project id>` names the project for a video that was
made outside this server.

## Costs

- `macaron_cookie_extend_{3..10}s`: 3 credits per second at 720p; not available on the free tier.
- `macaron_cookie_edit` (and `_360p`, `_entry`): depends on the source length, 9 credits for 3 s,
  12 for 4 s, 15 for 5 s, … 42 for 12 s (RPC `HTrJv`, see `scripts/flow_catalog.py`).

Veo Extend (`veo_3_1_extend*`) was retired by Flow on 2026-11-05 and is no longer offered.
