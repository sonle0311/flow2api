"""Deterministic ownership/refill regressions; no browser or provider is started."""

import asyncio
import time
import types
import unittest
from unittest.mock import AsyncMock, patch

from src.services import browser_captcha_personal as personal


async def _schedule_pending_tasks():
    # Yield to runnable tasks only; no wall-clock timer or provider is involved.
    for _ in range(8):
        await asyncio.sleep(0)


class BrowserResidentOwnershipTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = personal.BrowserCaptchaService()
        self.service._max_resident_tabs = 1
        self.service._wait_for_resident_slot_available = AsyncMock(return_value=False)
        self.service._dispose_browser_context_quietly = AsyncMock()
        self.service._close_tab_quietly = AsyncMock(
            side_effect=lambda tab: setattr(tab, "closed", True)
        )
        self.service._create_resident_tab = AsyncMock(side_effect=self._create)
        self.resident = self._create("slot-A", "project-A", token_id=1)
        self.service._resident_tabs[self.resident.slot_id] = self.resident
        self.service._remember_token_affinity(1, self.resident.slot_id, self.resident)

    @staticmethod
    def _create(slot_id, project_id=None, token_id=None):
        return personal.ResidentTabInfo(
            types.SimpleNamespace(closed=False), slot_id, project_id,
            token_id=token_id, browser_context_id=f"context-{slot_id}",
        )

    async def asyncTearDown(self):
        tasks = list(self.service._resident_rebuild_tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def reserve(self):
        self.assertTrue(self.service._reserve_resident_slot_for_solve_locked(
            self.resident.slot_id, self.resident
        ))

    async def test_full_pool_keeps_pending_owner_even_before_solve_lock(self):
        self.reserve()
        result = await self.service._ensure_resident_tab(
            "project-B", token_id=2, reserve_for_solve=True, return_slot_key=True
        )
        self.assertEqual(result, (None, None))
        self.assertFalse(self.resident.tab.closed)
        self.assertEqual(self.resident.pending_assignment_count, 1)
        self.service._dispose_browser_context_quietly.assert_not_awaited()
        self.service._create_resident_tab.assert_not_awaited()

    async def test_lru_cannot_close_a_reservation_added_after_candidate_selection(self):
        close = self.service._close_resident_tab

        async def reserve_before_close(*args, **kwargs):
            self.reserve()
            return await close(*args, **kwargs)

        self.service._close_resident_tab = reserve_before_close
        self.assertFalse(await self.service._evict_lru_tab_if_needed())
        self.assertFalse(self.resident.tab.closed)
        self.assertIs(self.service._resident_tabs[self.resident.slot_id], self.resident)

    async def test_full_pool_does_not_evict_active_solve(self):
        async with self.resident.solve_lock:
            self.assertFalse(await self.service._evict_lru_tab_if_needed())
            self.assertFalse(self.resident.tab.closed)

    async def test_detached_eviction_candidate_cannot_gain_a_stale_reservation(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def dispose(*args):
            entered.set()
            await release.wait()

        self.service._dispose_browser_context_quietly.side_effect = dispose
        task = asyncio.create_task(self.service._evict_lru_tab_if_needed())
        await entered.wait()
        try:
            self.assertFalse(self.service._reserve_resident_slot_for_solve_locked(
                self.resident.slot_id, self.resident
            ))
        finally:
            release.set()
            await task

    async def test_lru_replaces_an_idle_account_at_capacity(self):
        slot_id, replacement = await self.service._ensure_resident_tab(
            "project-B", token_id=2, reserve_for_solve=True, return_slot_key=True
        )
        self.assertTrue(self.resident.tab.closed)
        self.assertEqual(len(self.service._resident_tabs), 1)
        self.assertIs(self.service._resident_tabs[slot_id], replacement)
        self.assertEqual(replacement.token_id, 2)
        self.assertEqual(replacement.pending_assignment_count, 1)

    async def test_cancelling_full_pool_waiter_keeps_existing_reservation(self):
        self.reserve()
        waiting = asyncio.Event()

        async def wait(*args, **kwargs):
            waiting.set()
            await asyncio.Event().wait()

        self.service._wait_for_resident_slot_available = wait
        task = asyncio.create_task(self.service._ensure_resident_tab(
            "project-A", token_id=1, reserve_for_solve=True
        ))
        await waiting.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.resident.pending_assignment_count, 1)
        self.assertFalse(self.resident.tab.closed)
        await self.service._release_resident_slot_reservation(self.resident.slot_id)
        self.assertEqual(self.resident.pending_assignment_count, 0)

    async def test_cancelled_post_solve_owner_cannot_release_the_next_reservation(self):
        post_solve = asyncio.Event()
        self.service.initialize = AsyncMock()
        self.service._wait_for_pending_fresh_profile_restart_before_solve = AsyncMock()
        self.service._ensure_resident_token_binding = AsyncMock(return_value=True)
        self.service._personal_solve_mode = lambda *args: "direct"
        self.service._execute_recaptcha_on_tab = AsyncMock(
            return_value={"token": "synthetic-solved"}
        )
        self.service._finalize_resident_solve_locked = AsyncMock(return_value=1)

        async def pause_after_solve(*args, **kwargs):
            post_solve.set()
            await asyncio.Event().wait()

        self.service._maybe_execute_pending_fresh_profile_restart = pause_after_solve
        owner = asyncio.create_task(self.service._get_token_direct(
            "project-A", token_id=1
        ))
        try:
            await post_solve.wait()
            self.assertFalse(self.resident.solve_lock.locked())
            self.assertEqual(self.resident.pending_assignment_count, 0)
            self.reserve()  # B owns the same slot while A is post-processing.
            owner.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await owner
            self.assertEqual(self.resident.pending_assignment_count, 1)
            self.assertFalse(self.resident.pending_assignments_released.is_set())
            self.assertFalse(await self.service._evict_lru_tab_if_needed())
            self.assertFalse(self.resident.tab.closed)
        finally:
            owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)
            await self.service._release_resident_slot_reservation(
                self.resident.slot_id, self.resident
            )

    async def test_cancelling_actual_request_before_solve_lock_releases_its_reservation(self):
        binding = asyncio.Event()
        continue_binding = asyncio.Event()
        self.service.initialize = AsyncMock()
        self.service._wait_for_pending_fresh_profile_restart_before_solve = AsyncMock()

        async def bind(*args, **kwargs):
            binding.set()
            await continue_binding.wait()
            return True

        self.service._ensure_resident_token_binding = bind
        self.service._personal_solve_mode = lambda *args: "direct"
        request = asyncio.create_task(self.service._get_token_direct(
            "project-A", token_id=1
        ))
        await binding.wait()
        self.assertEqual(self.resident.pending_assignment_count, 1)
        await self.resident.solve_lock.acquire()
        try:
            continue_binding.set()
            await _schedule_pending_tasks()
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await request
            self.assertEqual(self.resident.pending_assignment_count, 0)
            self.assertTrue(self.resident.pending_assignments_released.is_set())
        finally:
            self.resident.solve_lock.release()
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)

    async def test_repeated_cancel_drains_reservation_release_blocked_on_resident_lock(self):
        binding = asyncio.Event()
        self.service.initialize = AsyncMock()
        self.service._wait_for_pending_fresh_profile_restart_before_solve = AsyncMock()

        async def bind(*args, **kwargs):
            binding.set()
            await asyncio.Event().wait()

        self.service._ensure_resident_token_binding = bind
        request = asyncio.create_task(self.service._get_token_direct(
            "project-A", token_id=1
        ))
        await binding.wait()
        await self.service._resident_lock.acquire()
        try:
            request.cancel()
            await _schedule_pending_tasks()
            self.assertFalse(request.done())
            request.cancel()
            await _schedule_pending_tasks()
            self.assertFalse(request.done())
            self.assertEqual(self.resident.pending_assignment_count, 1)
        finally:
            self.service._resident_lock.release()
            await asyncio.gather(request, return_exceptions=True)
        self.assertTrue(request.cancelled())
        self.assertEqual(self.resident.pending_assignment_count, 0)
        self.assertTrue(self.resident.pending_assignments_released.is_set())
        _, rebuilt = await self.start_rebuild()
        self.assertIsNotNone(rebuilt)
        self.assertTrue(self.resident.tab.closed)

    async def test_cancel_cleanup_releases_original_resident_after_slot_replacement(self):
        binding = asyncio.Event()
        self.service.initialize = AsyncMock()
        self.service._wait_for_pending_fresh_profile_restart_before_solve = AsyncMock()

        async def bind(*args, **kwargs):
            binding.set()
            await asyncio.Event().wait()

        self.service._ensure_resident_token_binding = bind
        request = asyncio.create_task(self.service._get_token_direct(
            "project-A", token_id=1
        ))
        await binding.wait()
        await self.service._resident_lock.acquire()
        try:
            request.cancel()
            await _schedule_pending_tasks()
            replacement = self._create(self.resident.slot_id, "project-B", token_id=2)
            self.service._resident_tabs[self.resident.slot_id] = replacement
            self.assertTrue(self.service._reserve_resident_slot_for_solve_locked(
                replacement.slot_id, replacement
            ))
        finally:
            self.service._resident_lock.release()
            await asyncio.gather(request, return_exceptions=True)
        self.assertTrue(request.cancelled())
        self.assertEqual(self.resident.pending_assignment_count, 0)
        self.assertTrue(self.resident.pending_assignments_released.is_set())
        self.assertEqual(replacement.pending_assignment_count, 1)
        self.assertFalse(replacement.pending_assignments_released.is_set())

    def start_rebuild(self):
        return asyncio.create_task(self.service._rebuild_resident_tab(
            "project-A", token_id=1, slot_id=self.resident.slot_id,
            return_slot_key=True,
        ))

    async def test_rebuild_waits_before_disposing_an_active_solve_context(self):
        await self.resident.solve_lock.acquire()
        task = self.start_rebuild()
        try:
            await _schedule_pending_tasks()
            self.service._dispose_browser_context_quietly.assert_not_awaited()
            self.assertFalse(self.resident.tab.closed)
            self.assertFalse(task.done())
        finally:
            self.resident.solve_lock.release()
            await task
        self.service._dispose_browser_context_quietly.assert_awaited_once_with(
            self.resident.browser_context_id
        )

    async def test_rebuild_waits_for_pending_owner_to_enter_and_leave_solve(self):
        self.reserve()
        task = self.start_rebuild()
        try:
            await _schedule_pending_tasks()
            self.service._dispose_browser_context_quietly.assert_not_awaited()
            self.assertIn(self.resident.slot_id, self.service._resident_unavailable_slots)
            # Retirement must leave the pending owner's release path reachable.
            self.assertIs(self.service._resident_tabs[self.resident.slot_id], self.resident)
            async with self.resident.solve_lock:
                await self.service._consume_resident_slot_reservation(self.resident.slot_id)
                self.assertEqual(self.resident.pending_assignment_count, 0)
                self.assertFalse(self.service._reserve_resident_slot_for_solve_locked(
                    self.resident.slot_id, self.resident
                ))
                await _schedule_pending_tasks()
                self.service._dispose_browser_context_quietly.assert_not_awaited()
        finally:
            await self.service._release_resident_slot_reservation(
                self.resident.slot_id, self.resident
            )
            await task
        self.assertTrue(self.resident.tab.closed)

    async def test_cancelled_pending_owner_can_release_a_retired_slot(self):
        self.reserve()
        task = self.start_rebuild()
        await _schedule_pending_tasks()
        self.service._dispose_browser_context_quietly.assert_not_awaited()
        await self.service._release_resident_slot_reservation(self.resident.slot_id)
        await task
        self.assertEqual(self.resident.pending_assignment_count, 0)
        self.assertTrue(self.resident.tab.closed)

    async def test_storage_recovery_cannot_reopen_a_slot_retired_for_rebuild(self):
        await self.resident.solve_lock.acquire()
        task = self.start_rebuild()
        await _schedule_pending_tasks()
        # A concurrent storage-recovery callback can clear the unavailable flag.
        self.service._clear_resident_slot_unavailable_locked(self.resident.slot_id)
        self.resident.solve_lock.release()
        try:
            self.assertFalse(self.service._reserve_resident_slot_for_solve_locked(
                self.resident.slot_id, self.resident
            ))
        finally:
            await self.service._release_resident_slot_reservation(self.resident.slot_id)
            await task

    async def test_cancelled_rebuild_waiters_reuse_the_registered_task(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def create(*args, **kwargs):
            entered.set()
            await release.wait()
            return self._create(*args, **kwargs)

        self.service._create_resident_tab.side_effect = create
        first = self.start_rebuild()
        await entered.wait()
        inner = self.service._resident_rebuild_tasks[self.resident.slot_id]
        try:
            for waiter in [first, self.start_rebuild(), self.start_rebuild()]:
                await _schedule_pending_tasks()
                waiter.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await waiter
                self.assertIs(self.service._resident_rebuild_tasks.get(self.resident.slot_id), inner)
                self.assertFalse(inner.done())
            last = self.start_rebuild()
            await _schedule_pending_tasks()
        finally:
            release.set()
            await inner
        slot_id, rebuilt = await last
        self.assertEqual(slot_id, self.resident.slot_id)
        self.assertIs(self.service._resident_tabs[slot_id], rebuilt)
        self.assertEqual(self.service._create_resident_tab.await_count, 1)
        self.assertNotIn(slot_id, self.service._resident_rebuild_tasks)

    async def test_shutdown_can_cancel_rebuild_after_its_waiter_was_cancelled(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def create(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        self.service._create_resident_tab.side_effect = create
        waiter = self.start_rebuild()
        await entered.wait()
        inner = self.service._resident_rebuild_tasks[self.resident.slot_id]
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        try:
            await self.service._cancel_background_runtime_tasks(reason="test-shutdown")
            self.assertTrue(cancelled.is_set())
            self.assertTrue(inner.cancelled())
            self.assertFalse(self.service._resident_rebuild_tasks)
        finally:
            inner.cancel()
            await asyncio.gather(inner, return_exceptions=True)

    async def test_rebuild_exception_clears_registry_at_actual_completion(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def create(*args, **kwargs):
            entered.set()
            await release.wait()
            raise RuntimeError("synthetic rebuild failure")

        self.service._create_resident_tab.side_effect = create
        first = self.start_rebuild()
        await entered.wait()
        second = self.start_rebuild()
        await _schedule_pending_tasks()
        release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        self.assertTrue(all(isinstance(result, RuntimeError) for result in results))
        self.assertEqual(self.service._create_resident_tab.await_count, 1)
        self.assertFalse(self.service._resident_rebuild_tasks)


class BrowserRefillBackoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pool = personal._PersonalBrowserPoolService()
        self.now = 100.0
        self.clock_patch = patch.object(personal, "time", types.SimpleNamespace(
            time=time.time, monotonic=lambda: self.now
        ))
        self.clock_patch.start()
        self.enabled = True
        self.target = 1
        self.pool._is_token_pool_enabled = lambda: self.enabled
        self.pool._get_token_pool_bucket_target_size = lambda **kwargs: self.target
        self.pool._get_token_pool_refill_parallelism = lambda: 1
        self.pool._register_configured_token_pool_buckets_locked = lambda **kwargs: None
        self.pool._ensure_token_pool_maintainer = AsyncMock()
        self.pool._get_token_pool_wait_timeout_seconds = lambda: 60.0
        self.pool._get_token_bundle_direct = AsyncMock(return_value=None)
        self.bucket = "IMAGE_GENERATION"
        self.pool._register_token_pool_bucket_locked(
            bucket_key=self.bucket, project_id="project", action=self.bucket,
            token_id=1, now_value=time.time(),
        )
        self.pool._token_pool_waiters[self.bucket] = 1

    async def asyncTearDown(self):
        await self.pool.close()
        self.clock_patch.stop()

    async def test_immediate_failed_refills_wait_for_clock_advance(self):
        await self.pool._maintain_token_pool_once()
        await _schedule_pending_tasks()
        self.assertEqual(self.pool._get_token_bundle_direct.await_count, 1)
        self.assertFalse(self.pool._token_pool_refill_inflight)
        for _ in range(10):
            await self.pool._maintain_token_pool_once()
        await _schedule_pending_tasks()
        self.assertEqual(self.pool._get_token_bundle_direct.await_count, 1)
        self.now += 1.0
        await self.pool._maintain_token_pool_once()
        await _schedule_pending_tasks()
        self.assertEqual(self.pool._get_token_bundle_direct.await_count, 2)

    async def test_configured_prefill_failure_without_waiters_also_obeys_backoff(self):
        self.pool._token_pool_waiters.clear()

        def register(*, now_value):
            self.pool._register_token_pool_bucket_locked(
                bucket_key=self.bucket, project_id="project", action=self.bucket,
                token_id=1, now_value=now_value,
            )

        self.pool._register_configured_token_pool_buckets_locked = register
        await self.pool._maintain_token_pool_once()
        await _schedule_pending_tasks()
        self.assertEqual(self.pool._get_token_bundle_direct.await_count, 1)
        self.now += 1.0
        await self.pool._maintain_token_pool_once()
        await _schedule_pending_tasks()
        self.assertEqual(self.pool._get_token_bundle_direct.await_count, 2)

    async def test_successful_retry_releases_backoff_and_restores_replenishment(self):
        await self.pool._maintain_token_pool_once()
        await _schedule_pending_tasks()
        self.pool._get_token_bundle_direct.return_value = {"token": "recovered"}
        self.now += 1.0
        await self.pool._maintain_token_pool_once()
        await _schedule_pending_tasks()
        lease = self.pool._pop_ready_token_pool_lease_locked(
            self.bucket, now_value=time.time()
        )
        self.assertEqual(lease.token, "recovered")
        await self.pool._maintain_token_pool_once()
        await _schedule_pending_tasks()
        self.assertEqual(self.pool._get_token_bundle_direct.await_count, 3)
        self.assertEqual(len(self.pool._token_pool_queues[self.bucket]), 1)

    async def test_failure_notification_does_not_make_waiter_spin(self):
        self.pool._token_pool_waiters.clear()
        waiter = asyncio.create_task(self.pool._wait_for_token_pool_token(
            bucket_key=self.bucket, project_id="project", action=self.bucket, token_id=1
        ))
        try:
            await _schedule_pending_tasks()
            await _schedule_pending_tasks()
            self.assertEqual(self.pool._get_token_bundle_direct.await_count, 1)
            self.assertFalse(waiter.done())
        finally:
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
        self.assertFalse(self.pool._token_pool_waiters)
        self.assertFalse(self.pool._token_pool_refill_inflight)

    async def test_success_replenishes_immediately_and_notifies_waiter(self):
        self.pool._token_pool_waiters.clear()
        self.target = 2
        self.pool._get_token_bundle_direct.return_value = {"token": "synthetic"}
        waiter = asyncio.create_task(self.pool._wait_for_token_pool_token(
            bucket_key=self.bucket, project_id="project", action=self.bucket, token_id=1
        ))
        lease = await waiter
        self.assertEqual(lease.token, "synthetic")
        await _schedule_pending_tasks()
        self.assertEqual(len(self.pool._token_pool_queues[self.bucket]), 2)
        self.assertEqual(self.pool._get_token_bundle_direct.await_count, 3)

    async def test_failed_refill_exception_is_throttled_and_config_can_disable_pool(self):
        self.pool._get_token_bundle_direct.side_effect = RuntimeError("synthetic unavailable")
        await self.pool._maintain_token_pool_once()
        await _schedule_pending_tasks()
        self.assertEqual(self.pool._get_token_bundle_direct.await_count, 1)
        self.enabled = False
        await self.pool._maintain_token_pool_once()
        self.assertFalse(self.pool._token_pool_refill_inflight)
        self.assertFalse(self.pool._token_pool_bucket_meta)
        self.assertFalse(self.pool._token_pool_queues)

    async def test_close_cancels_inflight_refill_without_respawning(self):
        started = asyncio.Event()

        async def solve(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        self.pool._get_token_bundle_direct.side_effect = solve
        await self.pool._maintain_token_pool_once()
        await started.wait()
        await self.pool.close()
        self.assertFalse(self.pool._token_pool_fill_tasks)
        self.assertFalse(self.pool._token_pool_refill_inflight)
        self.assertEqual(self.pool._get_token_bundle_direct.await_count, 1)

    async def test_cancelled_refill_keeps_backoff_without_a_sleeping_task(self):
        started = asyncio.Event()

        async def solve(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        self.pool._get_token_bundle_direct.side_effect = solve
        await self.pool._maintain_token_pool_once()
        await started.wait()
        task = next(iter(self.pool._token_pool_fill_tasks))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.pool._maintain_token_pool_once()
        await _schedule_pending_tasks()
        self.assertEqual(self.pool._get_token_bundle_direct.await_count, 1)
        self.assertFalse(self.pool._token_pool_refill_inflight)
        self.assertFalse(self.pool._token_pool_fill_tasks)
