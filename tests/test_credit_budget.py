"""Credits measured from the account balance, charged to client keys, and monthly budgets."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI

from src.api import admin, routes
from src.core import auth
from src.core.database import Database
from src.services.client_keys import ClientKeyService, ClientLimitExceeded
from src.services.credit_ledger import CreditLedger
from src.services.flow_client import FlowClient

PROJECT = "11111111-1111-4111-8111-111111111111"
MEDIA = "22222222-2222-4222-8222-222222222222"
OPERATION = "33333333-3333-4333-8333-333333333333"


class LedgerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(str(Path(self.temp.name) / "flow.db"))
        await self.db.init_db()
        self.keys = ClientKeyService(self.db)
        await self.keys.initialize()
        self.balance = 12036
        self.token_manager = SimpleNamespace(refresh_credits=AsyncMock(side_effect=lambda *a, **k: self.balance))
        self.ledger = CreditLedger(self.db, self.token_manager, self.keys)
        self.token = SimpleNamespace(id=4, credits=12000)
        info, _ = await self.keys.create("acme", 0, 0, [], 100)
        self.key_id = info["id"]

    async def settle(self):
        await asyncio.gather(*list(self.ledger._tasks))

    async def test_each_submission_is_charged_the_drop_in_the_balance_even_when_they_overlap(self):
        await self.ledger.ensure_baseline(self.token)
        self.assertEqual(12036, self.ledger.last_known[4])  # read fresh, not the stored 12000
        # Two videos submitted back to back; Flow answers with the balance after each deduction.
        first = self.ledger.observe(4, 12024, client_key_id=self.key_id, model="omni-1.2-flash-extend-4s-landscape", kind="video")
        second = self.ledger.observe(4, 12003, client_key_id=0, model="omni-1.2-flash-8s-landscape", kind="video")
        await self.settle()
        self.assertEqual((12, 21), (first, second))
        report = await self.ledger.report(7)
        self.assertEqual(33, report["total_credits"])
        by_key = {row["client_key_id"]: row for row in report["by_key"]}
        self.assertEqual((12, "acme"), (by_key[self.key_id]["credits"], by_key[self.key_id]["name"]))
        self.assertEqual((21, "master key"), (by_key[0]["credits"], by_key[0]["name"]))
        self.assertEqual({"omni-1.2-flash-extend-4s-landscape": 12, "omni-1.2-flash-8s-landscape": 21},
                         {row["model"]: row["credits"] for row in report["by_model"]})
        self.assertEqual(12, self.keys.get(self.key_id).credits_used)

    async def test_unknown_baseline_refund_and_garbage_are_never_charged(self):
        # Nothing known about the account yet: the first answer only sets the baseline.
        self.assertEqual(0, self.ledger.observe(9, 500, client_key_id=0, model="m", kind="video"))
        self.assertEqual(0, self.ledger.observe(9, 900, client_key_id=0, model="m", kind="video"))  # top-up or refund
        for junk in (None, "12", -1, True, 4.5):
            self.assertEqual(0, self.ledger.observe(9, junk, client_key_id=0, model="m", kind="video"))
        self.assertEqual(900, self.ledger.last_known[9])
        await self.settle()
        self.assertEqual(0, (await self.ledger.report(7))["total_credits"])

    async def test_baseline_falls_back_to_the_stored_balance_when_the_refresh_fails(self):
        self.token_manager.refresh_credits = AsyncMock(side_effect=RuntimeError("no network"))
        await self.ledger.ensure_baseline(self.token)
        self.assertEqual(12000, self.ledger.last_known[4])

    async def test_images_are_charged_after_they_finish(self):
        await self.ledger.ensure_baseline(self.token)
        self.balance = 12036 - 4
        await self.ledger.observe_after_completion(self.token, client_key_id=self.key_id, model="gemini-3.1-flash-image-landscape", kind="image")
        await self.settle()
        self.assertEqual(4, (await self.ledger.report(7))["total_credits"])

    async def test_submit_response_exposes_the_balance_it_states(self):
        payload = [None, 12003, [[OPERATION, PROJECT, MEDIA, None, None, [[1, 0], "x"]]]]
        result = FlowClient._normalize_frontend_video_submission(
            payload, project_id=PROJECT, aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE", model_key="k",
        )
        self.assertEqual(12003, result["creditsRemaining"])
        without = FlowClient._normalize_frontend_video_submission(
            [None, None, [[OPERATION, PROJECT, MEDIA, None, None, [[1, 0], "x"]]]], project_id=PROJECT,
            aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE", model_key="k",
        )
        self.assertIsNone(without["creditsRemaining"])


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(str(Path(self.temp.name) / "flow.db"))
        await self.db.init_db()
        self.service = ClientKeyService(self.db)
        await self.service.initialize()
        info, self.secret = await self.service.create("acme", 0, 0, [], 30)
        self.key = self.service.get(info["id"])

    async def test_budget_blocks_admission_until_reset_or_the_next_month(self):
        self.service.admit(self.key).release()
        await self.service.add_spend(self.key.id, 29)
        self.service.admit(self.key).release()  # 29 < 30: still allowed (the budget is a soft limit)
        await self.service.add_spend(self.key.id, 1)
        with self.assertRaises(ClientLimitExceeded) as blocked:
            self.service.admit(self.key)
        error = blocked.exception
        self.assertEqual(("credit_budget_exceeded", 30), (error.code, error.limit))
        self.assertTrue(1 <= error.retry_after <= 32 * 24 * 3600)
        description = self.service.describe(self.key)
        self.assertEqual((30, 30, 0), (description["credit_budget"], description["credits_used"], description["credits_remaining"]))

        await self.service.update(self.key.id, reset_credits_used=True)
        self.service.admit(self.key).release()
        await self.service.add_spend(self.key.id, 30)
        self.key.budget_month = "2000-01"  # the month has changed since the spending
        self.service.admit(self.key).release()
        self.assertEqual(0, self.key.credits_used)

    async def test_budget_zero_means_unlimited_and_usage_survives_a_restart(self):
        await self.service.update(self.key.id, credit_budget=0)
        await self.service.add_spend(self.key.id, 10_000)
        self.service.admit(self.key).release()
        await self.service.update(self.key.id, credit_budget=50_000)
        reloaded = ClientKeyService(self.db)
        await reloaded.initialize()
        record = reloaded.get(self.key.id)
        self.assertEqual((50_000, 10_000), (record.credit_budget, record.credits_used))
        with self.assertRaises(ValueError):
            await self.service.update(self.key.id, credit_budget=-1)

    async def test_exhausted_budget_answers_http_429_with_retry_after(self):
        await self.service.add_spend(self.key.id, 30)
        previous_key_service, previous_handler = auth.get_client_key_service(), routes.generation_handler
        auth.set_client_key_service(self.service)
        routes.set_generation_handler(SimpleNamespace(
            handle_generation=lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not generate")),
            admission_preflight=AsyncMock(return_value=None),
        ))
        self.addCleanup(auth.set_client_key_service, previous_key_service)
        self.addCleanup(routes.set_generation_handler, previous_handler)
        app = FastAPI()
        app.include_router(routes.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/chat/completions",
                json={"model": "gemini-3.1-flash-image-landscape", "messages": [{"role": "user", "content": "x"}]},
                headers={"Authorization": f"Bearer {self.secret}"},
            )
        self.assertEqual(429, response.status_code)
        body = response.json()["error"]
        self.assertEqual(("rate_limit_error", "credit_budget_exceeded"), (body["type"], body["code"]))
        self.assertEqual(str(body["retry_after"]), response.headers["retry-after"])


if __name__ == "__main__":
    unittest.main()
