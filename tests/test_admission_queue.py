"""Requests wait in a bounded FIFO when every account is busy, then get 429 + Retry-After."""

import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

from src.api import routes
from src.core.config import config
from src.core.models import Token
from src.services.admission_queue import AdmissionQueue, AdmissionRejected
from src.services.concurrency_manager import ConcurrencyManager
from src.services.generation_handler import MODEL_CONFIG, GenerationHandler
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


def image_model():
    return next(
        name for name, cfg in MODEL_CONFIG.items()
        if cfg["type"] == "image" and not cfg.get("upsample")
    )


IMAGE_RESULT = ({"media": [{"name": "synthetic-media", "image": {
    "generatedImage": {"fifeUrl": "https://example.invalid/synthetic.png"},
}}]}, "synthetic-session", {})


async def consume(handler, prompt="synthetic prompt", stream=False):
    return [chunk async for chunk in handler.handle_generation(
        image_model(), prompt, stream=stream,
    )]


def last_error(chunks):
    return json.loads(chunks[-1]).get("error")


class AdmissionQueueTests(unittest.IsolatedAsyncioTestCase):
    def queue(self, max_waiting=5, timeout=5.0):
        return AdmissionQueue(lambda: max_waiting, lambda kind: timeout)

    async def test_waiters_are_served_in_arrival_order_as_slots_free_up(self):
        queue = self.queue()
        slots = 0
        served = []

        async def attempt():
            nonlocal slots
            if slots > 0:
                slots -= 1
                return "slot"
            return None

        async def saturated():
            return True

        async def waiter(name):
            await queue.wait_for_slot("image", attempt, saturated)
            served.append(name)

        tasks = []
        for name in ("a", "b", "c"):
            tasks.append(asyncio.create_task(waiter(name)))
            await asyncio.sleep(0.01)
        self.assertEqual(queue.waiting("image"), 3)
        for _ in range(3):
            slots += 1
            queue.notify()
            await asyncio.sleep(0.05)
        await asyncio.gather(*tasks)
        self.assertEqual(served, ["a", "b", "c"])
        self.assertEqual(queue.waiting("image"), 0)

    async def test_full_line_rejects_immediately_with_a_retry_hint(self):
        queue = self.queue(max_waiting=1)
        never = AsyncMock(return_value=None)
        saturated = AsyncMock(return_value=True)
        first = asyncio.create_task(queue.wait_for_slot("video", never, saturated))
        await asyncio.sleep(0.01)
        with self.assertRaises(AdmissionRejected) as caught:
            await queue.wait_for_slot("video", never, saturated)
        self.assertEqual((caught.exception.reason, caught.exception.retry_after), ("queue_full", 30))
        self.assertTrue(queue.is_full("video"))
        self.assertFalse(queue.is_full("image"))
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertEqual(queue.waiting("video"), 0)

    async def test_wait_is_bounded_in_time(self):
        queue = self.queue(timeout=0.3)
        with self.assertRaises(AdmissionRejected) as caught:
            await queue.wait_for_slot("image", AsyncMock(return_value=None), AsyncMock(return_value=True))
        self.assertEqual((caught.exception.reason, caught.exception.retry_after), ("queue_timeout", 10))
        self.assertGreaterEqual(caught.exception.waited_seconds, 0.25)
        self.assertEqual(queue.waiting("image"), 0)

    async def test_returns_none_when_capacity_is_no_longer_the_blocker(self):
        queue = self.queue()
        result = await queue.wait_for_slot("image", AsyncMock(return_value=None), AsyncMock(return_value=False))
        self.assertIsNone(result)
        self.assertEqual(queue.waiting("image"), 0)


class HandlerQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name, value in (
            ("cache_enabled", False), ("call_logic_mode", "default"),
            ("flow_queue_max_waiting", 5), ("flow_image_slot_wait_timeout", 5.0),
        ):
            patcher = patch.object(type(config), name, new_callable=PropertyMock, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def set_provider(self, handler, work):
        state = SimpleNamespace(active=0, peak=0, order=[])

        async def provider(**kwargs):
            state.active += 1
            state.peak = max(state.peak, state.active)
            state.order.append(kwargs["prompt"])
            try:
                await work()
                return IMAGE_RESULT
            finally:
                state.active -= 1

        handler.flow_client.generate_image = provider
        return state

    async def test_requests_over_capacity_wait_their_turn_and_all_succeed(self):
        handler = await make_handler([make_token(limit=1)])
        state = self.set_provider(handler, lambda: asyncio.sleep(0.05))
        tasks = []
        for index in range(4):
            tasks.append(asyncio.create_task(consume(handler, f"prompt-{index}")))
            await asyncio.sleep(0.01)
        results = await asyncio.gather(*tasks)
        self.assertTrue(all("error" not in json.loads(chunks[-1]) for chunks in results))
        self.assertEqual(state.peak, 1)
        self.assertEqual(state.order, [f"prompt-{index}" for index in range(4)])
        self.assertEqual(await handler.concurrency_manager.get_image_inflight(1), 0)
        self.assertEqual(handler.admission_queue.waiting("image"), 0)

    async def test_full_line_answers_429_with_retry_after_and_keeps_served_requests(self):
        handler = await make_handler([make_token(limit=1)])
        release = asyncio.Event()
        self.set_provider(handler, release.wait)
        with patch.object(type(config), "flow_queue_max_waiting", new_callable=PropertyMock, return_value=1):
            running = asyncio.create_task(consume(handler, "running"))
            await asyncio.sleep(0.05)
            queued = asyncio.create_task(consume(handler, "queued"))
            await asyncio.sleep(0.05)
            rejected = await consume(handler, "overflow")
            error = last_error(rejected)
            self.assertEqual(
                (error["status_code"], error["type"], error["code"], error["retry_after"]),
                (429, "rate_limit_error", "server_busy", 10),
            )
            self.assertIn("排队队列已满", error["message"])
            release.set()
            for chunks in await asyncio.gather(running, queued):
                self.assertNotIn("error", json.loads(chunks[-1]))
        self.assertEqual(await handler.concurrency_manager.get_image_inflight(1), 0)

    async def test_wait_that_outlasts_the_limit_answers_429(self):
        handler = await make_handler([make_token(limit=1)])
        release = asyncio.Event()
        self.set_provider(handler, release.wait)
        with patch.object(type(config), "flow_image_slot_wait_timeout", new_callable=PropertyMock, return_value=1.0):
            running = asyncio.create_task(consume(handler, "running"))
            await asyncio.sleep(0.05)
            error = last_error(await consume(handler, "late"))
        release.set()
        await running
        self.assertEqual((error["status_code"], error["retry_after"]), (429, 10))
        self.assertIn("等待可用账号超时", error["message"])
        self.assertEqual(handler.admission_queue.waiting("image"), 0)

    async def test_no_usable_account_is_still_an_immediate_503(self):
        handler = await make_handler([])
        error = last_error(await consume(handler))
        self.assertEqual(error["status_code"], 503)
        self.assertNotIn("retry_after", error)

    async def test_stream_tells_the_client_it_is_queued(self):
        handler = await make_handler([make_token(limit=1)])
        release = asyncio.Event()
        self.set_provider(handler, release.wait)
        running = asyncio.create_task(consume(handler, "running"))
        await asyncio.sleep(0.05)
        waiting = asyncio.create_task(consume(handler, "waiting", stream=True))
        await asyncio.sleep(0.05)
        release.set()
        await running
        chunks = await waiting
        self.assertTrue(any("正在排队" in chunk for chunk in chunks))
        self.assertNotIn("error", json.loads(chunks[-1]) if chunks[-1].lstrip().startswith("{") else {})

    async def test_preflight_rejects_streams_only_when_line_is_full_and_busy(self):
        handler = await make_handler([make_token(limit=1)])
        release = asyncio.Event()
        self.set_provider(handler, release.wait)
        self.assertIsNone(await handler.admission_preflight(image_model()))
        with patch.object(type(config), "flow_queue_max_waiting", new_callable=PropertyMock, return_value=1):
            running = asyncio.create_task(consume(handler, "running"))
            await asyncio.sleep(0.05)
            self.assertIsNone(await handler.admission_preflight(image_model()))
            queued = asyncio.create_task(consume(handler, "queued"))
            await asyncio.sleep(0.05)
            rejection = await handler.admission_preflight(image_model())
            self.assertEqual(rejection.reason, "queue_full")
            release.set()
            await asyncio.gather(running, queued)
        self.assertIsNone(await handler.admission_preflight("unknown-model"))


class RetryAfterResponseTests(unittest.TestCase):
    def test_openai_and_gemini_errors_carry_the_retry_after_header(self):
        payload = {"error": {"message": "busy", "status_code": 429, "retry_after": 30}}
        openai = routes._build_openai_json_response(payload)
        gemini = routes._build_gemini_error_response_from_handler(payload)
        for response in (openai, gemini):
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers["retry-after"], "30")
        self.assertEqual(json.loads(gemini.body)["error"]["status"], "RESOURCE_EXHAUSTED")

    def test_errors_without_a_hint_have_no_header(self):
        response = routes._build_openai_json_response({"error": {"message": "x", "status_code": 503}})
        self.assertNotIn("retry-after", response.headers)

    def test_stream_preflight_rejection_is_a_real_http_429(self):
        handler = GenerationHandler.__new__(GenerationHandler)
        previous = routes.generation_handler
        routes.set_generation_handler(handler)
        self.addCleanup(routes.set_generation_handler, previous)
        rejected = AdmissionRejected("queue_full", "video")
        for gemini in (False, True):
            response = routes._rejection_response(rejected, gemini=gemini)
            self.assertEqual((response.status_code, response.headers["retry-after"]), (429, "30"))


if __name__ == "__main__":
    unittest.main()
