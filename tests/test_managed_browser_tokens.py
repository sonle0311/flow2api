import asyncio
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.database import Database
from src.core.models import Token
from src.services.token_manager import TokenManager


EMAIL = "account@example.com"
OLD = json.dumps([
    {"name": "OSID", "value": "old", "domain": "flow.google.com", "path": "/"},
    {"name": "SID", "value": "account", "domain": ".google.com", "path": "/"},
])
NEW = OLD.replace('"old"', '"new"')


class ManagedBrowserTokenTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(self.temp.name + "/flow.db")
        await self.db.init_db()
        self.token_id = await self.db.add_token(Token(
            st="frontend-old", at="old-at", email=EMAIL,
            login_account=EMAIL, google_cookies=OLD,
        ))
        self.flow = MagicMock()
        self.flow.get_request_fingerprint.return_value = None
        self.flow.st_to_at = AsyncMock(return_value={
            "access_token": "flow-frontend-cookie", "expires": "2026-12-01T00:00:00Z",
            "credits": 42, "userPaygateTier": "PAYGATE_TIER_ONE",
        })
        self.manager = TokenManager(self.db, self.flow)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_browser_save_validates_and_only_explicit_login_reactivates(self):
        await self.db.update_token(self.token_id, is_active=False)
        result = {"email": EMAIL.upper(), "google_cookies": NEW}
        self.assertTrue(await self.manager.save_managed_browser_cookies(self.token_id, result))
        token = await self.db.get_token(self.token_id)
        self.assertEqual(token.google_cookies, NEW)
        self.assertFalse(token.is_active)
        self.assertEqual(token.last_st_refresh_result, "success")
        self.flow.st_to_at.assert_awaited_once()
        self.assertTrue(await self.manager.save_managed_browser_cookies(
            self.token_id, result, reactivate=True,
        ))
        self.assertTrue((await self.db.get_token(self.token_id)).is_active)

    async def test_wrong_identity_never_changes_account_or_sends_cookie_upstream(self):
        with self.assertRaises(ValueError):
            await self.manager.save_managed_browser_cookies(
                self.token_id, {"email": "other@example.com", "google_cookies": NEW}, reactivate=True,
            )
        self.flow.st_to_at.assert_not_awaited()
        token = await self.db.get_token(self.token_id)
        self.assertEqual(token.email, EMAIL)
        self.assertEqual(token.google_cookies, OLD)

    async def test_validation_failure_leaves_credentials_and_disabled_state_unchanged(self):
        await self.db.update_token(self.token_id, is_active=False)
        self.flow.st_to_at.side_effect = RuntimeError("upstream unavailable")
        with self.assertRaises(RuntimeError):
            await self.manager.save_managed_browser_cookies(
                self.token_id, {"email": EMAIL, "google_cookies": NEW}, reactivate=True,
            )
        token = await self.db.get_token(self.token_id)
        self.assertEqual(token.google_cookies, OLD)
        self.assertFalse(token.is_active)

    async def test_identity_edited_during_rpc_cannot_receive_previous_profile_cookie(self):
        async def validating(*args, **kwargs):
            await self.db.update_token(
                self.token_id, email="changed@example.com", login_account="changed@example.com",
            )
            return {"access_token": "flow-frontend-cookie"}

        self.flow.st_to_at.side_effect = validating
        with self.assertRaises(RuntimeError):
            await self.manager.save_managed_browser_cookies(
                self.token_id, {"email": EMAIL, "google_cookies": NEW}, reactivate=True,
            )
        token = await self.db.get_token(self.token_id)
        self.assertEqual(token.email, "changed@example.com")
        self.assertEqual(token.google_cookies, OLD)

    def managed(self, status="ready"):
        service = MagicMock()
        service.get_status = AsyncMock(return_value={"enabled": True, "status": status})
        service.sync = AsyncMock(return_value={"enabled": True, "status": status})
        service.run_due_once = AsyncMock()
        service.forget = AsyncMock()
        self.manager.managed_browser = service
        return service

    async def test_on_demand_browser_sync_holds_no_token_lock(self):
        service = self.managed()

        async def sync(token_id):
            # The browser callback acquires the same lock; nesting would deadlock.
            return {"status": "ready"} if await self.manager.save_managed_browser_cookies(
                token_id, {"email": EMAIL, "google_cookies": NEW},
            ) else {"status": "error"}

        service.sync.side_effect = sync
        self.assertTrue(await asyncio.wait_for(self.manager._refresh_at_inner(self.token_id), 2))
        service.sync.assert_awaited_once_with(self.token_id)

    async def test_login_required_does_not_disable_managed_account(self):
        self.managed("needs_login")
        self.assertFalse(await self.manager._refresh_at_inner(self.token_id))
        self.assertTrue((await self.db.get_token(self.token_id)).is_active)
        self.flow.st_to_at.assert_not_awaited()

    async def test_manual_refresh_uses_profile_outside_token_lock(self):
        service = self.managed()
        self.assertTrue(await self.manager.refresh_cookies(self.token_id))
        service.sync.assert_awaited_once_with(self.token_id)
        self.flow.st_to_at.assert_not_awaited()

    async def test_scheduler_uses_profile_once_and_skips_legacy_refresh(self):
        service = self.managed()
        await self.db.update_token_refresh_config(enabled=True)
        with patch.object(self.manager, "_refresh_protocol_token", new_callable=AsyncMock) as legacy:
            await self.manager.run_protocol_refresh_once()
        service.run_due_once.assert_awaited_once()
        legacy.assert_not_awaited()

    async def test_disabled_global_refresh_does_not_launch_profiles(self):
        service = self.managed()
        await self.db.update_token_refresh_config(enabled=False)
        await self.manager.run_protocol_refresh_once()
        service.run_due_once.assert_not_awaited()

    async def test_delete_closes_managed_browser_before_database_removal(self):
        service = self.managed()

        async def forget(token_id):
            self.assertIsNotNone(await self.db.get_token(token_id))

        service.forget.side_effect = forget
        await self.manager.delete_token(self.token_id)
        service.forget.assert_awaited_once_with(self.token_id)
        self.assertIsNone(await self.db.get_token(self.token_id))
