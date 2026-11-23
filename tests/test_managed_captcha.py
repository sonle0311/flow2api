"""Managed captcha mints reCAPTCHA tokens in each account's own headless Chrome profile.

All browsers are fakes; no Chrome is launched and no Flow request is sent.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

from src.core.config import Config, config
from src.core.database import Database
from src.core.models import Token
from src.services.flow_client import FlowClient
from src.services.managed_browser import ManagedBrowserService, ProfileBusyError
from src.services.managed_captcha import (
    PROJECT_URL,
    _RECAPTCHA_READY_SCRIPT,
    ManagedCaptchaService,
)

PROJECT = "9ad7d492-769d-4e5a-aba0-82d1aed22071"


class Tracker:
    def __init__(self):
        self.active = 0
        self.peak = 0


class FakePage:
    def __init__(self, tracker=None, delay=0.0):
        self.url = "about:blank"
        self.closed = False
        self.gotos = []
        self.ready = True
        self.fail_execute = False
        self.tracker = tracker
        self.delay = delay
        self.executed = []

    async def goto(self, url, **kwargs):
        self.gotos.append(url)
        self.url = url

    async def evaluate(self, script, arg=None):
        if script == _RECAPTCHA_READY_SCRIPT:
            return self.ready and self.url == PROJECT_URL.format(arg)
        self.executed.append(script)
        if self.tracker:
            self.tracker.active += 1
            self.tracker.peak = max(self.tracker.peak, self.tracker.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail_execute:
                raise RuntimeError("Target page, context or browser has been closed")
            action = "VIDEO_GENERATION" if "VIDEO_GENERATION" in script else "IMAGE_GENERATION"
            return {"ok": True, "token": f"token-{action}"}
        finally:
            if self.tracker:
                self.tracker.active -= 1

    async def close(self):
        self.closed = True

    def is_closed(self):
        return self.closed


class FakeContext:
    def __init__(self, tracker=None, delay=0.0):
        self.pages = []
        self.init_scripts = []
        self.tracker = tracker
        self.delay = delay

    async def add_init_script(self, script):
        self.init_scripts.append(script)

    async def new_page(self):
        page = FakePage(self.tracker, self.delay)
        self.pages.append(page)
        return page


class FakeBrowser:
    def __init__(self, tracker=None, delay=0.0):
        self.contexts = {}
        self.opened = []
        self.released = []
        self.busy = False
        self.tracker = tracker
        self.delay = delay

    async def open_context(self, token_id, *, wait_seconds=30):
        self.opened.append(token_id)
        if self.busy:
            raise ProfileBusyError("profile_busy")
        return self.contexts.setdefault(token_id, FakeContext(self.tracker, self.delay))

    async def release_context(self, token_id):
        self.released.append(token_id)
        return True


def pages_of(browser, token_id=1):
    return browser.contexts[token_id].pages


class ManagedCaptchaServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.browser = FakeBrowser()
        self.service = ManagedCaptchaService(self.browser)
        self.addAsyncCleanup(self.service.close)

    async def test_first_mint_opens_project_page_and_later_mints_reuse_the_tab(self):
        image = await self.service.get_token(PROJECT, "image_generation", token_id=1)
        video = await self.service.get_token(PROJECT, "VIDEO_GENERATION", token_id=1)
        self.assertEqual((image, video), ("token-IMAGE_GENERATION", "token-VIDEO_GENERATION"))
        context = self.browser.contexts[1]
        self.assertEqual(self.browser.opened, [1])
        self.assertEqual(len(context.init_scripts), 1)
        self.assertEqual(len(context.pages), 1)
        self.assertEqual(context.pages[0].gotos, [PROJECT_URL.format(PROJECT)])
        self.assertIn('"IMAGE_GENERATION"', context.pages[0].executed[0])

    async def test_tab_that_left_the_project_page_is_navigated_back(self):
        await self.service.get_token(PROJECT, "IMAGE_GENERATION", token_id=1)
        page = pages_of(self.browser)[0]
        page.url = "https://flow.google.com/projects"
        self.assertEqual(await self.service.get_token(PROJECT, "IMAGE_GENERATION", token_id=1), "token-IMAGE_GENERATION")
        self.assertEqual(len(page.gotos), 2)
        self.assertEqual(len(pages_of(self.browser)), 1)

    async def test_failed_mint_rebuilds_the_tab_once(self):
        await self.service.get_token(PROJECT, "IMAGE_GENERATION", token_id=1)
        first = pages_of(self.browser)[0]
        first.fail_execute = True
        self.assertEqual(await self.service.get_token(PROJECT, "IMAGE_GENERATION", token_id=1), "token-IMAGE_GENERATION")
        self.assertTrue(first.closed)
        self.assertEqual(len(pages_of(self.browser)), 2)

    async def test_persistent_failure_gives_up_after_one_rebuild(self):
        original = FakePage.evaluate

        async def always_fail(page, script, arg=None):
            if script != _RECAPTCHA_READY_SCRIPT:
                raise RuntimeError("boom")
            return await original(page, script, arg)

        with patch.object(FakePage, "evaluate", always_fail):
            self.assertIsNone(await self.service.get_token(PROJECT, "IMAGE_GENERATION", token_id=1))
        self.assertEqual(len(pages_of(self.browser)), 2)
        self.assertTrue(all(page.closed for page in pages_of(self.browser)))

    async def test_busy_profile_fails_fast_without_retry(self):
        self.browser.busy = True
        self.assertIsNone(await self.service.get_token(PROJECT, "IMAGE_GENERATION", token_id=1))
        self.assertEqual(self.browser.opened, [1])

    async def test_signed_out_profile_never_returns_a_token(self):
        self.service.READY_SECONDS = 0.05

        async def to_sign_in(page, url, **kwargs):
            page.url = "https://accounts.google.com/v3/signin"

        with patch.object(FakePage, "goto", to_sign_in):
            self.assertIsNone(await self.service.get_token(PROJECT, "IMAGE_GENERATION", token_id=1))

    async def test_missing_account_or_project_returns_none_without_opening_a_browser(self):
        self.assertIsNone(await self.service.get_token(PROJECT, "IMAGE_GENERATION", token_id=None))
        self.assertIsNone(await self.service.get_token("", "IMAGE_GENERATION", token_id=1))
        self.assertEqual(self.browser.opened, [])

    async def test_only_recaptcha_rejections_reload_the_tab(self):
        await self.service.get_token(PROJECT, "IMAGE_GENERATION", token_id=1)
        page = pages_of(self.browser)[0]
        await self.service.report_flow_error(token_id=1, error_reason="content_policy", error_message="PUBLIC_ERROR_SEXUAL")
        self.assertFalse(page.closed)
        await self.service.report_flow_error(
            token_id=1, error_reason="500", error_message="rpc=ogiZ0b, error=PUBLIC_ERROR_UNUSUAL_ACTIVITY",
        )
        self.assertTrue(page.closed)
        await self.service.get_token(PROJECT, "IMAGE_GENERATION", token_id=1)
        self.assertEqual(len(pages_of(self.browser)), 2)

    async def test_same_account_mints_queue_while_accounts_run_in_parallel(self):
        tracker = Tracker()
        service = ManagedCaptchaService(FakeBrowser(tracker, delay=0.05))
        self.addAsyncCleanup(service.close)
        await asyncio.gather(*(service.get_token(PROJECT, "IMAGE_GENERATION", token_id=1) for _ in range(3)))
        self.assertEqual(tracker.peak, 1)
        tracker.peak = 0
        await asyncio.gather(*(service.get_token(PROJECT, "IMAGE_GENERATION", token_id=i) for i in (1, 2, 3)))
        self.assertEqual(tracker.peak, 3)

    async def test_idle_tab_and_profile_are_released_but_busy_ones_are_kept(self):
        await self.service.get_token(PROJECT, "IMAGE_GENERATION", token_id=1)
        await self.service.get_token(PROJECT, "IMAGE_GENERATION", token_id=2)
        self.service.IDLE_SECONDS = 0
        async with self.service._lock(2):
            await self.service.reap_idle()
        self.assertTrue(pages_of(self.browser, 1)[0].closed)
        self.assertFalse(pages_of(self.browser, 2)[0].closed)
        self.assertEqual(self.browser.released, [1])
        self.assertEqual(await self.service.get_token(PROJECT, "IMAGE_GENERATION", token_id=1), "token-IMAGE_GENERATION")
        self.assertEqual(len(pages_of(self.browser, 1)), 2)


class BrowserContextLeaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(str(Path(self.temp.name) / "test.db"))
        await self.db.init_db()
        self.token_id = await self.db.add_token(Token(st="frontend-old", email="account@example.com"))
        self.launches = 0

        async def factory(profile_path, *, headless, proxy):
            self.launches += 1
            self.headless = headless
            return SimpleNamespace(
                pages=[], closed=False, on=lambda *a: None, close=AsyncMock(),
            )

        manager = SimpleNamespace(flow_client=SimpleNamespace(proxy_manager=None))
        self.service = ManagedBrowserService(self.db, manager, Path(self.temp.name) / "profiles", factory)
        await self.service.initialize()
        self.addAsyncCleanup(self.service.shutdown)

    async def test_open_context_launches_headless_once_and_reuses_it(self):
        first = await self.service.open_context(self.token_id)
        second = await self.service.open_context(self.token_id)
        self.assertIs(first, second)
        self.assertEqual(self.launches, 1)
        self.assertTrue(self.headless)

    async def test_open_context_reports_a_profile_held_by_sync_or_login(self):
        async with self.service._lock(self.token_id):
            with self.assertRaises(ProfileBusyError):
                await self.service.open_context(self.token_id, wait_seconds=0.05)
        self.service._manual_browsers[self.token_id] = SimpleNamespace(is_running=True, close=AsyncMock())
        with self.assertRaises(ProfileBusyError):
            await self.service.open_context(self.token_id)
        self.assertEqual(self.launches, 0)

    async def test_release_context_closes_idle_profile_but_not_a_busy_one(self):
        context = await self.service.open_context(self.token_id)
        async with self.service._lock(self.token_id):
            self.assertFalse(await self.service.release_context(self.token_id))
        context.close.assert_not_awaited()
        self.assertTrue(await self.service.release_context(self.token_id))
        context.close.assert_awaited_once()
        await self.service.open_context(self.token_id)
        self.assertEqual(self.launches, 2)


class FlowClientManagedRoutingTests(unittest.IsolatedAsyncioTestCase):
    def managed(self):
        return patch.object(Config, "captcha_method", new_callable=PropertyMock, return_value="managed")

    async def test_token_comes_from_the_account_profile_without_browser_fingerprint(self):
        client = FlowClient(None)
        client.managed_captcha = SimpleNamespace(get_token=AsyncMock(return_value="minted"))
        with self.managed():
            result = await client._get_recaptcha_token(PROJECT, "VIDEO_GENERATION", token_id=7)
        self.assertEqual(result, ("minted", None))
        client.managed_captcha.get_token.assert_awaited_once_with(PROJECT, "VIDEO_GENERATION", token_id=7)
        self.assertIsNone(client.get_request_fingerprint())
        self.assertEqual(client._get_captcha_request_context()["method"], "managed")

    async def test_unconfigured_service_or_empty_mint_yields_no_token(self):
        client = FlowClient(None)
        with self.managed():
            self.assertEqual(await client._get_recaptcha_token(PROJECT, token_id=7), (None, None))
            client.managed_captcha = SimpleNamespace(get_token=AsyncMock(return_value=None))
            self.assertEqual(await client._get_recaptcha_token(PROJECT, token_id=7), (None, None))

    async def test_upstream_rejection_is_reported_for_the_minting_account(self):
        client = FlowClient(None)
        client.managed_captcha = SimpleNamespace(
            get_token=AsyncMock(return_value="minted"), report_flow_error=AsyncMock(),
        )
        with self.managed():
            await client._get_recaptcha_token(PROJECT, "IMAGE_GENERATION", token_id=7)
            await client._notify_browser_captcha_error(
                None, PROJECT, "500", "PUBLIC_ERROR_UNUSUAL_ACTIVITY",
            )
        client.managed_captcha.report_flow_error.assert_awaited_once_with(
            token_id=7, error_reason="500", error_message="PUBLIC_ERROR_UNUSUAL_ACTIVITY",
        )


if __name__ == "__main__":
    unittest.main()
