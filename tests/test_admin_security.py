"""Admin password handling: hashed storage, forced change of the factory default, constant-time checks."""

import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from starlette.requests import Request

from src.api import admin
from src.core.auth import AuthManager
from src.core.config import config
from src.core.database import Database


def _request(path: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b""})


class AdminPasswordTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(str(Path(self.temp.name) / "flow.db"))
        await self.db.init_db()
        await self.db.init_config_from_toml(None, is_first_startup=True)  # factory row: admin / admin in plain text
        saved = (config._admin_username, config._admin_password, config.api_key, admin.db, AuthManager.default_password_active)
        self.addCleanup(self._restore, saved)
        admin.db = self.db
        admin.active_admin_tokens.clear()
        self.addCleanup(admin.active_admin_tokens.clear)

    @staticmethod
    def _restore(saved):
        config._admin_username, config._admin_password, config.api_key, admin.db, AuthManager.default_password_active = saved

    async def sign_in(self, password="admin"):
        class _Response:
            def set_cookie(self, **kwargs):
                pass

        return await admin.admin_login(admin.LoginRequest(username="admin", password=password), _Response())

    async def test_plain_text_password_is_hashed_on_load_and_still_works(self):
        stored = (await self.db.get_admin_config()).password
        self.assertFalse(AuthManager.is_hashed(stored))
        await self.db.reload_config_to_memory()
        stored = (await self.db.get_admin_config()).password
        self.assertTrue(AuthManager.is_hashed(stored))
        self.assertTrue(AuthManager.verify_admin("admin", "admin"))
        self.assertFalse(AuthManager.verify_admin("admin", "Admin"))
        self.assertFalse(AuthManager.verify_admin("root", "admin"))
        self.assertTrue(AuthManager.default_password_active)

    async def test_default_password_blocks_the_console_until_it_is_changed(self):
        await self.db.reload_config_to_memory()
        result = await self.sign_in()
        self.assertTrue(result["must_change_password"])
        with self.assertRaises(HTTPException) as blocked:
            await admin.verify_admin_token(_request("/api/stats"), f"Bearer {result['token']}")
        self.assertEqual((401, "password_change_required"), (blocked.exception.status_code, blocked.exception.detail))
        # Changing the password, signing out and the security status stay reachable.
        for path in ("/api/admin/change-password", "/api/admin/password", "/api/admin/logout"):
            self.assertEqual(result["token"], await admin.verify_admin_token(_request(path), f"Bearer {result['token']}"))

    async def test_new_password_is_validated_hashed_and_ends_the_restriction(self):
        await self.db.reload_config_to_memory()
        token = (await self.sign_in())["token"]
        for weak in ("short", "admin", "x" * 73):
            with self.assertRaises(HTTPException) as refused:
                await admin.change_password(admin.ChangePasswordRequest(old_password="admin", new_password=weak), token)
            self.assertEqual(400, refused.exception.status_code)
        with self.assertRaises(HTTPException):
            await admin.change_password(admin.ChangePasswordRequest(old_password="wrong", new_password="a-new-secret"), token)
        self.assertTrue(AuthManager.default_password_active)

        await admin.change_password(admin.ChangePasswordRequest(old_password="admin", new_password="a-new-secret"), token)
        self.assertFalse(AuthManager.default_password_active)
        self.assertFalse(admin.active_admin_tokens)  # every session must sign in again
        stored = (await self.db.get_admin_config()).password
        self.assertTrue(AuthManager.is_hashed(stored))
        self.assertNotIn("a-new-secret", stored)
        with self.assertRaises(HTTPException):
            await self.sign_in("admin")
        fresh = await self.sign_in("a-new-secret")
        self.assertFalse(fresh["must_change_password"])
        self.assertEqual(fresh["token"], await admin.verify_admin_token(_request("/api/stats"), f"Bearer {fresh['token']}"))

    async def test_new_password_survives_a_restart(self):
        await self.db.reload_config_to_memory()
        token = (await self.sign_in())["token"]
        await admin.change_password(admin.ChangePasswordRequest(old_password="admin", new_password="a-new-secret"), token)
        # A restart forgets the in-memory value and reloads the database.
        config._admin_password = None
        await self.db.reload_config_to_memory()
        self.assertTrue(AuthManager.verify_admin("admin", "a-new-secret"))
        self.assertFalse(AuthManager.verify_admin("admin", "admin"))
        self.assertFalse(AuthManager.default_password_active)

    async def test_security_status_reports_exposure(self):
        await self.db.reload_config_to_memory()
        status = await admin.security_status("token")
        self.assertTrue(status["default_admin_password"])
        self.assertIn("listening_on_all_interfaces", status)


if __name__ == "__main__":
    unittest.main()
