# Flow Omni 1.2 edit and extend: captured protocol

Captured on 2026-11-24 from the Flow web app (account 4, Ultra) by intercepting the request the
UI sends and aborting it before it left the browser, so nothing was generated and no credits were
spent. Tokens and per-request IDs are redacted. **Not implemented in Flow2API yet**: the response
shape and the operation polling for these two RPCs have not been observed.

Both calls are `POST https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=<RPC>`
with form fields `f.req` and `at`, like the `YhhmEf` (text to video) and `MZZa6b` (reference images)
calls Flow2API already makes through `_call_flow_frontend_rpc`.

## Edit (video to video)

UI: open a video, type in "Describe how to edit this video…", model Omni 1.2 Flash.

RPC `jIps6`, argument:

```json
[[[[null, "<batch uuid>", 0, 96, null, [], [4]],
   [null, null, [["<prompt>"]]],
   "macaron_cookie_edit",
   2,
   [null, "<source video media id>", null, null, "<request uuid>"]]],
 [null, 22, null, null, null, "<project id>", null, null, null, null, ["<recaptcha token>", 1]],
 ["<session uuid>", 2]]
```

## Extend

UI: open a video, "+" at the end of the timeline, "Extend", choose a length (4s here), type the prompt.

RPC `fZytfe`, argument:

```json
[[[[null, "<batch uuid>", 0, 96],
   [null, null, [["<prompt>"]]],
   "macaron_cookie_extend_4s",
   2,
   null,
   [null, "<source video media id>", null, null, "<request uuid>"]]],
 [null, 22, null, null, null, "<project id>", null, null, null, null, ["<recaptcha token>", 1]],
 ["<session uuid>", 2]]
```

## What the model table says (RPC `HTrJv`, see `scripts/flow_catalog.py`)

- `macaron_cookie_extend_{3..10}s` (and `_360p`): at most 3 input images; 30 credits for 10s at 720p;
  not available on the free tier.
- `macaron_cookie_edit` (and `_360p`, `_entry`): at most 5 inputs; the credit cost depends on the
  length of the source video (9 credits for 3s, 12 for 4s, 15 for 5s, ... 42 for 12s).

## To finish the feature

1. Send one real `jIps6` / `fZytfe` call and record the response, then normalise it like
   `_normalize_frontend_video_submission` does for `YhhmEf`.
2. Check which RPC the status poll uses for these operations (`jwpduf` is used for `YhhmEf`).
3. Take the source video from the existing `extend://<media id>` marker, and add `edit` and
   `extend` modes to the `omni-1.2-flash` family contract.
