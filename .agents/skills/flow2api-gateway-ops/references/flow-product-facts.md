# What Google says Flow offers

Official source: Google Flow Help, "Learn about Google Flow models & supported features" (`https://support.google.com/flow/answer/16352836`) and "Manage your Google Flow credits" (`/flow/answer/16526234`). Read the page itself, not a search snippet; its content differs by platform, plan and region. Press and "pricing 2026" blogs only point to these pages.

Treat the lists below as a dated lead. The live catalog and `MODEL_CONFIG` decide what this gateway exposes; if they disagree with this file, update this file.

## Current (read 2026-11-25)

- **Omni Flash 1.2**: text, frames, ingredients/references to video and video-to-video editing, 3-10 s without a Google AI plan, 3-15 s with Plus, Pro or Ultra. **Extend** (3-10 s, up to 3 images) and **Upscale** (to 1080p, 4K on Ultra) need a plan. Omni 360p costs one third of 720p.
- **Veo 3.1 Lite**: text to video and frames 4/6/8 s; ingredients 8 s only. No video-to-video, no extend.
- **Image models** named by Flow: Nano Banana Pro (default on Ultra), Nano Banana 2 Lite (free default), Nano Banana 2.1.
- Credits come from the Google AI plan or a daily free grant. The prompt-box settings in Flow show the current cost; check there before quoting a number.
- **An account's plan** is not in Flow's `/credits` reply (`userPaygateTier` is null). The gateway reads the plan chip (`flow-user-tier-chip .tier-chip`) from the account's browser profile during each sync: the chip is present for Pro and Ultra and absent on a rendered page for the free plan (checked 2026-11-27 on four accounts). A balance that falls 90% or more at once (from 2000 credits or more) triggers an immediate sync and an alert, and is not booked as spending.

## Retirements

- Veo 3.1 Fast, Veo 3.1 Quality and Omni Flash 1.1 retire on **2026-12-05**. Until then they still generate; Flow recommends Omni Flash 1.2 or Veo 3.1 Lite.

## Old patterns

- Veo Extend (`veo_3_1_extend*`) was retired on 2026-11-05. Extending a video now means Omni Flash 1.2 on a Plus, Pro or Ultra account (`omni-1.2-flash-extend-*` here).
