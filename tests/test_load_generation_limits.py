"""Synthetic burst and cancellation regressions for real generation dispatch."""

import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

from src.core.config import config
from src.core.models import Token
from src.services.concurrency_manager import ConcurrencyManager
from src.services.generation_handler import GenerationHandler, MODEL_CONFIG
from src.services.load_balancer import LoadBalancer


def make_token(token_id=1, limit=1):
    return Token(
        id=token_id, st="synthetic-st", at="synthetic-at",
        at_expires=datetime.now(timezone.utc) + timedelta(hours=24),
        email=f"synthetic-{token_id}@example.invalid",
        user_paygate_tier="PAYGATE_TIER_TWO", image_concurrency=limit,
        video_concurrency=limit, auto_refresh_enabled=False,
    )


async def make_handler(tokens):
    cm = ConcurrencyManager()
    await cm.initialize(tokens)
    tm = SimpleNamespace(
        get_active_tokens=AsyncMock(return_value=tokens),
        ensure_valid_token=AsyncMock(side_effect=lambda t: t),
        needs_at_refresh=lambda t: False,
        ensure_project_exists=AsyncMock(return_value="synthetic-project"),
        record_error=AsyncMock(), record_usage=AsyncMock(), record_success=AsyncMock(),
        refresh_credits=AsyncMock(return_value=0),
    )
    handler = GenerationHandler.__new__(GenerationHandler)
    handler.token_manager, handler.concurrency_manager = tm, cm
    handler.load_balancer = LoadBalancer(tm, cm)
    handler.load_balancer._check_extension_route = AsyncMock(return_value=(True, ""))
    handler.proxy_manager = None
    handler.db = SimpleNamespace(update_request_log=AsyncMock())
    handler._log_request = AsyncMock(return_value=1)
    handler.flow_client = SimpleNamespace(
        clear_request_fingerprint=lambda: None, prefill_remote_browser_pool=AsyncMock(),
    )
    return handler


def model_for(kind):
    return next(
        name for name, cfg in MODEL_CONFIG.items()
        if cfg["type"] == kind and not cfg.get("upsample")
        and (kind == "image" or cfg.get("video_type") == "t2v")
    )


def provider_result(kind):
    if kind == "image":
        return ({"media": [{"name": "synthetic-media", "image": {
            "generatedImage": {"fifeUrl": "https://example.invalid/synthetic.png"},
        }}]}, "synthetic-session", {})
    return {"direct_media": True, "video_url": "https://example.invalid/synthetic.mp4"}


async def consume(handler, kind, stream=False):
    return [chunk async for chunk in handler.handle_generation(
        model_for(kind), "synthetic prompt", stream=stream,
    )]


class GenerationLimitLoadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cache = patch.object(type(config), "cache_enabled", new_callable=PropertyMock, return_value=False)
        self.mode = patch.object(type(config), "call_logic_mode", new_callable=PropertyMock, return_value="default")
        self.cache.start()
        self.mode.start()
        self.addCleanup(self.cache.stop)
        self.addCleanup(self.mode.stop)

    async def assert_released(self, handler, tokens):
        for token in tokens:
            self.assertEqual(await handler.concurrency_manager.get_image_inflight(token.id), 0)
            self.assertEqual(await handler.concurrency_manager.get_video_inflight(token.id), 0)
        self.assertEqual(handler.load_balancer._image_pending, {})
        self.assertEqual(handler.load_balancer._video_pending, {})

    async def burst(self, kind, tokens, expected):
        handler = await make_handler(tokens)
        release, decided = asyncio.Event(), asyncio.Event()
        arrivals, decisions, counts = set(), set(), {}
        n = 12

        def decision():
            decisions.add(asyncio.current_task())
            if len(decisions) == n:
                decided.set()

        async def provider(**kwargs):
            arrivals.add(asyncio.current_task())
            token_id = kwargs["token_id"]
            counts[token_id] = counts.get(token_id, 0) + 1
            decision()
            await release.wait()
            return provider_result(kind)

        setattr(handler.flow_client, "generate_image" if kind == "image" else "generate_video_text", provider)

        async def run():
            try:
                return await consume(handler, kind)
            finally:
                decision()

        tasks = [asyncio.create_task(run()) for _ in range(n)]
        try:
            await asyncio.wait_for(decided.wait(), 2)
            self.assertEqual(len(arrivals), expected)
            for token in tokens:
                self.assertLessEqual(counts.get(token.id, 0), token.image_concurrency if token.image_concurrency > 0 else n)
                inflight = getattr(handler.concurrency_manager, f"get_{kind}_inflight")
                self.assertEqual(await inflight(token.id), counts.get(token.id, 0))
            self.assertEqual(handler.load_balancer._image_pending, {})
            self.assertEqual(handler.load_balancer._video_pending, {})
        finally:
            release.set()
            results = await asyncio.gather(*tasks)
        self.assertEqual(sum("error" not in json.loads(chunks[-1]) for chunks in results), expected)
        for chunks in results:
            error = json.loads(chunks[-1]).get("error")
            if error:
                self.assertEqual(error["status_code"], 503)
        await self.assert_released(handler, tokens)

    async def test_finite_image_and_video_bursts_respect_account_capacity(self):
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                await self.burst(kind, [make_token()], 1)

    async def test_two_accounts_distribute_within_each_limit(self):
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                await self.burst(kind, [make_token(1), make_token(2)], 2)

    async def test_explicit_unlimited_accepts_entire_burst(self):
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                await self.burst(kind, [make_token(limit=-1)], 12)

    async def test_cancellation_at_first_post_selection_log_releases_account(self):
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                token = make_token()
                handler = await make_handler([token])
                selected = asyncio.Event()

                async def update(*args, **kwargs):
                    if kwargs.get("status_text") == "token_selected":
                        selected.set()
                        await asyncio.Event().wait()

                handler.db.update_request_log = update
                request = asyncio.create_task(consume(handler, kind, stream=True))
                await asyncio.wait_for(selected.wait(), 2)
                request.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await request
                await self.assert_released(handler, [token])
                selected_token = await handler.load_balancer.select_token(
                    **{f"for_{kind}_generation": True}, reserve=True,
                )
                self.assertEqual(selected_token.id, token.id)
                await getattr(handler.concurrency_manager, f"release_{kind}")(token.id)

    async def test_repeated_cancellation_cannot_interrupt_slot_cleanup(self):
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                token = make_token()
                handler = await make_handler([token])
                entered, cleaning, release_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()

                async def provider(**kwargs):
                    entered.set()
                    await asyncio.Event().wait()

                original_release = getattr(handler.concurrency_manager, f"release_{kind}")

                async def slow_release(token_id):
                    cleaning.set()
                    await release_cleanup.wait()
                    await original_release(token_id)

                setattr(handler.flow_client, "generate_image" if kind == "image" else "generate_video_text", provider)
                setattr(handler.concurrency_manager, f"release_{kind}", slow_release)
                request = asyncio.create_task(consume(handler, kind))
                await asyncio.wait_for(entered.wait(), 2)
                request.cancel()
                try:
                    await asyncio.wait_for(cleaning.wait(), 0.5)
                    request.cancel()
                    await asyncio.sleep(0)
                    request.cancel()
                finally:
                    release_cleanup.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await request
                await self.assert_released(handler, [token])

    async def test_validation_failure_releases_original_reservation(self):
        token = make_token()
        handler = await make_handler([token])
        handler.token_manager.ensure_valid_token.side_effect = [token, None]
        chunks = await consume(handler, "image")
        self.assertIn("error", json.loads(chunks[-1]))
        await self.assert_released(handler, [token])

    async def test_provider_errors_release_reserved_capacity(self):
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                token = make_token()
                handler = await make_handler([token])
                setattr(handler.flow_client, "generate_image" if kind == "image" else "generate_video_text", AsyncMock(side_effect=RuntimeError("synthetic provider rejection")))
                chunks = await consume(handler, kind)
                self.assertIn("synthetic provider rejection", json.loads(chunks[-1])["error"]["message"])
                await self.assert_released(handler, [token])

    async def test_hard_reservation_never_waits_for_pending_lock(self):
        token = make_token()
        handler = await make_handler([token])
        async with handler.load_balancer._pending_lock:
            # Selection reads load under this lock; bypass that read to test the
            # ownership handoff after the atomic concurrency reservation.
            with patch.object(handler.load_balancer, "_get_token_load", new=AsyncMock(return_value=(0, 1))):
                selected = await asyncio.wait_for(handler.load_balancer.select_token(
                    for_image_generation=True, reserve=True, track_pending=True,
                ), 2)
        self.assertEqual(selected.id, token.id)
        self.assertEqual(handler.load_balancer._image_pending, {})
        self.assertEqual(await handler.concurrency_manager.get_image_inflight(token.id), 1)
        await handler.concurrency_manager.release_image(token.id)

    async def test_closing_stream_after_selection_releases_reservation(self):
        token = make_token()
        handler = await make_handler([token])
        generation = handler.handle_generation(model_for("image"), "synthetic", stream=True)
        await anext(generation)
        await anext(generation)
        await generation.aclose()
        await self.assert_released(handler, [token])

    async def test_failover_releases_each_account_once(self):
        tokens = [make_token(1), make_token(2)]
        handler = await make_handler(tokens)
        attempted = []

        async def provider(**kwargs):
            attempted.append(kwargs["token_id"])
            if len(attempted) == 1:
                raise RuntimeError("PUBLIC_ERROR_USER_QUOTA_REACHED")
            return provider_result("image")

        handler.flow_client.generate_image = provider
        release = handler.concurrency_manager.release_image
        handler.concurrency_manager.release_image = AsyncMock(side_effect=release)
        chunks = await consume(handler, "image")
        self.assertNotIn("error", json.loads(chunks[-1]))
        self.assertEqual(len(set(attempted)), 2)
        self.assertEqual([call.args[0] for call in handler.concurrency_manager.release_image.await_args_list], attempted)
        await self.assert_released(handler, tokens)
