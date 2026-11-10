"""Account cookie boundaries using only synthetic nodriver transports."""

import asyncio
import json
import types
import unittest
from unittest.mock import AsyncMock, patch

from nodriver import cdp

from src.services.browser_captcha_personal import BrowserCaptchaService, ResidentTabInfo


class _Tab:
    type_ = "page"

    def __init__(self, browser, target_id, context_id):
        self.browser = browser
        self.target_id = target_id
        self.target = types.SimpleNamespace(browser_context_id=context_id)
        self.closed = False

    async def send(self, command):
        return await self.browser.dispatch(command, self.target.browser_context_id)

    async def close(self):
        self.closed = True


class _Browser:
    stopped = False

    def __init__(self):
        self.targets = []
        self.jars = {None: {"SID": "manual-login"}}
        self.commands = []
        self.fail_storage_reads = False
        self.cookies = types.SimpleNamespace(get_all=AsyncMock(return_value=[
            self.cookie("SID", "manual-login")
        ]))

    @staticmethod
    def cookie(name, value):
        return types.SimpleNamespace(name=name, value=value, domain=".google.com", path="/")

    async def send(self, command):
        return await self.dispatch(command, None)

    async def update_targets(self):
        pass

    async def dispatch(self, command, tab_context):
        payload = next(command)
        method, params = payload["method"], payload.get("params", {})
        self.commands.append(payload)
        context_id = params.get("browserContextId", tab_context)
        if method == "Target.createBrowserContext":
            context_id = cdp.browser.BrowserContextID(f"context-{len(self.jars)}")
            self.jars[context_id] = {}
            return context_id
        if method == "Target.createTarget":
            target_id = cdp.target.TargetID(f"tab-{len(self.targets)}")
            self.targets.append(_Tab(self, target_id, context_id))
            return target_id
        if method in {"Storage.setCookies", "Network.setCookies"}:
            self.jars[context_id].update({c["name"]: c["value"] for c in params["cookies"]})
            return
        if method in {"Storage.clearCookies", "Network.clearBrowserCookies"}:
            self.jars[context_id].clear()
            return
        if method in {"Storage.getCookies", "Network.getAllCookies", "Network.getCookies"}:
            if method == "Storage.getCookies" and self.fail_storage_reads:
                raise RuntimeError("context cookie read failed")
            return [self.cookie(k, v) for k, v in self.jars[context_id].items()]
        if method == "Target.disposeBrowserContext":
            self.jars.pop(context_id)
            return
        raise AssertionError(f"Unexpected CDP command: {method}")


class PersonalContextIsolationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = BrowserCaptchaService()
        self.browser = _Browser()
        self.service.browser = self.browser
        self.service._browser_has_page_targets = AsyncMock(return_value=True)
        self.service._apply_tab_startup_spoofs = AsyncMock()
        self.service._apply_configured_browser_startup_cookie = AsyncMock()
        self.service._tab_get = AsyncMock()
        self.service._tab_reload = AsyncMock()
        self.service._wait_for_document_ready = AsyncMock(return_value=True)
        self.service._wait_for_recaptcha = AsyncMock(return_value=True)
        self.service._warmup_google_context_cookies = AsyncMock(return_value=True)
        self.service._load_token_cookie = AsyncMock(side_effect=lambda key: {
            1: "SID=synthetic-A; HSID=only-A", 2: "SID=synthetic-B", 3: None
        }[key])

        async def open_default(*args, **kwargs):
            tab = _Tab(self.browser, "default-tab", None)
            self.browser.targets.append(tab)
            return tab

        self.service._open_visible_browser_tab = AsyncMock(side_effect=open_default)

    async def resident(self, key):
        tab, context_id = await self.service._create_isolated_context_tab(
            "about:blank", label=f"account-{key}"
        )
        return ResidentTabInfo(tab, f"slot-{key}", browser_context_id=context_id)

    async def test_headed_and_headless_accounts_retain_distinct_cookies_on_reuse(self):
        for headless in (False, True):
            with self.subTest(headless=headless):
                self.service.headless = headless
                first, second = await self.resident(1), await self.resident(2)
                self.assertTrue(await self.service._apply_token_cookie_binding(first, 1, label="first"))
                self.assertTrue(await self.service._apply_token_cookie_binding(second, 2, label="second"))
                self.assertTrue(await self.service._ensure_resident_token_binding(first, 1, label="reuse"))
                self.assertEqual(self.browser.jars[first.browser_context_id]["SID"], "synthetic-A")
                self.assertEqual(self.browser.jars[second.browser_context_id]["SID"], "synthetic-B")
                self.assertIsNotNone(first.browser_context_id)
                self.assertNotEqual(first.browser_context_id, second.browser_context_id)
                self.assertEqual(self.browser.jars[None], {"SID": "manual-login"})

    async def test_account_switch_removes_cookies_absent_from_new_account(self):
        self.service.headless = True
        resident = await self.resident(1)
        await self.service._apply_token_cookie_binding(resident, 1, label="first")
        await self.service._ensure_resident_token_binding(resident, 2, label="switch")
        self.assertNotIn("HSID", self.browser.jars[resident.browser_context_id])
        self.assertEqual(self.browser.jars[resident.browser_context_id]["SID"], "synthetic-B")

    async def test_clear_cookie_less_account_is_scoped_even_with_stored_context(self):
        for headless in (False, True):
            with self.subTest(headless=headless):
                self.service.headless = headless
                resident = await self.resident(1)
                await self.service._apply_token_cookie_binding(resident, 1, label="first")
                self.assertTrue(await self.service._ensure_resident_token_binding(resident, 3, label="clear"))
                self.assertEqual(self.browser.jars[resident.browser_context_id], {})
                self.assertEqual(self.browser.jars[None], {"SID": "manual-login"})
                self.assertEqual(self.browser.commands[-1], {
                    "method": "Storage.clearCookies",
                    "params": {"browserContextId": str(resident.browser_context_id)},
                })

    async def test_default_context_binding_cache_is_rejected(self):
        self.service.headless = False
        resident = ResidentTabInfo(_Tab(self.browser, "old", None), "old", token_id=1)
        resident.cookie_signature = self.service._normalize_cookie_signature(
            await self.service._load_token_cookie(1)
        )
        self.assertFalse(await self.service._ensure_resident_token_binding(resident, 1, label="stale"))
        self.assertFalse(await self.service._apply_token_cookie_binding(resident, 1, label="stale"))

    async def test_stale_isolated_context_id_cannot_validate_a_default_tab(self):
        self.service.headless = False
        resident = ResidentTabInfo(
            _Tab(self.browser, "default", None), "old", token_id=1,
            browser_context_id=cdp.browser.BrowserContextID("no-longer-tab-context"),
        )
        resident.cookie_signature = self.service._normalize_cookie_signature(
            await self.service._load_token_cookie(1)
        )
        self.assertFalse(await self.service._ensure_resident_token_binding(resident, 1, label="stale"))

    async def test_context_mismatch_prevents_cookie_export_or_warmup(self):
        self.service.headless = True
        resident = await self.resident(1)
        other = await self.resident(2)
        resident.token_id = 1
        resident.browser_context_id = other.browser_context_id
        self.service.db = types.SimpleNamespace(update_token=AsyncMock())
        self.service._get_browser_cookies = AsyncMock(return_value=[])
        self.assertFalse(await self.service._persist_context_cookies_to_token(resident, 1, label="mismatch"))
        self.service._get_browser_cookies.assert_not_awaited()
        # Exercise the production warmup rather than the synthetic setup stub.
        self.assertFalse(await BrowserCaptchaService._warmup_google_context_cookies(
            self.service, resident, label="mismatch"
        ))
        self.service._tab_get.assert_not_awaited()

    async def test_cookie_less_binding_does_not_keep_startup_account_cookies(self):
        self.service.headless = True
        resident = await self.resident(3)
        self.browser.jars[resident.browser_context_id] = {"SID": "startup-account"}
        resident.token_id = 3
        self.assertFalse(await self.service._apply_token_cookie_binding(resident, 3, label="empty"))
        self.assertEqual(self.browser.jars[resident.browser_context_id], {})

    async def test_cookie_less_signature_is_not_proof_of_an_empty_account_context(self):
        self.service.headless = True
        resident = await self.resident(3)
        resident.token_id = 3
        self.browser.jars[resident.browser_context_id] = {"SID": "startup-account"}
        self.assertTrue(await self.service._ensure_resident_token_binding(resident, 3, label="empty"))
        self.assertEqual(self.browser.jars[resident.browser_context_id], {})

    async def test_context_cookie_read_failure_never_exports_default_login(self):
        self.browser.fail_storage_reads = True
        context_id = cdp.browser.BrowserContextID("isolated")
        with self.assertRaisesRegex(RuntimeError, "context cookie read failed"):
            await self.service._get_browser_cookies("export", browser_context_id=context_id)
        self.browser.cookies.get_all.assert_not_awaited()

    async def test_computed_session_cookie_capture_reads_account_context_first(self):
        self.service.headless = True
        resident = await self.resident(1)
        self.browser.jars[resident.browser_context_id] = {"SID": "synthetic-A"}
        with patch("src.services.browser_captcha_personal.set_cached_session_cookies"):
            cookies = await self.service._cache_session_cookies_for_computed(resident)
        self.assertEqual(cookies, {"SID": "synthetic-A"})
        self.assertEqual(self.browser.commands[-1], {
            "method": "Storage.getCookies",
            "params": {"browserContextId": str(resident.browser_context_id)},
        })

    async def test_simultaneous_refresh_and_binding_do_not_change_other_account(self):
        self.service.headless = False
        first, second = await self.resident(1), await self.resident(2)
        await asyncio.gather(
            self.service._apply_token_cookie_binding(first, 1, label="solve"),
            self.service._apply_token_cookie_binding(second, 2, label="refresh"),
        )
        first_cookies, second_cookies = await asyncio.gather(
            self.service._get_browser_cookies("solve", browser_context_id=first.browser_context_id),
            self.service._get_browser_cookies("refresh", browser_context_id=second.browser_context_id),
        )
        self.assertEqual({c.name: c.value for c in first_cookies}["SID"], "synthetic-A")
        self.assertEqual({c.name: c.value for c in second_cookies}["SID"], "synthetic-B")

    async def test_cookie_refresh_during_another_account_solve_keeps_both_sessions(self):
        self.service.headless = False
        first, second = await self.resident(1), await self.resident(2)
        await self.service._apply_token_cookie_binding(first, 1, label="first")
        await self.service._apply_token_cookie_binding(second, 2, label="second")
        self.service.initialize = AsyncMock()
        self.service._ensure_resident_tab = AsyncMock(return_value=(second.slot_id, second))
        self.service._consume_resident_slot_reservation = AsyncMock()
        self.service._tab_evaluate = AsyncMock(return_value={
            "host": "flow.google.com", "ready": "complete", "email": "synthetic-B@example.com"
        })
        self.service._finalize_resident_solve_locked = AsyncMock(return_value=1)
        self.service._maybe_execute_pending_fresh_profile_restart = AsyncMock()
        solve_started, refreshed = asyncio.Event(), asyncio.Event()

        async def execute(tab, *args, **kwargs):
            self.assertIs(tab, first.tab)
            solve_started.set()
            await refreshed.wait()
            self.assertEqual(self.browser.jars[first.browser_context_id]["SID"], "synthetic-A")
            return {"token": "synthetic-captcha"}

        async def refresh():
            await solve_started.wait()
            try:
                return await self.service.refresh_google_cookies(None, token_id=2)
            finally:
                refreshed.set()

        self.service._execute_recaptcha_on_tab = AsyncMock(side_effect=execute)
        captcha, exported = await asyncio.wait_for(asyncio.gather(
            self.service._solve_with_resident_tab(
                first.slot_id, "project", first, "IMAGE_GENERATION", success_label="test"
            ),
            refresh(),
        ), timeout=3)
        self.assertEqual(captcha, "synthetic-captcha")
        self.assertEqual(exported["email"], "synthetic-B@example.com")
        self.assertEqual({c["name"]: c["value"] for c in json.loads(exported["google_cookies"])}["SID"], "synthetic-B")

    async def test_closing_resident_disposes_only_its_context(self):
        self.service.headless = False
        first, second = await self.resident(1), await self.resident(2)
        self.service._resident_tabs[first.slot_id] = first
        await self.service._close_resident_tab(first.slot_id)
        self.assertNotIn(first.browser_context_id, self.browser.jars)
        self.assertIn(second.browser_context_id, self.browser.jars)
        self.assertEqual(self.browser.jars[None], {"SID": "manual-login"})

    async def test_cancelled_context_initialization_disposes_cookie_store(self):
        self.service.headless = True
        self.service._apply_tab_startup_spoofs.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.resident(1)
        self.assertEqual(self.browser.jars, {None: {"SID": "manual-login"}})

    async def test_failed_binding_never_reaches_resident_captcha_execution(self):
        self.service.headless = False
        resident = await self.resident(1)
        self.service.initialize = AsyncMock()
        self.service._wait_for_pending_fresh_profile_restart_before_solve = AsyncMock()
        self.service._ensure_resident_tab = AsyncMock(return_value=(resident.slot_id, resident))
        self.service._ensure_resident_token_binding = AsyncMock(return_value=False)
        self.service._rebuild_resident_tab = AsyncMock(return_value=(resident.slot_id, None))
        self.service._solve_with_resident_tab = AsyncMock(return_value="unsafe-token")
        result = await self.service._get_token_direct("project", token_id=1)
        self.assertIsNone(result)
        self.service._solve_with_resident_tab.assert_not_awaited()

    async def test_new_resident_rejects_failed_account_cookie_binding(self):
        self.service.headless = False
        self.service._tab_evaluate = AsyncMock(return_value="complete")
        self.service._apply_token_cookie_binding = AsyncMock(return_value=False)
        self.service._open_labs_bootstrap_page = AsyncMock(return_value=True)
        self.service._refresh_last_fingerprint = AsyncMock(return_value=None)
        self.service._cache_session_cookies_for_computed = AsyncMock()
        result = await self.service._create_resident_tab("new", token_id=1)
        self.assertIsNone(result)
        self.service._open_labs_bootstrap_page.assert_not_awaited()
        self.assertEqual(self.browser.jars, {None: {"SID": "manual-login"}})

    async def test_legacy_rejects_failed_account_binding_before_flow_navigation(self):
        self.service.headless = False
        self.service._initialized = True
        self.service._apply_token_cookie_binding = AsyncMock(return_value=False)
        self.service._open_labs_bootstrap_page = AsyncMock(side_effect=AssertionError("unsafe navigation"))
        self.assertEqual(await self.service._get_token_legacy("project", token_id=1), (None, None))
        self.service._open_labs_bootstrap_page.assert_not_awaited()
        self.assertEqual(self.browser.jars, {None: {"SID": "manual-login"}})
