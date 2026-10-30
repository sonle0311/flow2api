# Normal browser login correction

**Goal:** Resolve the managed login flow's incompatibility with Google's restriction on software-controlled sign-in browsers.

**Evidence:** The user received Google's insecure-browser rejection. The active managed Chrome process had a remote debugging argument, and the source launched it through Playwright. Google's official account help lists software automation as a possible reason for rejecting sign-in.

**Design:** Launch an installed ordinary Chrome/Edge process with the dedicated account profile, without an automation or remote-debugging connection during sign-in. The user completes authentication and closes that profile's windows. Only after process exit may background profile inspection and Flow validation run. Preserve account identity safeguards and explicit-only reactivation.

- [x] Add failing launcher/service tests, then implement owned-process launch, exit monitoring, safe stop/shutdown and profile reuse.
- [x] Update zh/en/vi instructions and browser tests to require closing the login window before synchronization.
- [x] Correct integration contracts and the existing design document.
- [x] Review subprocess ownership, installed browser selection, profile locks, proxy limitations and cancellation.
- [x] Run relevant regression checks, close only the old managed login window through its authenticated stop API, restart local server and verify the corrected UI/API.

Do not claim a successful real Google login until the user has performed it. Do not add stealth flags or attempt to bypass Google's verification.

## Verification

- Focused launcher, managed service, token manager, authenticated API, UI, i18n and complete integration reference: 102 passed.
- JavaScript syntax and git diff checks passed.
- Independent subprocess/lifecycle review passed.
- Old automated profile window closed through the authenticated stop endpoint; local server restarted and /health passed.
- Real corrected login launched via the admin endpoint: status awaiting_login, browser_open=true. The owned Chrome process has neither remote-debugging nor enable-automation arguments. No automation inspected or controlled the Google sign-in page.
- Google authentication itself is awaiting the user; only after the dedicated windows close may background verification/synchronization begin.
