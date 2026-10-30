import asyncio
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.api import admin
from src.core.database import Database
from src.core.models import Token
from src.main import app
from src.services.token_manager import TokenManager


EMAIL = "new-account@example.com"
ENDPOINT = "/api/browser-sessions/accounts"


class BrowserAccountBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(self.temp.name + "/flow.db")
        await self.db.init_db()
        self.flow = MagicMock()
        self.flow.st_to_at = AsyncMock()
        self.flow.create_project = AsyncMock()
        self.manager = TokenManager(self.db, self.flow)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_empty_database_can_prepare_email_only_without_credentials_or_upstream_calls(self):
        token, created = await self.manager.prepare_browser_account("  New-Account@EXAMPLE.com  ")
        self.assertTrue(created)
        self.assertEqual(token.email, EMAIL)
        self.assertEqual(token.login_account, EMAIL)
        self.assertFalse(token.is_active)
        self.assertFalse(token.at)
        self.assertEqual(token.google_cookies, "")
        self.assertTrue(token.st.startswith("browser-pending-"))
        self.assertTrue(token.auto_refresh_enabled)
        self.assertEqual(await self.db.get_active_tokens(), [])
        self.assertEqual(len(await self.db.get_all_tokens()), 1)
        self.flow.st_to_at.assert_not_awaited()
        self.flow.create_project.assert_not_awaited()

    async def test_existing_account_is_reused_without_modifying_credentials_or_settings(self):
        existing = Token(st="existing-session", email=EMAIL, login_account=EMAIL,
                         google_cookies="existing-cookie", is_active=False,
                         image_enabled=False, refresh_interval_minutes=77)
        existing.id = await self.db.add_token(existing)
        token, created = await self.manager.prepare_browser_account(EMAIL.upper())
        self.assertFalse(created)
        self.assertEqual(token.id, existing.id)
        self.assertEqual(token.google_cookies, "existing-cookie")
        self.assertFalse(token.is_active)
        self.assertFalse(token.image_enabled)
        self.assertEqual(token.refresh_interval_minutes, 77)

    async def test_concurrent_preparations_cannot_create_duplicate_email_accounts(self):
        other = TokenManager(self.db, self.flow)
        results = await asyncio.gather(self.manager.prepare_browser_account(EMAIL), other.prepare_browser_account(EMAIL.upper()))
        self.assertEqual(results[0][0].id, results[1][0].id)
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(len(await self.db.get_all_tokens()), 1)

    async def test_invalid_email_creates_no_record(self):
        for value in ("", "not-email", "name@example", "a b@example.com", "<script>@example.com"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                await self.manager.prepare_browser_account(value)
        self.assertEqual(await self.db.get_all_tokens(), [])

    async def test_pending_account_cannot_be_manually_enabled(self):
        account, _ = await self.manager.prepare_browser_account(EMAIL)
        with self.assertRaises(ValueError):
            await self.manager.enable_token(account.id)
        self.assertFalse((await self.db.get_token(account.id)).is_active)
        self.assertEqual(await self.db.get_active_tokens(), [])

    async def test_validated_login_replaces_pending_marker_and_first_generation_can_create_project(self):
        account, _ = await self.manager.prepare_browser_account(EMAIL)
        cookies = json.dumps([
            {"name": "OSID", "value": "session", "domain": "flow.google.com", "path": "/"},
            {"name": "SID", "value": "account", "domain": ".google.com", "path": "/"},
        ])
        self.flow.get_request_fingerprint.return_value = None
        self.flow.st_to_at.return_value = {
            "access_token": "flow-frontend-cookie", "expires": "2026-12-01T00:00:00Z",
        }
        self.assertTrue(await self.manager.save_managed_browser_cookies(
            account.id, {"email": EMAIL, "google_cookies": cookies}, reactivate=True,
        ))
        saved = await self.db.get_token(account.id)
        self.assertTrue(saved.is_active)
        self.assertTrue(saved.st.startswith("frontend-"))
        self.assertEqual(saved.email, EMAIL)
        self.flow.create_project.return_value = "new-flow-project"
        with patch.object(self.manager, "_get_project_pool_size", return_value=1):
            project = await self.manager.ensure_project_exists(account.id)
        self.assertEqual(project, "new-flow-project")
        self.assertEqual((await self.db.get_token(account.id)).current_project_id, project)


def test_bootstrap_requires_admin_before_creating_or_launching(monkeypatch):
    manager = MagicMock(prepare_browser_account=AsyncMock())
    monkeypatch.setattr(admin, "token_manager", manager)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost") as client:
            response = await client.post(ENDPOINT, json={"email": EMAIL})
        assert response.status_code == 401
        manager.prepare_browser_account.assert_not_awaited()
    asyncio.run(check())


@pytest.mark.parametrize("created", [True, False])
def test_bootstrap_launches_for_returned_id_and_returns_only_public_status(monkeypatch, created):
    token = Token(id=42, st="browser-pending-random", email=EMAIL, is_active=False)
    manager = MagicMock(prepare_browser_account=AsyncMock(return_value=(token, created)))
    status = {"token_id": 42, "enabled": True, "status": "opening", "browser_open": False,
              "last_sync_at": None, "error_code": "", "interval_minutes": 30}
    service = MagicMock(start_login=AsyncMock(return_value={**status, "google_cookies": "SECRET", "profile_path": "PRIVATE"}))
    concurrency = MagicMock(reset_token=AsyncMock())
    monkeypatch.setattr(admin, "token_manager", manager)
    monkeypatch.setattr(admin, "concurrency_manager", concurrency)
    monkeypatch.setattr(app.state, "managed_browser", service)
    admin.active_admin_tokens.add("bootstrap-test")
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost", cookies={"admin_session": "bootstrap-test"}) as client:
            response = await client.post(ENDPOINT, json={"email": EMAIL})
        assert response.status_code == 200, response.text
        assert response.json() == {"success": True, "created": created, "session": status}
        assert "no-store" in response.headers["cache-control"]
        manager.prepare_browser_account.assert_awaited_once_with(EMAIL)
        service.start_login.assert_awaited_once_with(42)
        if created:
            concurrency.reset_token.assert_awaited_once_with(42, image_concurrency=-1, video_concurrency=-1)
        else:
            concurrency.reset_token.assert_not_awaited()
    try:
        asyncio.run(check())
    finally:
        admin.active_admin_tokens.discard("bootstrap-test")


@pytest.mark.parametrize("payload", [{"email": "not-email"}, {"email": "<script>@example.com"}, {}, {"email": EMAIL, "google_cookies": "no"}])
def test_bootstrap_rejects_invalid_body_without_creating_or_opening(monkeypatch, payload):
    manager = MagicMock(prepare_browser_account=AsyncMock())
    monkeypatch.setattr(admin, "token_manager", manager)
    admin.active_admin_tokens.add("bootstrap-test")
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost", headers={"Authorization": "Bearer bootstrap-test"}) as client:
            response = await client.post(ENDPOINT, json=payload)
        assert response.status_code == 422
        manager.prepare_browser_account.assert_not_awaited()
    try:
        asyncio.run(check())
    finally:
        admin.active_admin_tokens.discard("bootstrap-test")


def test_bootstrap_rejects_cross_origin_before_creating_account(monkeypatch):
    manager = MagicMock(prepare_browser_account=AsyncMock())
    monkeypatch.setattr(admin, "token_manager", manager)
    admin.active_admin_tokens.add("bootstrap-test")
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost", cookies={"admin_session": "bootstrap-test"}) as client:
            response = await client.post(ENDPOINT, json={"email": EMAIL}, headers={"Origin": "https://unrelated.example"})
        assert response.status_code == 403
        manager.prepare_browser_account.assert_not_awaited()
    try:
        asyncio.run(check())
    finally:
        admin.active_admin_tokens.discard("bootstrap-test")
