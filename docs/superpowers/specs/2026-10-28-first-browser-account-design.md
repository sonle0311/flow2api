# Add the first account through a browser

## Problem and intended behavior

The existing browser action belongs to an account row, so an empty account list has no way to start browser sign-in. Add a global **Add account through browser** action and an empty-state action. The user supplies only the Google email, signs in using the normal standalone browser, and closes the dedicated profile windows before synchronization.

This extends the previously approved persistent-browser workflow. It does not require an API key, cookie import, password collection or preexisting account ID.

## Registration and state

`POST /api/browser-sessions/accounts` accepts `{email: string}` under the existing admin authentication and same-origin mutation guard. Normalize email case and surrounding whitespace, reject non-ASCII/invalid addresses, lengths over 254 and local parts over 64, and reject body fields other than email. Atomic database identity checks under BEGIN IMMEDIATE prevent concurrent requests or imports from creating duplicate drafts; an existing record is reused.

If the normalized email exists, return its ID with `created=false`, leave credentials/settings unchanged, and start its existing managed login. Otherwise create an inactive token record with the real supplied email in both identity fields, an unpredictable `browser-pending-` session marker, no access token, empty cookies, default account permissions, and a 30-minute refresh interval. Return `created=true`.

Pending records stay outside generation because they are inactive. The interface labels them **Waiting for sign-in**, rather than suggesting that they are usable accounts. Existing disabled accounts keep their ordinary disabled label. Hide the manual Enable action for pending drafts, and reject attempts to enable their pending session marker with HTTP 409 until sign-in validation replaces it.

Start the current normal Chrome/Edge login flow against that account ID and its dedicated profile. While the user authenticates, no automation connects to Google sign-in. After all dedicated profile windows close, background cookie capture must match the selected email exactly and pass current Flow RPC validation. Only that explicit successful login may activate the account. Background checks never activate pending or disabled accounts.

Failed or cancelled sign-in leaves an inactive draft available for retry or deletion. Do not delete profiles, clear existing credentials, create fake email identities, or enable incomplete drafts automatically.

## API contract

Successful registration returns `{success:true,created:boolean,session:{token_id,enabled,status,browser_open,last_sync_at,error_code,interval_minutes}}`. Session polling and stop/sync actions continue using the existing per-account routes.

Invalid input returns HTTP 422, absent admin authentication HTTP 401, and an unrelated browser origin HTTP 403. Status and error values exclude cookies, passwords, proxy credentials and filesystem paths. The configured generation API key does not authorize this operation.

## Interface

The button is available in the token-list toolbar regardless of account count. The empty table also explains that the first account can be added by browser login.

An accessible form requests a required Google email. Submitting disables duplicate requests and displays progress. Success refreshes the account list and opens the current browser-status dialog for the returned account ID. Closing the form during a pending request must not reopen a dialog unexpectedly if the response arrives later; a completed server-side registration may still be reflected when refreshing the list.

All labels, waiting states, errors and instructions support Chinese, English and Vietnamese. The instructions retain the normal-browser sign-in and close-window handoff required by the Google compatibility correction.

## Verification

- Empty-list browser test confirms the global action needs no existing row, Cookie or API key.
- Registration tests cover valid/invalid email, case-insensitive reuse, duplicate-click concurrency, safe inactive defaults and credential preservation.
- Admin API tests cover authentication, origin checks, response filtering and service invocation.
- Cookie validation tests retain strict identity checks, RPC-before-save and explicit-only activation.
- UI tests cover localized empty state, pending labels, submit failures/retry, disabled duplicate submission and stale responses after cancellation.
- Exhaustive integration reference includes this endpoint and a valid request/response example.

Real Google authentication remains a human step. Tests may simulate the flow but must not claim that Google accepted a real sign-in.

## Review evidence

Read-only backend review confirmed inactive defaults, RPC-free preparation, atomic identity de-duplication across manager instances, existing-account credential preservation, admin authentication and origin guards, response field filtering, and validation-before-activation. The existing generation path lazily creates Flow projects after successful login, so pending drafts need no upstream project creation. Focused bootstrap/token/reference tests: 29 passed and 5 subtests passed.

An independent concurrency probe used 12 separate Database/TokenManager instances against one SQLite file for three rounds. Each round produced one inactive account and exactly one created=true result.
