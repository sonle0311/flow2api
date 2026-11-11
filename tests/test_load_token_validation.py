"""Concurrent credential validation must share work without sharing stale identity."""

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.core.database import Database
from src.core.models import Token
from src.services.token_manager import TokenManager


def token_snapshot(token_id=1):
    return Token(
        id=token_id, st=f"synthetic-st-{token_id}", at="synthetic-at",
        at_expires=datetime.now(timezone.utc) + timedelta(hours=24),
        email=f"synthetic-{token_id}@example.invalid", login_account=f"synthetic-{token_id}@example.invalid",
        google_cookies="OSID=synthetic; SID=synthetic", auto_refresh_enabled=False,
        credits=1,
    )


class ValidationLoadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(db_path=self.temp.name + "/flow.db")
        await self.db.init_db()
        self.token_id = await self.db.add_token(token_snapshot())
        self.flow = SimpleNamespace(FRONTEND_ACCESS_TOKEN="frontend-marker")
        self.manager = TokenManager(self.db, self.flow)
        self.manager._refresh_at = AsyncMock(return_value=False)

    async def test_25_callers_share_cold_and_expired_cache_validation_and_persistence(self):
        for expired in (False, True):
            with self.subTest(expired=expired):
                if expired:
                    with patch("src.services.token_manager.time.monotonic", return_value=1000000000000):
                        # Start the requests below with the already-expired entry.
                        self.manager._has_recent_at_validation(self.token_id)
                entered, release = asyncio.Event(), asyncio.Event()
                calls = 0

                async def credits(*args):
                    nonlocal calls
                    calls += 1
                    entered.set()
                    await release.wait()
                    return {"credits": 42, "userPaygateTier": "PAYGATE_TIER_TWO"}

                self.manager._get_credits_for_token = credits
                snapshot = await self.db.get_token(self.token_id)
                with patch.object(self.db, "update_token_if_cookie_matches", wraps=self.db.update_token_if_cookie_matches) as guarded, patch.object(
                    self.db, "update_token", wraps=self.db.update_token,
                ) as unconditional:
                    tasks = [asyncio.create_task(self.manager.ensure_valid_token(snapshot)) for _ in range(25)]
                    await asyncio.wait_for(entered.wait(), 2)
                    # A barrier in credits keeps the first validation unfinished
                    # while every same-snapshot caller reaches shared-task lookup.
                    for _ in range(30):
                        await asyncio.sleep(0)
                    release.set()
                    results = await asyncio.gather(*tasks)
                    self.assertEqual(calls, 1)
                    self.assertEqual(guarded.await_count + unconditional.await_count, 1)
                    self.assertTrue(all(result.credits == 42 for result in results))
                await self.manager.ensure_valid_token(await self.db.get_token(self.token_id))
                self.assertEqual(calls, 1)

    async def test_cancelled_waiter_does_not_remove_or_cancel_shared_validation(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def credits(*args):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return {"credits": 30}

        self.manager._get_credits_for_token = credits
        snapshot = await self.db.get_token(self.token_id)
        first = asyncio.create_task(self.manager.ensure_valid_token(snapshot))
        await asyncio.wait_for(entered.wait(), 2)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(self.manager.ensure_valid_token(snapshot))
        await asyncio.sleep(0)
        release.set()
        result = await second
        self.assertEqual(result.credits, 30)
        self.assertEqual(calls, 1)
        self.assertEqual(getattr(self.manager, "_validation_futures", {}), {})

    async def test_different_accounts_validate_independently(self):
        other_id = await self.db.add_token(token_snapshot(2))
        started, release = {self.token_id: asyncio.Event(), other_id: asyncio.Event()}, asyncio.Event()

        async def credits(token, at):
            started[token.id].set()
            if token.id == self.token_id:
                await release.wait()
            return {"credits": token.id * 10}

        self.manager._get_credits_for_token = credits
        first = asyncio.create_task(self.manager.ensure_valid_token(await self.db.get_token(self.token_id)))
        second = asyncio.create_task(self.manager.ensure_valid_token(await self.db.get_token(other_id)))
        try:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), 2)
            self.assertEqual((await asyncio.wait_for(second, 2)).credits, other_id * 10)
            self.assertFalse(first.done())
        finally:
            release.set()
            await asyncio.gather(first, second)

    async def test_changed_credentials_use_new_validation_and_discard_old_result(self):
        changes = (
            {"at": "replacement-at"},
            {"google_cookies": "OSID=replacement; SID=replacement"},
            {"email": "replacement@example.invalid", "login_account": "replacement@example.invalid"},
        )
        for change in changes:
            with self.subTest(change=next(iter(change))):
                self.manager._clear_at_validation_cache(self.token_id)
                entered, release = asyncio.Event(), asyncio.Event()
                calls = []
                old = await self.db.get_token(self.token_id)

                async def credits(token, at):
                    calls.append((token.at, token.google_cookies, token.email))
                    if len(calls) == 1:
                        entered.set()
                        await release.wait()
                        return {"credits": 999, "userPaygateTier": "PAYGATE_TIER_TWO"}
                    return {"credits": 7, "userPaygateTier": "PAYGATE_TIER_ONE"}

                self.manager._get_credits_for_token = credits
                first = asyncio.create_task(self.manager.ensure_valid_token(old))
                await asyncio.wait_for(entered.wait(), 2)
                await self.db.update_token(self.token_id, **change)
                new = await self.db.get_token(self.token_id)
                try:
                    fresh = await asyncio.wait_for(self.manager.ensure_valid_token(new), 2)
                    self.assertEqual(fresh.credits, 7)
                finally:
                    release.set()
                    old_result = await first
                current = await self.db.get_token(self.token_id)
                self.assertEqual(current.credits, 7)
                self.assertEqual(current.user_paygate_tier, "PAYGATE_TIER_ONE")
                self.assertEqual(old_result.at, current.at)
                self.assertEqual(old_result.google_cookies, current.google_cookies)
                self.assertEqual(old_result.email, current.email)
                self.assertEqual(len(calls), 2)
                await self.manager.ensure_valid_token(new)
                self.assertEqual(len(calls), 2)

    async def test_warm_cache_is_bound_to_at_cookie_and_identity_snapshot(self):
        self.manager._get_credits_for_token = AsyncMock(return_value={"credits": 10})
        await self.manager.ensure_valid_token(await self.db.get_token(self.token_id))
        for field, value in (
            ("at", "changed-at"), ("google_cookies", "OSID=changed; SID=changed"),
            ("email", "changed@example.invalid"), ("login_account", "changed@example.invalid"),
        ):
            with self.subTest(field=field):
                before = self.manager._get_credits_for_token.await_count
                stale = await self.db.get_token(self.token_id)
                await self.db.update_token(self.token_id, **{field: value})
                result = await self.manager.ensure_valid_token(stale)
                self.assertEqual(getattr(result, field), value)
                self.assertEqual(self.manager._get_credits_for_token.await_count, before + 1)

    async def test_all_cancelled_waiters_leave_task_owned_until_completion(self):
        entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def credits(*args):
            entered.set()
            await release.wait()
            return {"credits": 31}

        self.manager._get_credits_for_token = credits
        snapshot = await self.db.get_token(self.token_id)
        first = asyncio.create_task(self.manager.ensure_valid_token(snapshot))
        await asyncio.wait_for(entered.wait(), 2)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertEqual(len(self.manager._validation_futures), 1)
        task = next(iter(self.manager._validation_futures.values()))
        task.add_done_callback(lambda _: finished.set())
        release.set()
        await asyncio.wait_for(finished.wait(), 2)
        self.assertEqual(self.manager._validation_futures, {})
        self.assertEqual((await self.db.get_token(self.token_id)).credits, 31)

    async def test_atomic_validation_save_rejects_changed_at_even_with_same_cookie(self):
        snapshot = await self.db.get_token(self.token_id)
        await self.db.update_token(self.token_id, at="replacement-at")
        saved = await self.db.update_token_if_cookie_matches(
            self.token_id, snapshot.google_cookies, expected_at=snapshot.at,
            expected_identity=(snapshot.email, snapshot.login_account), credits=999,
        )
        self.assertFalse(saved)
        self.assertEqual((await self.db.get_token(self.token_id)).credits, 1)

    async def test_rejected_save_with_reverted_credentials_cannot_join_its_own_task(self):
        snapshot = await self.db.get_token(self.token_id)
        self.manager._get_credits_for_token = AsyncMock(return_value={"credits": 999})
        original_save = self.db.update_token_if_cookie_matches

        async def save_after_credential_push(*args, **kwargs):
            await self.db.update_token(self.token_id, at="temporary-at")
            saved = await original_save(*args, **kwargs)
            await self.db.update_token(self.token_id, at=snapshot.at)
            return saved

        with patch.object(self.db, "update_token_if_cookie_matches", side_effect=save_after_credential_push):
            result = await asyncio.wait_for(self.manager.ensure_valid_token(snapshot), 2)
        self.assertIsNone(result)
        self.assertEqual(self.manager._validation_futures, {})
        self.assertEqual((await self.db.get_token(self.token_id)).credits, 1)
