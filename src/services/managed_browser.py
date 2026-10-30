"""Persistent, account-bound login profiles independent of CAPTCHA browsers.

An injected browser_factory receives (profile_path, headless=bool, proxy=dict|None)
and returns a Playwright-compatible persistent BrowserContext. Neither profile
paths nor browser exception strings are returned through the public status API.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import aiosqlite

from .browser_cookie_utils import is_partitioned_cookie, validate_flow_cookie_storage


FLOW_URL = "https://flow.google.com/projects"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


class ManagedBrowserService:
    """One persistent browser profile and one serialized operation per account."""

    LOGIN_TIMEOUT_SECONDS = 600
    LOGIN_POLL_SECONDS = 2

    def __init__(self, db, token_manager, profile_root=None, browser_factory=None, manual_browser_factory=None):
        self.db = db
        self.token_manager = token_manager
        self.profile_root = Path(profile_root or Path(db.db_path).parent / "managed_browser_profiles").resolve()
        self.browser_factory = browser_factory or self._launch_browser
        # Test contexts can opt into the old injected in-memory watcher. Real
        # sign-in always uses an ordinary browser, without a Playwright/CDP link.
        if manual_browser_factory is not None:
            self.manual_browser_factory = manual_browser_factory
        elif browser_factory is None:
            from .manual_login_browser import launch_manual_browser
            self.manual_browser_factory = launch_manual_browser
        else:
            self.manual_browser_factory = None
        self._manual_browsers: dict[int, Any] = {}
        self._playwright = None
        self._playwright_lock = asyncio.Lock()
        self._locks: dict[int, asyncio.Lock] = {}
        self._control_locks: dict[int, asyncio.Lock] = {}
        self._contexts: dict[int, Any] = {}
        self._login_tasks: dict[int, asyncio.Task] = {}
        self._login_stops: dict[int, asyncio.Event] = {}
        self._closing = False

    async def initialize(self):
        self._closing = False
        async with self.db._connect(write=True) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS managed_browser_sessions (
                    token_id INTEGER PRIMARY KEY REFERENCES tokens(id) ON DELETE CASCADE,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'not_configured',
                    last_sync_at TEXT,
                    last_attempt_at TEXT,
                    error_code TEXT NOT NULL DEFAULT ''
                )
            """)
            # An interrupted interactive login cannot be resumed silently.
            await conn.execute("""
                UPDATE managed_browser_sessions SET status='needs_login',error_code='browser_closed'
                WHERE status IN ('opening','awaiting_login','syncing')
            """)
            await conn.commit()

    def _lock(self, token_id: int) -> asyncio.Lock:
        return self._locks.setdefault(token_id, asyncio.Lock())

    def _control_lock(self, token_id: int) -> asyncio.Lock:
        # A watcher owns the operation lock while waiting for manual login.
        # Control requests need a separate lock so stop can signal the watcher
        # without waiting for that operation lock, while starts remain ordered.
        return self._control_locks.setdefault(token_id, asyncio.Lock())

    async def _token(self, token_id):
        if not isinstance(token_id, int) or isinstance(token_id, bool) or token_id < 1:
            raise LookupError("Account not found")
        token = await self.db.get_token(token_id)
        if not token:
            raise LookupError("Account not found")
        return token

    async def _row(self, token_id):
        async with self.db._connect() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM managed_browser_sessions WHERE token_id=?", (token_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def _write(self, token_id, **updates):
        allowed = {"enabled", "status", "last_sync_at", "last_attempt_at", "error_code"}
        if not updates or not set(updates) <= allowed:
            raise ValueError("Invalid managed browser metadata")
        async with self.db._connect(write=True) as conn:
            await conn.execute("INSERT OR IGNORE INTO managed_browser_sessions(token_id) VALUES (?)", (token_id,))
            await conn.execute(
                "UPDATE managed_browser_sessions SET " + ",".join(f"{key}=?" for key in updates) + " WHERE token_id=?",
                (*updates.values(), token_id),
            )
            await conn.commit()

    @staticmethod
    def _interval(token):
        try:
            return max(1, min(10080, int(token.refresh_interval_minutes or 30)))
        except (TypeError, ValueError):
            return 30

    async def get_status(self, token_id):
        token = await self._token(token_id)
        row = await self._row(token_id) or {}
        return {
            "token_id": token_id,
            "enabled": bool(row.get("enabled", False)),
            "status": row.get("status", "not_configured"),
            "browser_open": token_id in self._contexts or bool(
                self._manual_browsers.get(token_id) and self._manual_browsers[token_id].is_running
            ),
            "last_sync_at": row.get("last_sync_at"),
            "error_code": row.get("error_code", ""),
            "interval_minutes": self._interval(token),
        }

    async def _proxy(self, token):
        raw = str(token.proxy_url or "").strip()
        if not raw:
            manager = getattr(getattr(self.token_manager, "flow_client", None), "proxy_manager", None)
            if manager:
                raw = str(await manager.get_request_proxy_url() or "").strip()
        if not raw:
            return None
        parsed = urlparse(raw if "://" in raw else "http://" + raw)
        if parsed.scheme not in {"http", "https", "socks5"} or not parsed.hostname:
            raise ValueError("proxy_invalid")
        # Accessing .port validates malformed values without exposing the URL.
        port = parsed.port
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        proxy = {"server": f"{parsed.scheme}://{host}" + (f":{port}" if port else "")}
        if parsed.username is not None:
            proxy["username"] = unquote(parsed.username)
            proxy["password"] = unquote(parsed.password or "")
        return proxy

    async def _launch_browser(self, profile_path, *, headless, proxy):
        from .manual_login_browser import read_profile_channel

        async with self._playwright_lock:
            if self._playwright is None:
                from playwright.async_api import async_playwright

                self._playwright = await async_playwright().start()
        # Chromium otherwise discards session-only Google cookies on clean
        # browser shutdown despite using a persistent profile directory.
        options = {
            "headless": headless, "proxy": proxy, "timeout": 30000,
            "viewport": {"width": 1200, "height": 850},
            "args": ["--restore-last-session"],
        }
        if os.environ.get("FLOW2API_CHROME_SANDBOX", "").lower() in {"1", "true", "yes", "on"}:
            options["chromium_sandbox"] = True
        channel = read_profile_channel(profile_path) or "chrome"
        try:
            return await self._playwright.chromium.launch_persistent_context(str(profile_path), channel=channel, **options)
        except Exception as exc:
            message = str(exc).lower()
            if read_profile_channel(profile_path):
                # A profile created by normal Chrome/Edge must stay in that
                # browser; do not silently downgrade it to bundled Chromium.
                raise
            if "distribution 'chrome' is not found" not in message and "executable doesn't exist" not in message:
                raise
            # Chrome is optional; Playwright Chromium is a supported fallback.
            return await self._playwright.chromium.launch_persistent_context(str(profile_path), **options)

    async def _context(self, token, *, headless):
        current = self._contexts.get(token.id)
        if current is not None:
            return current, False
        profile = (self.profile_root / f"token-{token.id}").resolve()
        if profile.parent != self.profile_root:
            raise ValueError("Invalid profile directory")
        profile.mkdir(parents=True, exist_ok=True)
        context = await self.browser_factory(profile, headless=headless, proxy=await self._proxy(token))
        self._contexts[token.id] = context

        def closed(*_):
            if self._contexts.get(token.id) is context:
                self._contexts.pop(token.id, None)

        context.on("close", closed)
        return context, True

    async def _close_context(self, token_id):
        context = self._contexts.pop(token_id, None)
        if context is not None:
            try:
                await asyncio.wait_for(context.close(), timeout=10)
            except Exception:
                pass

    def _profile(self, token_id):
        profile = (self.profile_root / f"token-{token_id}").resolve()
        if profile.parent != self.profile_root:
            raise ValueError("Invalid profile directory")
        return profile

    async def _close_manual_browser(self, token_id):
        browser = self._manual_browsers.pop(token_id, None)
        if browser is not None:
            await browser.close()

    async def _manual_login(self, token_id, token, stop):
        # No browser automation is connected while the user enters credentials
        # or completes Google's verification. Closing the dedicated browser
        # commits its profile and is the hand-off to cookie synchronization.
        await self._close_context(token_id)
        try:
            browser = await self.manual_browser_factory(self._profile(token_id), proxy=await self._proxy(token))
        except ValueError as exc:
            if str(exc) == "proxy_invalid":
                await self._write(token_id, status="error", error_code="proxy_invalid")
                return
            raise
        self._manual_browsers[token_id] = browser
        await self._write(token_id, status="awaiting_login", error_code="")
        deadline = asyncio.get_running_loop().time() + self.LOGIN_TIMEOUT_SECONDS
        while browser.is_running and not stop.is_set() and not self._closing:
            if asyncio.get_running_loop().time() >= deadline:
                await self._close_manual_browser(token_id)
                await self._write(token_id, status="needs_login", error_code="login_timeout")
                return
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.LOGIN_POLL_SECONDS)
            except asyncio.TimeoutError:
                pass
        if stop.is_set() or self._closing:
            return
        self._manual_browsers.pop(token_id, None)
        token = await self._token(token_id)
        context = None
        try:
            await self._write(token_id, status="syncing", error_code="")
            context, _ = await self._context(token, headless=True)
            page = await self._page(context)
            await page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=30000)
            error, result = await self._capture(token, context)
            if result and not stop.is_set() and not self._closing:
                await self._save(token_id, result, interactive=True)
            elif not stop.is_set():
                await self._write(token_id, status="needs_login", error_code=error)
        finally:
            if context is not None:
                await self._close_context(token_id)

    @staticmethod
    async def _page(context):
        pages = [p for p in context.pages if not p.is_closed()]
        if not pages:
            return await context.new_page()
        return next((p for p in pages if urlparse(p.url).hostname == "flow.google.com"), pages[-1])

    async def _capture(self, token, context):
        page = await self._page(context)
        identity = await page.evaluate(
            "({host:location.hostname,ready:document.readyState,email:(window.WIZ_global_data||{}).oPEP7c||''})"
        )
        if not isinstance(identity, dict) or identity.get("host") != "flow.google.com" or not identity.get("email"):
            return "login_required", None
        expected = str(token.login_account or token.email or "").strip().casefold()
        observed = str(identity.get("email") or "").strip()
        if not expected or observed.casefold() != expected:
            return "identity_mismatch", None
        cookies = []
        for cookie in await context.cookies():
            host = str(cookie.get("domain") or "").lower().lstrip(".")
            if (host == "google.com" or host.endswith(".google.com")) and not is_partitioned_cookie(cookie):
                cookies.append(cookie)
        serialized = json.dumps(cookies, ensure_ascii=False, separators=(",", ":"))
        try:
            validate_flow_cookie_storage(serialized)
        except ValueError:
            return "login_required", None
        return "", {"email": observed, "google_cookies": serialized}

    async def _save(self, token_id, result, *, interactive):
        await self._write(token_id, status="syncing", error_code="")
        try:
            success = await self.token_manager.save_managed_browser_cookies(token_id, result, reactivate=interactive)
        except Exception:
            success = False
        if success:
            await self._write(token_id, status="ready", error_code="", last_sync_at=_utcnow().isoformat())
        else:
            await self._write(token_id, status="error", error_code="validation_failed")

    async def start_login(self, token_id):
        async with self._control_lock(token_id):
            await self._token(token_id)
            if self._closing:
                raise RuntimeError("Browser service is shutting down")
            task = self._login_tasks.get(token_id)
            if task and not task.done():
                return await self.get_status(token_id)
            async with self._lock(token_id):
                if self._closing:
                    raise RuntimeError("Browser service is shutting down")
                await self._write(token_id, enabled=1, status="opening", error_code="", last_attempt_at=_utcnow().isoformat())
                stop = asyncio.Event()
                self._login_stops[token_id] = stop
                self._login_tasks[token_id] = asyncio.create_task(self._login(token_id, stop))
            return await self.get_status(token_id)

    async def _login(self, token_id, stop):
        async with self._lock(token_id):
            try:
                if self._closing or stop.is_set():
                    return
                token = await self._token(token_id)
                if self._closing or stop.is_set():
                    return
                if self.manual_browser_factory is not None:
                    await self._manual_login(token_id, token, stop)
                    return
                context, _ = await self._context(token, headless=False)
                page = await self._page(context)
                await page.bring_to_front()
                try:
                    await page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    # Login redirects can replace the page execution context;
                    # the watcher below observes the final signed-in page.
                    if token_id not in self._contexts:
                        await self._write(token_id, status="needs_login", error_code="browser_closed")
                        return
                await self._write(token_id, status="awaiting_login")
                deadline = asyncio.get_running_loop().time() + self.LOGIN_TIMEOUT_SECONDS
                error = "login_required"
                while not stop.is_set() and asyncio.get_running_loop().time() < deadline:
                    if token_id not in self._contexts:
                        await self._write(token_id, status="needs_login", error_code="browser_closed")
                        return
                    # Re-read account identity in case it was edited while login was open.
                    token = await self._token(token_id)
                    try:
                        error, result = await self._capture(token, context)
                    except Exception:
                        if token_id not in self._contexts:
                            await self._write(token_id, status="needs_login", error_code="browser_closed")
                            return
                        # Evaluation while Google navigates is expected during
                        # manual sign-in/2FA. Retry within the bounded deadline.
                        error, result = "login_required", None
                    if result:
                        await self._save(token_id, result, interactive=True)
                        return
                    await self._write(token_id, status="awaiting_login", error_code=error)
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=self.LOGIN_POLL_SECONDS)
                    except asyncio.TimeoutError:
                        pass
                if not stop.is_set():
                    await self._write(token_id, status="needs_login", error_code="identity_mismatch" if error == "identity_mismatch" else "login_timeout")
            except asyncio.CancelledError:
                raise
            except LookupError:
                await self._close_context(token_id)
            except Exception:
                if not stop.is_set():
                    await self._write(token_id, status="error", error_code="browser_unavailable" if token_id not in self._contexts else "sync_failed")

    async def sync(self, token_id, interactive=False):
        if self._closing:
            raise RuntimeError("Browser service is shutting down")
        await self._token(token_id)
        task = self._login_tasks.get(token_id)
        if task and not task.done():
            return await self.get_status(token_id)
        async with self._lock(token_id):
            if self._closing:
                raise RuntimeError("Browser service is shutting down")
            row = await self._row(token_id)
            if not row or not row["enabled"]:
                return await self.get_status(token_id)
            token = await self._token(token_id)
            temporary = False
            await self._write(token_id, status="syncing", error_code="", last_attempt_at=_utcnow().isoformat())
            try:
                context, temporary = await self._context(token, headless=not interactive)
                page = await self._page(context)
                await page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=30000)
                error, result = await self._capture(token, context)
                if result:
                    await self._save(token_id, result, interactive=interactive)
                else:
                    await self._write(token_id, status="needs_login", error_code=error)
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._write(token_id, status="error", error_code="sync_failed")
            finally:
                if temporary and not interactive:
                    await self._close_context(token_id)
        return await self.get_status(token_id)

    async def _cancel_login(self, token_id):
        task = self._login_tasks.pop(token_id, None)
        stop = self._login_stops.pop(token_id, None)
        if stop:
            stop.set()
        await self._close_manual_browser(token_id)
        if task and not task.done():
            # Closing the context interrupts navigation. Let SQLite operations
            # finish normally instead of cancelling while a connection opens.
            await self._close_context(token_id)
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=35)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def stop(self, token_id):
        async with self._control_lock(token_id):
            await self._token(token_id)
            await self._cancel_login(token_id)
            async with self._lock(token_id):
                await self._close_manual_browser(token_id)
                await self._close_context(token_id)
                await self._write(token_id, enabled=0, status="stopped", error_code="")
            return await self.get_status(token_id)

    async def forget(self, token_id):
        async with self._control_lock(token_id):
            await self._cancel_login(token_id)
            async with self._lock(token_id):
                await self._close_manual_browser(token_id)
                await self._close_context(token_id)
                async with self.db._connect(write=True) as conn:
                    await conn.execute("DELETE FROM managed_browser_sessions WHERE token_id=?", (token_id,))
                    await conn.commit()

    async def run_due_once(self):
        if self._closing:
            return
        refresh_config = await self.db.get_token_refresh_config()
        if not refresh_config or not refresh_config.enabled:
            return
        async with self.db._connect() as conn:
            cursor = await conn.execute("SELECT token_id,last_attempt_at FROM managed_browser_sessions WHERE enabled=1")
            rows = await cursor.fetchall()
        for token_id, last_attempt in rows:
            task = self._login_tasks.get(token_id)
            if task and not task.done():
                continue
            token = await self.db.get_token(token_id)
            if not token or not token.auto_refresh_enabled:
                continue
            last = _as_utc(last_attempt)
            if last and _utcnow() - last < timedelta(minutes=self._interval(token)):
                continue
            await self.sync(token_id)

    async def shutdown(self):
        self._closing = True
        token_ids = set(self._control_locks) | set(self._locks) | set(self._login_tasks) | set(self._contexts) | set(self._manual_browsers)
        for token_id in token_ids:
            async with self._control_lock(token_id):
                await self._cancel_login(token_id)
                async with self._lock(token_id):
                    await self._close_manual_browser(token_id)
                    await self._close_context(token_id)
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
