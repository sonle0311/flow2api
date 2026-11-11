"""Synthetic overload and terminal CAPTCHA regressions; no provider traffic."""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from src.services.flow_client import FlowClient


PROJECT = "11111111-1111-4111-8111-111111111111"
MEDIA = "22222222-2222-4222-8222-222222222222"
OPERATION = "33333333-3333-4333-8333-333333333333"


def _client():
    client = FlowClient(None)
    client._get_runtime_config = lambda: SimpleNamespace(
        flow_max_retries=3, flow_image_request_timeout=90
    )
    client._load_flow_frontend_bootstrap = AsyncMock(return_value=(
        'boq_labs-ai-sandbox-frontend_test {"FdrFJe":"123","SNlM0e":"original"}'
    ))
    client._notify_browser_captcha_error = AsyncMock()
    client._notify_browser_captcha_request_finished = AsyncMock()
    client._update_flow_cookie_jar = lambda *args: None
    return client


async def _generate(client, kind):
    kwargs = dict(
        at="synthetic", project_id=PROJECT, prompt="synthetic",
        aspect_ratio=f"{kind.upper()}_ASPECT_RATIO_LANDSCAPE",
        google_cookies="SID=synthetic", token_id=1,
    )
    if kind == "image":
        return await client.generate_image(model_name="BELUGA", **kwargs)
    return await client.generate_video_text(model_key="macaron_cookie_t2v_8s", **kwargs)


def _response(status, text):
    return SimpleNamespace(
        status_code=status, text=text, headers={"Retry-After": "10"}
    )


class ProviderHttpOverloadTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, kind, first_response, *, always_reject=False):
        client = _client()
        client._get_recaptcha_token = AsyncMock(return_value=("synthetic", "lease"))
        posts = []

        class Session:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, **kwargs):
                posts.append(kwargs["data"])
                if len(posts) == 1 or always_reject:
                    return first_response
                rpc = parse_qs(urlparse(url).query)["rpcids"][0]
                payload = (
                    [[[MEDIA, f"https://flow-content.google/image/{MEDIA}"]]]
                    if kind == "image" else [[OPERATION, PROJECT, MEDIA]]
                )
                return _response(200, json.dumps([["wrb.fr", rpc, json.dumps(payload)]]))

        error = None
        with (
            patch("src.services.flow_client.AsyncSession", Session),
            patch("src.services.flow_client.asyncio.sleep", new=AsyncMock()) as sleep,
        ):
            try:
                await _generate(client, kind)
            except Exception as failure:
                error = failure
        return client, posts, error, sleep

    async def test_plain_http_overload_retries_known_rejection_once_then_succeeds(self):
        for kind in ("image", "video"):
            for status, body in ((429, "<html>Too Many Requests</html>"), (503, "Unavailable")):
                with self.subTest(kind=kind, status=status):
                    client, posts, error, sleep = await self._run(kind, _response(status, body))
                    self.assertIsNone(error)
                    self.assertEqual(len(posts), 2)
                    self.assertEqual(client._get_recaptcha_token.await_count, 2)
                    self.assertEqual(client._notify_browser_captcha_request_finished.await_count, 2)
                    self.assertEqual(sleep.await_count, 1)

    async def test_accepted_rpc_payload_on_http_overload_is_never_resubmitted(self):
        video_rpc, _ = _client()._build_frontend_video_generation_argument(
            project_id=PROJECT, prompt="synthetic",
            model_key="macaron_cookie_t2v_8s",
            aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE",
            recaptcha_token="synthetic", session_id="synthetic", mode="text",
        )
        for kind, rpc, payload in (
            ("image", "ogiZ0b", [[[MEDIA, f"https://flow-content.google/image/{MEDIA}"]]]),
            ("video", video_rpc, [[OPERATION, PROJECT, MEDIA]]),
        ):
            for status in (429, 503):
                with self.subTest(kind=kind, status=status):
                    client, posts, error, sleep = await self._run(
                        kind, _response(status, json.dumps([["wrb.fr", rpc, json.dumps(payload)]]))
                    )
                    self.assertIsNone(error)
                    self.assertEqual(len(posts), 1)
                    self.assertEqual(client._get_recaptcha_token.await_count, 1)
                    self.assertEqual(client._notify_browser_captcha_request_finished.await_count, 1)
                    self.assertEqual(sleep.await_count, 0)

    async def test_exhausted_overload_retains_status_headers_and_retry_budget(self):
        for kind in ("image", "video"):
            for status in (429, 503):
                with self.subTest(kind=kind, status=status):
                    client, posts, error, sleep = await self._run(
                        kind, _response(status, "<html>Overloaded</html>"), always_reject=True
                    )
                    self.assertIn(f"HTTP Error {status}", str(error))
                    self.assertEqual(getattr(error, "status_code", None), status)
                    self.assertEqual(getattr(error, "headers", {}).get("Retry-After"), "10")
                    self.assertFalse(getattr(error, "submission_uncertain", False))
                    self.assertEqual(len(posts), 3)
                    self.assertEqual(sleep.await_count, 2)
                    self.assertEqual(client._notify_browser_captcha_request_finished.await_count, 3)

    async def test_http_rejection_still_uses_xsrf_refresh_before_generic_fallback(self):
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                client, posts, error, sleep = await self._run(
                    kind, _response(403, '[["xsrf","replacement"]]')
                )
                self.assertIsNone(error)
                self.assertEqual(len(posts), 2)
                self.assertEqual(parse_qs(posts[0])["at"], ["original"])
                self.assertEqual(parse_qs(posts[1])["at"], ["replacement"])
                self.assertEqual(parse_qs(posts[0])["f.req"], parse_qs(posts[1])["f.req"])
                self.assertEqual(client._get_recaptcha_token.await_count, 1)
                self.assertEqual(sleep.await_count, 0)

    async def test_framed_rpc_cause_wins_over_http_status(self):
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                _, posts, error, sleep = await self._run(
                    kind, _response(503, '[["er",null,null,null,null,401]]')
                )
                self.assertIn("code=401", str(error))
                self.assertEqual(len(posts), 1)
                self.assertEqual(sleep.await_count, 0)

    async def test_framed_overload_retains_http_metadata_after_bounded_retries(self):
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                _, posts, error, sleep = await self._run(
                    kind, _response(503, '[["er",null,null,null,null,429]]'),
                    always_reject=True,
                )
                self.assertIn("code=429", str(error))
                self.assertEqual(getattr(error, "status_code", None), 503)
                self.assertEqual(getattr(error, "headers", {}).get("Retry-After"), "10")
                self.assertEqual(len(posts), 3)
                self.assertEqual(sleep.await_count, 2)

    async def test_cancelled_submission_releases_captcha_once_without_resubmission(self):
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                client = _client()
                client._get_recaptcha_token = AsyncMock(return_value=("synthetic", "lease"))
                started = asyncio.Event()
                posts = []

                class Session:
                    def __init__(self, **kwargs):
                        pass

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        pass

                    async def post(self, url, **kwargs):
                        posts.append(url)
                        started.set()
                        await asyncio.Event().wait()

                with patch("src.services.flow_client.AsyncSession", Session):
                    task = asyncio.create_task(_generate(client, kind))
                    await asyncio.wait_for(started.wait(), 1)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertEqual(len(posts), 1)
                client._notify_browser_captcha_request_finished.assert_awaited_once_with("lease")


class TerminalCaptchaProviderTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, poll_results, *, kind=None, create_result=None):
        client = _client()
        posts = []
        settings = SimpleNamespace(
            captcha_method="yescaptcha", yescaptcha_api_key="synthetic",
            yescaptcha_base_url="https://synthetic.invalid",
            yescaptcha_task_type="RecaptchaV3TaskProxylessM1S9",
        )
        polls = iter(poll_results)

        class Session:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, **kwargs):
                posts.append(url)
                if url.endswith("/createTask"):
                    payload = create_result or {"errorId": 0, "taskId": "synthetic-task"}
                elif url.endswith("/getTaskResult"):
                    payload = next(polls, poll_results[-1])
                else:
                    raise AssertionError("Terminal CAPTCHA must not submit a generation RPC")
                if isinstance(payload, Exception):
                    raise payload
                return SimpleNamespace(status_code=200, json=lambda: payload)

        result = error = None
        with (
            patch("src.services.flow_client.AsyncSession", Session),
            patch("src.services.flow_client.config", settings),
            patch("src.services.flow_client.asyncio.sleep", new=AsyncMock()) as sleep,
        ):
            try:
                result = (
                    await _generate(client, kind) if kind else
                    await client._get_api_captcha_token("yescaptcha", PROJECT)
                )
            except Exception as failure:
                error = failure
        return client, posts, result, error, sleep

    async def test_terminal_poll_error_stops_immediately_and_retains_provider_cause(self):
        errors = (
            {"errorId": 1, "errorCode": "ERROR_CAPTCHA_UNSOLVABLE", "errorDescription": "synthetic terminal failure"},
            {"errorCode": "ERROR_KEY_DOES_NOT_EXIST", "errorDescription": "invalid key"},
            {"errorId": 12, "errorDescription": "terminal failure without code"},
        )
        for payload in errors:
            with self.subTest(payload=payload):
                _, posts, _, error, sleep = await self._run([payload])
                self.assertIsInstance(error, RuntimeError)
                self.assertIn(payload["errorDescription"], str(error))
                self.assertEqual(getattr(error, "error_code", None), payload.get("errorCode", ""))
                self.assertEqual(getattr(error, "error_id", None), payload.get("errorId"))
                self.assertEqual(sum(url.endswith("/getTaskResult") for url in posts), 1)
                self.assertEqual(sleep.await_count, 0)

    async def test_outer_generation_does_not_recreate_terminal_failed_tasks(self):
        payload = {
            "errorId": 1, "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
            "errorDescription": "reCAPTCHA task not found, 503 provider failure",
        }
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                client, posts, _, error, sleep = await self._run([payload], kind=kind)
                self.assertIn("ERROR_CAPTCHA_UNSOLVABLE", str(error))
                self.assertEqual(sum(url.endswith("/createTask") for url in posts), 1)
                self.assertEqual(sum(url.endswith("/getTaskResult") for url in posts), 1)
                self.assertEqual(sleep.await_count, 0)
                client._notify_browser_captcha_request_finished.assert_awaited_once_with(None)

    async def test_permanent_create_failure_is_preserved_without_outer_retry(self):
        payload = {
            "errorId": 1, "errorCode": "ERROR_KEY_DOES_NOT_EXIST",
            "errorDescription": "reCAPTCHA provider credential invalid",
        }
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                _, posts, _, error, sleep = await self._run([], kind=kind, create_result=payload)
                self.assertIn("ERROR_KEY_DOES_NOT_EXIST", str(error))
                self.assertEqual(len(posts), 1)
                self.assertEqual(sleep.await_count, 0)

    async def test_processing_poll_continues_and_success_retains_user_agent(self):
        processing = {"errorId": "0", "status": "processing"}
        ready = {
            "errorId": 0, "status": "ready",
            "solution": {"gRecaptchaResponse": "synthetic-token", "userAgent": "synthetic-agent"},
        }
        _, posts, result, error, sleep = await self._run([processing, ready])
        self.assertIsNone(error)
        self.assertEqual(result, ("synthetic-token", "synthetic-agent"))
        self.assertEqual(sum(url.endswith("/getTaskResult") for url in posts), 2)
        sleep.assert_awaited_once_with(3)

    async def test_poll_network_failure_obeys_outer_generation_retry_budget(self):
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                client, posts, _, error, sleep = await self._run(
                    [TimeoutError("synthetic network timeout")], kind=kind
                )
                self.assertIsNotNone(error)
                self.assertEqual(sum(url.endswith("/createTask") for url in posts), 3)
                self.assertEqual(sum(url.endswith("/getTaskResult") for url in posts), 3)
                self.assertEqual(sleep.await_count, 2)
                self.assertEqual(client._notify_browser_captcha_request_finished.await_count, 3)

    async def test_provider_slot_shortage_keeps_bounded_backoff_and_original_code(self):
        payload = {
            "errorId": 1, "errorCode": "ERROR_NO_SLOT_AVAILABLE",
            "errorDescription": "synthetic capacity shortage",
        }
        _, posts, _, error, sleep = await self._run([], create_result=payload)
        self.assertIn("ERROR_NO_SLOT_AVAILABLE", str(error))
        self.assertFalse(getattr(error, "captcha_provider_terminal", True))
        self.assertEqual(len(posts), 5)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [3, 5, 8, 13])
