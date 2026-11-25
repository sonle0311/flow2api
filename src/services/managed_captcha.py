"""reCAPTCHA tokens minted inside an account's own signed-in Chrome profile.

Flow rejects tokens produced by a spoofed or automated environment with
PUBLIC_ERROR_UNUSUAL_ACTIVITY. This service reuses the persistent, signed-in
profile that ManagedBrowserService keeps for each account: it opens the Flow
project page headless, lets Flow load reCAPTCHA itself, then calls
grecaptcha.enterprise.execute with the requested action. No third-party solver
and no cost per token.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Optional
from urllib.parse import urlparse

from ..core.logger import debug_logger
from .managed_browser import ProfileBusyError
from .recaptcha_runtime import (
    FLOW_RECAPTCHA_SITE_KEY,
    TRUSTED_RECAPTCHA_HOOK_SOURCE,
    build_recaptcha_execute_script,
)

PROJECT_URL = "https://flow.google.com/project/{}"

_RECAPTCHA_READY_SCRIPT = """(projectId) =>
    location.hostname === 'flow.google.com' &&
    location.pathname === '/project/' + projectId &&
    typeof grecaptcha !== 'undefined' &&
    !!grecaptcha.enterprise &&
    typeof grecaptcha.enterprise.execute === 'function'"""

# Upstream errors that mean the page's reCAPTCHA state is no longer trusted.
_RECAPTCHA_ERROR_MARKERS = ("unusual_activity", "recaptcha", "403")


def _report(token_id: int, action: str, begun: float, reason: str) -> None:
    """Always-on line in server.log: the debug log is off in normal operation, and without
    this a failed upload or generation only says "Failed to obtain reCAPTCHA token"."""
    print(f"[managed-captcha] token={token_id} {action} gave up after {time.monotonic() - begun:.1f}s: {reason}", flush=True)


class SignedOutError(RuntimeError):
    """The account's browser profile is not signed in to Google/Flow."""


class CaptchaStats:
    """What each account's token minting has been doing lately (kept in memory)."""

    WINDOW_SECONDS = 3600
    ALERT_WINDOW_SECONDS = 900
    ALERT_THRESHOLD = 3
    MAX_EVENTS = 200

    def __init__(self, clock=time.time):
        self._clock = clock
        self._events: dict[int, deque] = {}
        self._totals: dict[int, dict[str, int]] = {}

    def record(self, token_id: int, action: str, outcome: str, *, seconds: float = 0.0, length: int = 0, reason: str = "") -> None:
        """outcome: ok (token minted), failed (could not mint) or rejected (Flow refused a token)."""
        events = self._events.setdefault(token_id, deque(maxlen=self.MAX_EVENTS))
        events.append((self._clock(), action, outcome, round(seconds, 2), length, reason[:200]))
        totals = self._totals.setdefault(token_id, {"ok": 0, "failed": 0, "rejected": 0})
        totals[outcome] = totals.get(outcome, 0) + 1

    def recent_failures(self, token_id: int, window: Optional[float] = None) -> int:
        cutoff = self._clock() - (window or self.ALERT_WINDOW_SECONDS)
        return sum(1 for event in self._events.get(token_id, ()) if event[0] >= cutoff and event[2] != "ok")

    def last_outcome(self, token_id: int) -> Optional[str]:
        events = self._events.get(token_id)
        return events[-1][2] if events else None

    def snapshot(self) -> list[dict]:
        cutoff = self._clock() - self.WINDOW_SECONDS
        rows = []
        for token_id, events in sorted(self._events.items()):
            recent = [event for event in events if event[0] >= cutoff]
            durations = [event[3] for event in recent if event[2] == "ok"]
            lengths = [event[4] for event in recent if event[2] == "ok" and event[4]]
            failures = [event for event in events if event[2] != "ok"]
            rows.append({
                "token_id": token_id,
                "last_hour": {
                    "ok": sum(1 for event in recent if event[2] == "ok"),
                    "failed": sum(1 for event in recent if event[2] == "failed"),
                    "rejected": sum(1 for event in recent if event[2] == "rejected"),
                },
                "total": dict(self._totals.get(token_id, {})),
                "mint_seconds_avg": round(sum(durations) / len(durations), 1) if durations else None,
                "mint_seconds_max": max(durations) if durations else None,
                "token_length_last": lengths[-1] if lengths else None,
                "last_failure": (
                    {"at": failures[-1][0], "action": failures[-1][1], "outcome": failures[-1][2], "reason": failures[-1][5]}
                    if failures else None
                ),
            })
        return rows


class ManagedCaptchaService:
    """One headless Flow project tab per account, serialized per account."""

    PROFILE_WAIT_SECONDS = 30
    NAVIGATION_TIMEOUT_MS = 45000
    READY_SECONDS = 30
    EXECUTE_TIMEOUT_MS = 25000
    IDLE_SECONDS = 600
    REAP_INTERVAL_SECONDS = 60

    def __init__(self, browser_service):
        self.browser = browser_service
        self._pages: dict[int, Any] = {}
        self._hooked: dict[int, Any] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._last_used: dict[int, float] = {}
        self._reaper: Optional[asyncio.Task] = None
        self._closed = False
        self.stats = CaptchaStats()
        self.alerts = None  # AlertService, set by the application

    def _note(self, token_id: int, action: str, outcome: str, **fields) -> None:
        """Record an outcome and raise or clear the per-account alert."""
        self.stats.record(token_id, action, outcome, **fields)
        alerts = self.alerts
        if alerts is None:
            return
        key = f"captcha_failing:{token_id}"
        failures = self.stats.recent_failures(token_id)
        if failures >= self.stats.ALERT_THRESHOLD:
            asyncio.ensure_future(alerts.raise_condition(
                key,
                f"Account {token_id}: {failures} captcha failures in the last "
                f"{int(self.stats.ALERT_WINDOW_SECONDS // 60)} minutes (last: {fields.get('reason') or outcome}).",
                severity="warning", details={"token_id": token_id, "failures": failures},
            ))
        elif outcome == "ok" and failures == 0 and key in alerts.conditions:
            asyncio.ensure_future(alerts.clear_condition(key))

    def _lock(self, token_id: int) -> asyncio.Lock:
        return self._locks.setdefault(token_id, asyncio.Lock())

    async def get_token(
        self,
        project_id: str,
        action: str = "IMAGE_GENERATION",
        token_id: Optional[int] = None,
        interact: bool = False,
    ) -> Optional[str]:
        project_id = str(project_id or "").strip()
        if token_id is None or not project_id or self._closed:
            return None
        action = str(action or "IMAGE_GENERATION").strip().upper()
        self._ensure_reaper()
        async with self._lock(token_id):
            self._last_used[token_id] = time.monotonic()
            reason = ""
            begun = time.monotonic()
            for attempt in (1, 2):
                started = time.monotonic()
                try:
                    page = await self._ready_page(token_id, project_id)
                    token = await self._execute(page, action, interact)
                    if token:
                        debug_logger.log_info(
                            f"[ManagedCaptcha] Token-{token_id} {action} ok "
                            f"(len={len(token)}, {time.monotonic() - started:.1f}s)"
                        )
                        self._note(token_id, action, "ok", seconds=time.monotonic() - begun, length=len(token))
                        return token
                    reason = "empty token"
                except asyncio.CancelledError:
                    raise
                except ProfileBusyError:
                    debug_logger.log_warning(
                        f"[ManagedCaptcha] Token-{token_id} profile is busy (sync or sign-in)"
                    )
                    _report(token_id, action, begun, "profile busy (sync or sign-in)")
                    self._note(token_id, action, "failed", reason="profile busy (sync or sign-in)")
                    return None
                except SignedOutError:
                    # Retrying cannot help: the profile needs a new sign-in.
                    _report(token_id, action, begun, "signed out: sign this account in again")
                    self._note(token_id, action, "failed", reason="signed out")
                    mark = getattr(self.browser, "mark_signed_out", None)
                    if mark is not None:
                        await mark(token_id)
                    await self._drop_page(token_id)
                    return None
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {str(exc)[:200]}"
                debug_logger.log_warning(
                    f"[ManagedCaptcha] Token-{token_id} {action} attempt {attempt} failed: {reason}"
                )
                await self._drop_page(token_id)
            _report(token_id, action, begun, f"2 attempts failed, last: {reason}")
            self._note(token_id, action, "failed", seconds=time.monotonic() - begun, reason=reason)
            return None

    async def report_flow_error(
        self,
        *,
        token_id: Optional[int],
        error_reason: str = "",
        error_message: str = "",
    ) -> None:
        """Reload the account's tab after Flow distrusted a token from it."""
        text = f"{error_reason} {error_message}".lower()
        if token_id is None or not any(marker in text for marker in _RECAPTCHA_ERROR_MARKERS):
            return
        self._note(token_id, "FLOW", "rejected", reason=(error_reason or error_message)[:200])
        async with self._lock(token_id):
            await self._drop_page(token_id)

    async def reap_idle(self) -> None:
        """Close tabs and profiles that have not minted for IDLE_SECONDS."""
        now = time.monotonic()
        for token_id in list(self._pages):
            lock = self._lock(token_id)
            if lock.locked() or now - self._last_used.get(token_id, now) < self.IDLE_SECONDS:
                continue
            async with lock:
                await self._drop_page(token_id)
                self._hooked.pop(token_id, None)
                await self.browser.release_context(token_id)

    async def close(self) -> None:
        self._closed = True
        if self._reaper is not None:
            self._reaper.cancel()
            try:
                await self._reaper
            except asyncio.CancelledError:
                pass
            self._reaper = None
        for token_id in list(self._pages):
            await self._drop_page(token_id)

    def _ensure_reaper(self) -> None:
        if self._reaper is None or self._reaper.done():
            self._reaper = asyncio.create_task(self._reap_loop())

    async def _reap_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(self.REAP_INTERVAL_SECONDS)
            try:
                await self.reap_idle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                debug_logger.log_warning(f"[ManagedCaptcha] idle reap failed: {type(exc).__name__}")

    async def _ready_page(self, token_id: int, project_id: str):
        page = self._pages.get(token_id)
        if page is not None and page.is_closed():
            self._pages.pop(token_id, None)
            page = None
        if page is not None:
            if not await self._is_ready(page, project_id):
                await self._open_project(page, project_id)
            return page

        context = await self.browser.open_context(
            token_id, wait_seconds=self.PROFILE_WAIT_SECONDS
        )
        if self._hooked.get(token_id) is not context:
            await context.add_init_script(TRUSTED_RECAPTCHA_HOOK_SOURCE)
            self._hooked[token_id] = context
        page = await context.new_page()
        self._pages[token_id] = page
        await self._open_project(page, project_id)
        return page

    @staticmethod
    async def _is_ready(page, project_id: str) -> bool:
        try:
            return bool(await page.evaluate(_RECAPTCHA_READY_SCRIPT, project_id))
        except Exception:
            return False

    async def _open_project(self, page, project_id: str) -> None:
        await page.goto(
            PROJECT_URL.format(project_id),
            wait_until="domcontentloaded",
            timeout=self.NAVIGATION_TIMEOUT_MS,
        )
        deadline = time.monotonic() + self.READY_SECONDS
        while time.monotonic() < deadline:
            if await self._is_ready(page, project_id):
                return
            if self._signed_out(page):
                raise SignedOutError("login_required")
            await asyncio.sleep(0.5)
        raise RuntimeError("login_required" if self._signed_out(page) else "recaptcha_unavailable")

    @staticmethod
    def _signed_out(page) -> bool:
        """The saved profile has no session: Google asked for a sign-in, or Flow showed its landing page."""
        try:
            url = urlparse(page.url)
        except Exception:  # noqa: BLE001
            return False
        return url.hostname != "flow.google.com" or url.path.startswith("/about")

    @staticmethod
    async def _move_pointer(page) -> None:
        """Real pointer events across the page.

        reCAPTCHA scores a token higher with pointer activity behind it. Flow accepts a token
        minted without any for generation but rejects it (PUBLIC_ERROR_UNUSUAL_ACTIVITY) for
        extend and edit; a few real mouse moves are enough (verified 2026-11-24).
        """
        size = getattr(page, "viewport_size", None) or {"width": 1200, "height": 850}
        width, height = size["width"], size["height"]
        for index in range(14):
            await page.mouse.move(
                width * (0.12 + 0.05 * index),
                height * (0.25 + 0.06 * (index % 4)),
                steps=8,
            )
            await asyncio.sleep(0.035)

    async def _execute(self, page, action: str, interact: bool = False) -> Optional[str]:
        if interact:
            await self._move_pointer(page)
        result = await asyncio.wait_for(
            page.evaluate(
                build_recaptcha_execute_script(
                    FLOW_RECAPTCHA_SITE_KEY, action, self.EXECUTE_TIMEOUT_MS
                )
            ),
            timeout=self.EXECUTE_TIMEOUT_MS / 1000 + 10,
        )
        if isinstance(result, dict) and result.get("ok"):
            return str(result.get("token") or "").strip() or None
        error = result.get("error") if isinstance(result, dict) else result
        debug_logger.log_warning(f"[ManagedCaptcha] execute returned no token: {str(error)[:200]}")
        return None

    async def _drop_page(self, token_id: int) -> None:
        page = self._pages.pop(token_id, None)
        if page is not None:
            try:
                await asyncio.wait_for(page.close(), timeout=5)
            except Exception:
                pass
