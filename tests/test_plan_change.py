"""An account that drops to the free plan: the plan chip is read in any language, a collapsed balance
is not booked as spending, and the plan is re-read at once."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.core.account_tiers import (
    PAYGATE_TIER_NOT_PAID, PAYGATE_TIER_ONE, PAYGATE_TIER_TWO, is_balance_collapse, tier_from_chip_text,
)
from src.core.database import Database
from src.core.models import Token
from src.services.credit_ledger import CreditLedger
from src.services.token_manager import TokenManager


class ChipTests(unittest.TestCase):
    def test_the_chip_is_read_in_the_languages_flow_shows(self):
        cases = {
            "Free": PAYGATE_TIER_NOT_PAID, "FREE": PAYGATE_TIER_NOT_PAID, "Miễn phí": PAYGATE_TIER_NOT_PAID,
            "免费": PAYGATE_TIER_NOT_PAID, "Pro": PAYGATE_TIER_ONE, "Google AI Pro": PAYGATE_TIER_ONE,
            "Plus": PAYGATE_TIER_ONE, "Ultra": PAYGATE_TIER_TWO, "  Google AI  Ultra ": PAYGATE_TIER_TWO,
        }
        for text, tier in cases.items():
            self.assertEqual(tier, tier_from_chip_text(text), text)

    def test_unreadable_text_names_no_plan(self):
        for text in (None, "", "   ", "Upgrade", "???"):
            self.assertIsNone(tier_from_chip_text(text), text)


class CollapseTests(unittest.TestCase):
    def test_only_a_huge_sudden_drop_counts(self):
        self.assertTrue(is_balance_collapse(24893, 50))
        self.assertTrue(is_balance_collapse(2000, 200))
        self.assertFalse(is_balance_collapse(2000, 201))   # ordinary spending, even a lot of it
        self.assertFalse(is_balance_collapse(1999, 0))     # a small balance running out
        self.assertFalse(is_balance_collapse(100, 90))
        self.assertFalse(is_balance_collapse(50, 24893))   # a top-up is not a collapse
        self.assertFalse(is_balance_collapse(None, 5))
        self.assertFalse(is_balance_collapse(5000, True))


class LedgerTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_plan_change_is_not_booked_as_a_request_cost(self):
        ledger = CreditLedger(MagicMock(), MagicMock())
        ledger.record = AsyncMock()
        ledger.last_known[5] = 24893
        self.assertEqual(0, ledger.observe(5, 50, client_key_id=0, model="m", kind="image"))
        await asyncio.sleep(0)
        ledger.record.assert_not_awaited()
        self.assertEqual(50, ledger.last_known[5])  # the next request is measured from the new balance
        self.assertEqual(9, ledger.observe(5, 41, client_key_id=0, model="m", kind="image"))

    async def test_real_spending_is_still_booked(self):
        ledger = CreditLedger(MagicMock(), MagicMock())
        ledger.record = AsyncMock()
        ledger.last_known[5] = 25000
        self.assertEqual(100, ledger.observe(5, 24900, client_key_id=3, model="veo", kind="video"))
        await asyncio.sleep(0)
        ledger.record.assert_awaited_once_with(3, "veo", 100)


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(str(Path(self.temp.name) / "flow.db"))
        await self.db.init_db()
        self.token_id = await self.db.add_token(Token(
            st="synthetic-session", email="a@example.test", at="at", credits=24893, user_paygate_tier=PAYGATE_TIER_TWO,
        ))
        self.flow = MagicMock()
        self.manager = TokenManager(self.db, self.flow)
        self.manager.ensure_valid_token = AsyncMock(side_effect=lambda token: token)
        self.manager.alerts = MagicMock(announce=AsyncMock())
        self.manager.managed_browser = MagicMock(
            get_status=AsyncMock(return_value={"enabled": True}), sync=AsyncMock(return_value={"status": "ready"}),
        )

    async def refresh(self, credits):
        self.flow.get_credits = AsyncMock(return_value={"credits": credits, "userPaygateTier": None})
        result = await self.manager.refresh_credits(self.token_id)
        await asyncio.gather(*self.manager._plan_check_tasks.values())
        return result

    async def test_a_collapsed_balance_alerts_and_rereads_the_plan(self):
        self.assertEqual(50, await self.refresh(50))
        self.manager.managed_browser.sync.assert_awaited_once_with(self.token_id)
        self.manager.alerts.announce.assert_awaited_once()
        message = self.manager.alerts.announce.await_args.args[1]
        self.assertIn("24893", message)
        self.assertIn("50", message)
        self.assertEqual(50, (await self.db.get_token(self.token_id)).credits)

    async def test_ordinary_spending_checks_nothing(self):
        await self.refresh(24000)
        self.manager.managed_browser.sync.assert_not_awaited()
        self.manager.alerts.announce.assert_not_awaited()

    async def test_the_plan_is_not_reread_more_than_once_per_cooldown(self):
        await self.refresh(50)
        await self.db.update_token(self.token_id, credits=24893)
        await self.refresh(40)
        self.assertEqual(1, self.manager.managed_browser.sync.await_count)

    async def test_an_account_without_a_managed_browser_is_not_synced(self):
        self.manager.managed_browser.get_status = AsyncMock(return_value={"enabled": False})
        await self.refresh(50)
        self.manager.managed_browser.sync.assert_not_awaited()

    async def test_a_failing_sync_never_breaks_the_refresh(self):
        self.manager.managed_browser.sync = AsyncMock(side_effect=RuntimeError("browser busy"))
        self.assertEqual(50, await self.refresh(50))


if __name__ == "__main__":
    unittest.main()
