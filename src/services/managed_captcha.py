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

    def _lock(self, token_id: int) -> asyncio.Lock:
        return self._locks.setdefault(token_id, asyncio.Lock())

    async def get_token(
        self,
        project_id: str,
        action: str = "IMAGE_GENERATION",
        token_id: Optional[int] = None,
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
                    token = await self._execute(page, action)
                    if token:
                        debug_logger.log_info(
                            f"[ManagedCaptcha] Token-{token_id} {action} ok "
                            f"(len={len(token)}, {time.monotonic() - started:.1f}s)"
                        )
                        return token
                    reason = "empty token"
                except asyncio.CancelledError:
                    raise
                except ProfileBusyError:
                    debug_logger.log_warning(
                        f"[ManagedCaptcha] Token-{token_id} profile is busy (sync or sign-in)"
                    )
                    _report(token_id, action, begun, "profile busy (sync or sign-in)")
                    return None
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {str(exc)[:200]}"
                debug_logger.log_warning(
                    f"[ManagedCaptcha] Token-{token_id} {action} attempt {attempt} failed: {reason}"
                )
                await self._drop_page(token_id)
            _report(token_id, action, begun, f"2 attempts failed, last: {reason}")
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
            await asyncio.sleep(0.5)
        host = ""
        try:
            host = urlparse(page.url).hostname or ""
        except Exception:
            pass
        # Leaving flow.google.com means the saved profile has no session.
        raise RuntimeError("login_required" if host != "flow.google.com" else "recaptcha_unavailable")

    async def _execute(self, page, action: str) -> Optional[str]:
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
