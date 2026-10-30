import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.core.database import Database
from src.core.models import Token


class FakePage:
    def __init__(self, email="account@example.com"):
        self.email = email
        self.url = "https://flow.google.com/projects"
        self.closed = False

    async def goto(self, url, **kwargs):
        self.url = url

    async def evaluate(self, script):
        if self.closed:
            raise RuntimeError("closed browser contains secret Cookie=bad")
        return {"host": "flow.google.com", "email": self.email, "ready": "complete"}

    async def bring_to_front(self):
        pass

    def is_closed(self):
        return self.closed


class FakeContext:
    def __init__(self, email="account@example.com"):
        self.pages = [FakePage(email)]
        self.closed = False
        self.callbacks = {}

    async def new_page(self):
        # Match Playwright: a closed context cannot create another page. Without
        # this guard, a close racing with _page() invented a signed-in tab.
        if self.closed:
            raise RuntimeError("Browser context is closed")
        page = FakePage()
        self.pages.append(page)
        return page

    async def cookies(self):
        return [
            {"name": "OSID", "value": "secret-session", "domain": "flow.google.com", "path": "/", "secure": True},
            {"name": "SID", "value": "secret-account", "domain": ".google.com", "path": "/", "secure": True},
            {"name": "evil", "value": "secret-other", "domain": "evilgoogle.com", "path": "/"},
        ]

    def on(self, event, callback):
        self.callbacks[event] = callback

    async def close(self):
        self.closed = True
        for page in self.pages:
            page.closed = True
        callback = self.callbacks.get("close")
        if callback:
            callback()


class ManagedBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "test.db"))
        await self.db.init_db()
        self.token_id = await self.db.add_token(Token(st="frontend-old", email="account@example.com", is_active=False))
        self.manager = SimpleNamespace(
            save_managed_browser_cookies=AsyncMock(return_value=True),
            flow_client=SimpleNamespace(proxy_manager=None),
        )
        self.contexts = []
        self.launches = []
        self.email = "account@example.com"

        async def factory(profile_path, *, headless, proxy):
            self.launches.append((profile_path, headless, proxy))
            context = FakeContext(self.email)
            self.contexts.append(context)
            return context

        from src.services.managed_browser import ManagedBrowserService
        self.service = ManagedBrowserService(self.db, self.manager, Path(self.temp.name) / "profiles", factory)
        self.service.LOGIN_POLL_SECONDS = 0.01
        self.service.LOGIN_TIMEOUT_SECONDS = 3
        await self.service.initialize()

    async def asyncTearDown(self):
        if hasattr(self, "service"):
            await self.service.shutdown()
        self.temp.cleanup()

    async def wait_login(self):
        deadline = asyncio.get_running_loop().time() + 5
        while asyncio.get_running_loop().time() < deadline:
            status = await self.service.get_status(self.token_id)
            if status["status"] not in {"opening", "awaiting_login", "syncing"}:
                return status
            await asyncio.sleep(0.01)
        self.fail("login watcher did not settle")

    async def wait_for_status(self, expected):
        deadline = asyncio.get_running_loop().time() + 5
        while asyncio.get_running_loop().time() < deadline:
            status = await self.service.get_status(self.token_id)
            if status["status"] == expected:
                return status
            await asyncio.sleep(0.01)
        self.fail(f"login watcher did not reach {expected}")

    async def test_initialize_does_not_open_browser_or_enable_account(self):
        status = await self.service.get_status(self.token_id)
        self.assertEqual("not_configured", status["status"])
        self.assertFalse(status["enabled"])
        self.assertFalse(self.launches)
        self.assertFalse((await self.db.get_token(self.token_id)).is_active)

    async def manual_setup(self):
        self.manual = SimpleNamespace(is_running=True, channel="chrome", close=AsyncMock())
        self.manual_factory = AsyncMock(return_value=self.manual)
        self.service.manual_browser_factory = self.manual_factory
        self.service.LOGIN_TIMEOUT_SECONDS = 20

    async def test_normal_login_waits_for_window_close_before_any_automation(self):
        await self.manual_setup()
        await self.service.start_login(self.token_id)
        status = await self.wait_for_status("awaiting_login")
        self.assertTrue(status["browser_open"])
        self.assertFalse(self.launches)
        self.manager.save_managed_browser_cookies.assert_not_awaited()
        await self.service.sync(self.token_id)
        self.assertFalse(self.launches)
        self.manual.is_running = False
        status = await self.wait_login()
        self.assertEqual("ready", status["status"])
        self.assertFalse(status["browser_open"])
        self.assertEqual(1, len(self.launches))
        self.assertTrue(self.launches[0][1])
        self.assertTrue(self.contexts[0].closed)
        self.assertTrue(self.manager.save_managed_browser_cookies.await_args.kwargs["reactivate"])

    async def test_stop_closes_only_the_owned_manual_browser_and_never_saves(self):
        await self.manual_setup()
        await self.service.start_login(self.token_id)
        await self.wait_for_status("awaiting_login")
        status = await self.service.stop(self.token_id)
        self.assertEqual("stopped", status["status"])
        self.assertFalse(status["browser_open"])
        self.manual.close.assert_awaited_once()
        self.assertFalse(self.launches)
        self.manager.save_managed_browser_cookies.assert_not_awaited()

    async def test_manual_wrong_account_is_not_saved_after_window_closes(self):
        await self.manual_setup()
        self.email = "other@example.com"
        await self.service.start_login(self.token_id)
        await self.wait_for_status("awaiting_login")
        self.manual.is_running = False
        status = await self.wait_login()
        self.assertEqual("needs_login", status["status"])
        self.assertEqual("identity_mismatch", status["error_code"])
        self.manager.save_managed_browser_cookies.assert_not_awaited()
        self.assertTrue(self.contexts[0].closed)

    async def test_manual_login_timeout_closes_owned_window_without_importing_cookie(self):
        await self.manual_setup()
        self.service.LOGIN_TIMEOUT_SECONDS = 0.03
        await self.service.start_login(self.token_id)
        status = await self.wait_login()
        self.assertEqual("needs_login", status["status"])
        self.assertEqual("login_timeout", status["error_code"])
        self.manual.close.assert_awaited_once()
        self.assertFalse(self.launches)
        self.assertFalse(self.service._manual_browsers)
        self.manager.save_managed_browser_cookies.assert_not_awaited()

    async def test_manual_shutdown_closes_owned_window_and_prevents_automation(self):
        await self.manual_setup()
        await self.service.start_login(self.token_id)
        await self.wait_for_status("awaiting_login")
        await self.service.shutdown()
        self.manual.close.assert_awaited_once()
        self.assertFalse(self.launches)
        self.assertFalse(self.service._manual_browsers)
        self.assertFalse((await self.service.get_status(self.token_id))["browser_open"])
        self.manager.save_managed_browser_cookies.assert_not_awaited()

    async def test_manual_repeated_start_and_sync_do_not_relaunch_or_attach(self):
        await self.manual_setup()
        await self.service.start_login(self.token_id)
        await self.wait_for_status("awaiting_login")
        await self.service.start_login(self.token_id)
        await self.service.sync(self.token_id)
        self.manual_factory.assert_awaited_once()
        self.assertFalse(self.launches)

    async def test_interactive_login_saves_only_google_cookies_and_preserves_context(self):
        status = await self.service.start_login(self.token_id)
        self.assertIn(status["status"], {"opening", "awaiting_login", "syncing", "ready"})
        status = await self.wait_login()
        self.assertEqual("ready", status["status"])
        self.assertTrue(status["enabled"])
        self.assertTrue(status["browser_open"])
        self.assertIsNotNone(status["last_sync_at"])
        self.assertEqual(False, self.launches[0][1])
        self.assertEqual("token-1", self.launches[0][0].name)
        args = self.manager.save_managed_browser_cookies.await_args
        self.assertEqual(self.token_id, args.args[0])
        self.assertTrue(args.kwargs["reactivate"])
        self.assertEqual(["OSID", "SID"], [c["name"] for c in json.loads(args.args[1]["google_cookies"])])
        self.assertNotIn("secret-", json.dumps(status))
        self.assertNotIn("profiles", json.dumps(status))

    async def test_wrong_account_never_saves_credentials(self):
        self.email = "wrong@example.com"
        self.service.LOGIN_TIMEOUT_SECONDS = 0.1
        await self.service.start_login(self.token_id)
        status = await self.wait_login()
        self.assertEqual("needs_login", status["status"])
        self.assertEqual("identity_mismatch", status["error_code"])
        self.manager.save_managed_browser_cookies.assert_not_awaited()

    async def test_background_reuses_saved_profile_headless_and_never_reactivates(self):
        await self.service.start_login(self.token_id)
        await self.wait_login()
        await self.contexts[0].close()
        self.manager.save_managed_browser_cookies.reset_mock()
        status = await self.service.sync(self.token_id)
        self.assertEqual("ready", status["status"])
        self.assertFalse(status["browser_open"])
        self.assertEqual(self.launches[0][0], self.launches[1][0])
        self.assertTrue(self.launches[1][1])
        self.assertTrue(self.contexts[1].closed)
        self.assertFalse(self.manager.save_managed_browser_cookies.await_args.kwargs["reactivate"])

    async def test_parallel_start_calls_only_open_one_profile(self):
        self.email = ""
        await asyncio.gather(self.service.start_login(self.token_id), self.service.start_login(self.token_id))
        await self.wait_for_status("awaiting_login")
        self.assertEqual(1, len(self.launches))

    async def test_stop_disables_sync_and_closes_browser_without_deleting_profile(self):
        await self.service.start_login(self.token_id)
        await self.wait_login()
        marker = self.launches[0][0] / "preserve.txt"
        marker.write_text("keep")
        status = await self.service.stop(self.token_id)
        self.assertEqual("stopped", status["status"])
        self.assertFalse(status["enabled"])
        self.assertFalse(status["browser_open"])
        self.assertTrue(marker.exists())
        await self.service.run_due_once()
        self.assertEqual(1, len(self.launches))

    async def test_login_wait_can_be_cancelled_by_stop(self):
        self.email = ""
        self.service.LOGIN_TIMEOUT_SECONDS = 20
        await self.service.start_login(self.token_id)
        await self.wait_for_status("awaiting_login")
        status = await asyncio.wait_for(self.service.stop(self.token_id), timeout=3)
        self.assertEqual("stopped", status["status"])
        self.assertTrue(self.contexts[0].closed)

    async def test_repeated_open_and_sync_return_promptly_while_waiting_for_user(self):
        self.email = ""
        self.service.LOGIN_TIMEOUT_SECONDS = 20
        await self.service.start_login(self.token_id)
        await self.wait_for_status("awaiting_login")
        status = await asyncio.wait_for(self.service.start_login(self.token_id), timeout=3)
        self.assertEqual("awaiting_login", status["status"])
        status = await asyncio.wait_for(self.service.sync(self.token_id), timeout=3)
        self.assertEqual("awaiting_login", status["status"])
        self.assertEqual(1, len(self.launches))

    async def test_concurrent_start_and_stop_cannot_leave_a_login_watcher(self):
        self.email = ""
        self.service.LOGIN_TIMEOUT_SECONDS = 20
        await asyncio.gather(self.service.start_login(self.token_id), self.service.stop(self.token_id))
        await asyncio.sleep(0.03)
        status = await self.service.get_status(self.token_id)
        self.assertEqual("stopped", status["status"])
        self.assertFalse(status["enabled"])
        self.assertFalse(status["browser_open"])
        self.assertTrue(all(task.done() for task in self.service._login_tasks.values()))

    async def test_concurrent_start_and_forget_cannot_recreate_metadata(self):
        self.email = ""
        self.service.LOGIN_TIMEOUT_SECONDS = 20
        await asyncio.gather(self.service.start_login(self.token_id), self.service.forget(self.token_id))
        await asyncio.sleep(0.03)
        status = await self.service.get_status(self.token_id)
        self.assertEqual("not_configured", status["status"])
        self.assertFalse(status["browser_open"])
        self.assertTrue(all(task.done() for task in self.service._login_tasks.values()))

    async def test_queued_login_cannot_launch_after_shutdown_begins(self):
        lock = self.service._lock(self.token_id)
        await lock.acquire()
        validated = asyncio.Event()
        original_token = self.service._token

        async def checked_token(token_id):
            token = await original_token(token_id)
            validated.set()
            return token

        self.service._token = checked_token
        starting = asyncio.create_task(self.service.start_login(self.token_id))
        await validated.wait()
        closing = asyncio.create_task(self.service.shutdown())
        while not self.service._closing:
            await asyncio.sleep(0)
        lock.release()
        results = await asyncio.gather(starting, closing, return_exceptions=True)
        self.assertIsInstance(results[0], RuntimeError)
        await asyncio.sleep(0.03)
        self.assertFalse(self.launches)
        self.assertFalse((await self.service.get_status(self.token_id))["browser_open"])
        self.assertTrue(all(task.done() for task in self.service._login_tasks.values()))

    async def test_queued_sync_cannot_launch_after_shutdown_begins(self):
        await self.service.start_login(self.token_id)
        await self.wait_login()
        await self.contexts[0].close()
        launch_count = len(self.launches)
        lock = self.service._lock(self.token_id)
        await lock.acquire()
        validated = asyncio.Event()
        original_token = self.service._token

        async def checked_token(token_id):
            token = await original_token(token_id)
            validated.set()
            return token

        self.service._token = checked_token
        syncing = asyncio.create_task(self.service.sync(self.token_id))
        await validated.wait()
        closing = asyncio.create_task(self.service.shutdown())
        while not self.service._closing:
            await asyncio.sleep(0)
        lock.release()
        results = await asyncio.gather(syncing, closing, return_exceptions=True)
        self.assertIsInstance(results[0], RuntimeError)
        self.assertEqual(launch_count, len(self.launches))
        self.assertFalse((await self.service.get_status(self.token_id))["browser_open"])
        with self.assertRaises(RuntimeError):
            await self.service.sync(self.token_id)

    async def test_failed_validation_is_sanitized_and_not_reported_ready(self):
        self.manager.save_managed_browser_cookies.side_effect = ValueError("secret-account secret-session")
        await self.service.start_login(self.token_id)
        status = await self.wait_login()
        self.assertEqual("error", status["status"])
        self.assertEqual("validation_failed", status["error_code"])
        self.assertNotIn("secret", json.dumps(status))

    async def test_due_refresh_respects_global_and_account_switches_with_failure_backoff(self):
        await self.service.start_login(self.token_id)
        await self.wait_login()
        await self.contexts[0].close()
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        async with self.db._connect(write=True) as conn:
            await conn.execute("UPDATE managed_browser_sessions SET last_attempt_at=?,last_sync_at=?", (old, old))
            await conn.commit()
        await self.db.update_token_refresh_config(enabled=False)
        await self.service.run_due_once()
        self.assertEqual(1, len(self.launches))
        await self.db.update_token_refresh_config(enabled=True)
        await self.db.update_token(self.token_id, auto_refresh_enabled=False)
        await self.service.run_due_once()
        self.assertEqual(1, len(self.launches))
        await self.db.update_token(self.token_id, auto_refresh_enabled=True)
        self.email = ""
        await self.service.run_due_once()
        self.assertEqual(2, len(self.launches))
        status = await self.service.get_status(self.token_id)
        self.assertEqual("needs_login", status["status"])
        await self.service.run_due_once()
        self.assertEqual(2, len(self.launches))

    async def test_unknown_token_rejected_and_forget_removes_metadata(self):
        with self.assertRaises(LookupError):
            await self.service.start_login(9999)
        await self.service.start_login(self.token_id)
        await self.wait_login()
        await self.service.forget(self.token_id)
        self.assertEqual("not_configured", (await self.service.get_status(self.token_id))["status"])
        self.assertTrue(self.contexts[0].closed)

    async def test_restart_preserves_configuration_but_does_not_open_browser(self):
        await self.service.start_login(self.token_id)
        await self.wait_login()
        await self.service.shutdown()
        from src.services.managed_browser import ManagedBrowserService
        other = ManagedBrowserService(self.db, self.manager, Path(self.temp.name) / "profiles", AsyncMock())
        await other.initialize()
        status = await other.get_status(self.token_id)
        self.assertEqual("ready", status["status"])
        self.assertTrue(status["enabled"])
        self.assertFalse(status["browser_open"])
        other.browser_factory.assert_not_awaited()
        await other.shutdown()

    async def test_navigation_race_during_login_is_retried(self):
        original_capture = self.service._capture
        calls = 0

        async def capture(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("Execution context was destroyed during navigation")
            return await original_capture(*args)

        self.service._capture = capture
        await self.service.start_login(self.token_id)
        self.assertEqual("ready", (await self.wait_login())["status"])
        self.assertEqual(2, calls)

    async def test_user_closing_login_browser_reports_needs_login(self):
        self.email = ""
        self.service.LOGIN_TIMEOUT_SECONDS = 20
        await self.service.start_login(self.token_id)
        await self.wait_for_status("awaiting_login")
        await self.contexts[0].close()
        status = await self.wait_login()
        self.assertEqual("needs_login", status["status"])
        self.assertEqual("browser_closed", status["error_code"])

    async def test_fallback_only_when_chrome_is_missing(self):
        launch = AsyncMock(side_effect=RuntimeError("profile is already in use"))
        self.service._playwright = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch), stop=AsyncMock())
        with self.assertRaisesRegex(RuntimeError, "profile is already"):
            await self.service._launch_browser(Path(self.temp.name) / "browser", headless=True, proxy=None)
        self.assertEqual(1, launch.await_count)
        launch.reset_mock()
        launch.side_effect = [RuntimeError("Chromium distribution 'chrome' is not found at test"), FakeContext()]
        await self.service._launch_browser(Path(self.temp.name) / "browser", headless=True, proxy=None)
        self.assertEqual(2, launch.await_count)

    async def test_real_browser_preserves_session_cookie_after_clean_exit(self):
        """Use only an invented loopback cookie, without visiting Google."""
        profile = Path(self.temp.name) / "runtime-fixture"
        first = None
        second = None
        try:
            try:
                first = await self.service._launch_browser(profile, headless=True, proxy=None)
            except Exception as exc:
                if "Executable doesn't exist" in str(exc) or "not found" in str(exc):
                    self.skipTest("Chrome/Playwright Chromium not installed")
                raise
            await first.add_cookies([{"name": "fixture_session", "value": "synthetic", "url": "http://127.0.0.1/"}])
            await first.close()
            first = None
            second = await self.service._launch_browser(profile, headless=True, proxy=None)
            cookie = next((c for c in await second.cookies() if c["name"] == "fixture_session"), None)
            self.assertIsNotNone(cookie)
            self.assertEqual("synthetic", cookie["value"])
        finally:
            if first:
                await first.close()
            if second:
                await second.close()
