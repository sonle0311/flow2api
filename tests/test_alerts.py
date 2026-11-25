"""Operator alerts: edge-triggered conditions, cooldown reminders, recovery, webhook handling."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.core.database import Database
from src.services.alerts import AlertService


def token(token_id, active=True, credits=5000):
    return SimpleNamespace(id=token_id, email=f"user{token_id}@example.com", is_active=active, credits=credits)


class AlertTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(str(Path(self.temp.name) / "flow.db"))
        await self.db.init_db()
        async with self.db._connect(write=True) as conn:
            await conn.execute("""CREATE TABLE IF NOT EXISTS managed_browser_sessions (
                token_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'not_configured')""")
            await conn.commit()
        self.tokens = [token(2, active=False), token(3, active=False), token(4)]
        self.now = 1_000_000.0
        self.sent = []
        self.fail_delivery = False

        async def sender(url, body):
            if self.fail_delivery:
                raise OSError("connection refused")
            self.sent.append((url, body))

        async def tokens():
            return self.tokens

        self.alerts = AlertService(self.db, tokens, clock=lambda: self.now, sender=sender)
        await self.alerts.load()
        await self.alerts.update_settings(webhook_url="https://hooks.example.com/secret-path", enabled=True, cooldown_minutes=60)

    async def set_session(self, token_id, status, enabled=1):
        async with self.db._connect(write=True) as conn:
            await conn.execute("INSERT OR REPLACE INTO managed_browser_sessions (token_id, enabled, status) VALUES (?, ?, ?)", (token_id, enabled, status))
            await conn.commit()

    def kinds(self):
        return [(body["event"], body["kind"]) for _, body in self.sent]

    async def test_a_problem_is_announced_once_reminded_after_the_cooldown_and_reported_recovered(self):
        await self.alerts.check_accounts()
        await self.alerts.check_accounts()
        self.assertEqual([("single_usable_account", "raised")], self.kinds())
        body = self.sent[0][1]
        self.assertEqual(body["text"], body["content"])  # chat webhooks read either field
        self.assertIn("user4@example.com", body["message"])
        self.now += 61 * 60
        await self.alerts.check_accounts()
        self.assertEqual(("single_usable_account", "reminder"), self.kinds()[-1])
        self.tokens[0].is_active = True  # a second account is back
        await self.alerts.check_accounts()
        self.assertEqual(("single_usable_account", "recovered"), self.kinds()[-1])
        self.assertEqual({}, self.alerts.conditions)
        count = len(self.sent)
        await self.alerts.check_accounts()
        self.assertEqual(count, len(self.sent))

    async def test_no_usable_account_is_critical_and_replaces_the_single_account_warning(self):
        await self.alerts.check_accounts()
        self.tokens[2].is_active = False
        await self.alerts.check_accounts()
        self.assertEqual({"no_usable_account"}, set(self.alerts.conditions))
        self.assertEqual("critical", self.alerts.conditions["no_usable_account"]["severity"])
        self.assertIn(("single_usable_account", "recovered"), self.kinds())

    async def test_signed_out_browser_sessions_and_low_credit_accounts_are_reported_per_account(self):
        self.tokens = [token(2), token(3, credits=120), token(4)]
        await self.set_session(2, "needs_login")
        await self.set_session(4, "ready")
        await self.set_session(3, "needs_login", enabled=0)  # stopped on purpose: not a problem
        await self.alerts.check_accounts()
        self.assertEqual({"account_needs_login:2", "credits_low:3"}, set(self.alerts.conditions))
        await self.alerts.update_settings(low_credits=0)  # 0 switches the credit alert off
        await self.alerts.check_accounts()
        self.assertEqual({"account_needs_login:2"}, set(self.alerts.conditions))
        await self.set_session(2, "ready")
        await self.alerts.check_accounts()
        self.assertEqual({}, self.alerts.conditions)

    async def test_conditions_from_other_services_are_not_cleared_by_the_account_check(self):
        await self.alerts.raise_condition("captcha_failing:4", "captcha broke", severity="warning")
        await self.alerts.check_accounts()
        self.assertIn("captcha_failing:4", self.alerts.conditions)

    async def test_an_active_account_that_needs_to_sign_in_again_does_not_count_as_usable(self):
        self.tokens = [token(2), token(3), token(4)]  # all flagged active, like a real deployment with lapsed sessions
        await self.set_session(2, "needs_login")
        await self.set_session(3, "needs_login")
        await self.set_session(4, "ready")
        await self.alerts.check_accounts()
        self.assertEqual({"single_usable_account", "account_needs_login:2", "account_needs_login:3"}, set(self.alerts.conditions))
        self.assertIn("user4@example.com", self.alerts.conditions["single_usable_account"]["message"])
        await self.set_session(4, "needs_login")
        await self.alerts.check_accounts()
        self.assertIn("no_usable_account", self.alerts.conditions)

    async def test_a_broken_webhook_is_recorded_and_never_raises(self):
        self.fail_delivery = True
        await self.alerts.check_accounts()
        entry = self.alerts.status()["history"][0]
        self.assertFalse(entry["delivered"])
        self.assertIn("connection refused", entry["error"])
        self.assertIn("single_usable_account", self.alerts.conditions)  # still tracked and shown

    async def test_without_a_webhook_conditions_are_tracked_but_nothing_is_sent(self):
        await self.alerts.update_settings(enabled=False)
        await self.alerts.check_accounts()
        self.assertEqual([], self.sent)
        self.assertIn("single_usable_account", self.alerts.conditions)
        self.assertIsNone(self.alerts.status()["history"][0]["delivered"])

    async def test_settings_are_validated_persisted_and_never_echo_the_webhook_secret(self):
        for bad in ({"webhook_url": "ftp://example.com/x"}, {"webhook_url": "not a url"}, {"low_credits": -1}, {"cooldown_minutes": 0}):
            with self.assertRaises(ValueError):
                await self.alerts.update_settings(**bad)
        await self.alerts.update_settings(webhook_url="")
        with self.assertRaises(ValueError):  # enabling needs somewhere to send to
            await self.alerts.update_settings(enabled=True)
        await self.alerts.update_settings(webhook_url="https://hooks.example.com/secret-path", enabled=True)
        description = self.alerts.describe_settings()
        self.assertEqual("hooks.example.com", description["webhook_host"])
        self.assertNotIn("secret-path", str(description))
        reloaded = AlertService(self.db, lambda: None)
        await reloaded.load()
        self.assertEqual(("https://hooks.example.com/secret-path", True, 60), (reloaded.webhook_url, reloaded.enabled, reloaded.cooldown_minutes))

    async def test_test_message_needs_a_webhook(self):
        await self.alerts.send_test()
        self.assertEqual("test", self.sent[-1][1]["event"])
        await self.alerts.update_settings(enabled=False, webhook_url="")
        with self.assertRaises(ValueError):
            await self.alerts.send_test()


if __name__ == "__main__":
    unittest.main()
