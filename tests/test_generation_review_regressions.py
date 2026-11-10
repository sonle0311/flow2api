"""Synthetic regressions for generation transport, accounting and task lifecycle."""

import asyncio
import json
import os
import socket
import tempfile
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch
from urllib.parse import parse_qs, urlparse

from curl_cffi import CurlECode, CurlError

from src.core.config import config
from src.services.file_cache import FileCache
from src.services.flow_client import FlowClient
from src.services.generation_handler import GenerationHandler
from test_token_quota_failover import _build_handler, _token


PROJECT = "11111111-1111-4111-8111-111111111111"
MEDIA = "22222222-2222-4222-8222-222222222222"
OPERATION = "33333333-3333-4333-8333-333333333333"
VIDEO_URL = f"https://flow-content.google/video/{MEDIA}"
IMAGE_URL = f"https://flow-content.google/image/{MEDIA}"


class SubmissionTransportRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def _generate(
        self,
        kind,
        *,
        bootstrap_failure=False,
        session_failure=False,
        response_read_failure=False,
        transport_failure=None,
    ):
        client = FlowClient(None)
        bootstrap = 'boq_labs-ai-sandbox-frontend_test "FdrFJe":"123"'
        client._load_flow_frontend_bootstrap = AsyncMock(
            side_effect=(
                [TimeoutError("bootstrap timed out"), bootstrap]
                if bootstrap_failure else None
            ),
            return_value=bootstrap,
        )
        client._get_recaptcha_token = AsyncMock(return_value=("synthetic", None))
        client._notify_browser_captcha_error = AsyncMock()
        client._notify_browser_captcha_request_finished = AsyncMock()
        client._update_flow_cookie_jar = lambda *args: None
        client._get_runtime_config = lambda: SimpleNamespace(
            flow_max_retries=2, flow_image_request_timeout=90
        )
        posts = []
        sessions = []
        failure = transport_failure or TimeoutError(
            "Operation timed out after upload; job accepted"
        )

        class Session:
            def __init__(self, **kwargs):
                sessions.append(self)

            async def __aenter__(self):
                if session_failure and len(sessions) == 1:
                    raise TimeoutError("session initialization timed out")
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, **kwargs):
                posts.append(kwargs["data"])
                if not bootstrap_failure and not session_failure and len(posts) == 1:
                    if response_read_failure:

                        class AcceptedResponse:
                            status_code = 200

                            @property
                            def text(self):
                                raise failure

                        return AcceptedResponse()
                    raise failure
                rpc = parse_qs(urlparse(url).query)["rpcids"][0]
                payload = (
                    [[[MEDIA, f"https://flow-content.google/image/{MEDIA}"]]]
                    if kind == "image" else [[OPERATION, PROJECT, MEDIA]]
                )
                return SimpleNamespace(
                    status_code=200,
                    text=json.dumps([["wrb.fr", rpc, json.dumps(payload)]]),
                )

        kwargs = dict(
            at="synthetic",
            project_id=PROJECT,
            prompt="synthetic",
            aspect_ratio=f"{kind.upper()}_ASPECT_RATIO_LANDSCAPE",
            google_cookies="SID=synthetic",
        )
        with patch("src.services.flow_client.AsyncSession", Session), patch(
            "src.services.flow_client.asyncio.sleep", new=AsyncMock()
        ):
            try:
                if kind == "image":
                    result = await client.generate_image(model_name="BELUGA", **kwargs)
                else:
                    result = await client.generate_video_text(
                        model_key="macaron_cookie_t2v_8s", **kwargs
                    )
            except Exception as error:
                return client, posts, failure, error
        return client, posts, result, None

    async def test_accepted_image_timeout_is_uncertain_and_never_resubmitted(self):
        client, posts, cause, error = await self._generate("image")
        self.assertIsNotNone(error)
        self.assertTrue(getattr(error, "submission_uncertain", False))
        self.assertIs(error.__cause__, cause)
        self.assertEqual(len(posts), 1)
        self.assertEqual(client._get_recaptcha_token.await_count, 1)

    async def test_accepted_video_timeout_is_uncertain_and_never_resubmitted(self):
        client, posts, cause, error = await self._generate("video")
        self.assertIsNotNone(error)
        self.assertTrue(getattr(error, "submission_uncertain", False))
        self.assertIs(error.__cause__, cause)
        self.assertEqual(len(posts), 1)
        self.assertEqual(client._get_recaptcha_token.await_count, 1)

    async def test_losing_the_accepted_response_body_does_not_resubmit(self):
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                _, posts, cause, error = await self._generate(
                    kind, response_read_failure=True
                )
                self.assertIsNotNone(error)
                self.assertTrue(getattr(error, "submission_uncertain", False))
                self.assertIs(error.__cause__, cause)
                self.assertEqual(len(posts), 1)

    async def test_bootstrap_failure_remains_safe_to_retry(self):
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                _, posts, _, error = await self._generate(kind, bootstrap_failure=True)
                self.assertIsNone(error)
                self.assertEqual(len(posts), 1)

    async def test_session_initialization_failure_remains_safe_to_retry(self):
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                _, posts, _, error = await self._generate(kind, session_failure=True)
                self.assertIsNone(error)
                self.assertEqual(len(posts), 1)

    async def test_proven_preconnect_failures_remain_safe_to_retry(self):
        failures = [
            ConnectionRefusedError("connection refused"),
            socket.gaierror(-2, "synthetic DNS failure"),
            *[
                CurlError("synthetic preconnect failure", code)
                for code in (
                    CurlECode.COULDNT_RESOLVE_PROXY,
                    CurlECode.COULDNT_RESOLVE_HOST,
                    CurlECode.COULDNT_CONNECT,
                    CurlECode.SSL_CONNECT_ERROR,
                )
            ],
        ]
        for kind in ("image", "video"):
            for failure in failures:
                with self.subTest(kind=kind, failure=repr(failure)):
                    _, posts, _, error = await self._generate(
                        kind, transport_failure=failure
                    )
                    self.assertIsNone(error)
                    self.assertEqual(len(posts), 2)

    async def test_connection_reset_remains_uncertain(self):
        redirect_failure = CurlError(
            "connection refused after redirect", CurlECode.COULDNT_CONNECT
        )
        redirect_failure.response = SimpleNamespace(status_code=0, redirect_count=1)
        for kind in ("image", "video"):
            for failure in (
                ConnectionResetError("connection reset after upload"),
                redirect_failure,
            ):
                with self.subTest(kind=kind, failure=str(failure)):
                    _, posts, cause, error = await self._generate(
                        kind, transport_failure=failure
                    )
                    self.assertTrue(getattr(error, "submission_uncertain", False))
                    self.assertIs(error.__cause__, cause)
                    self.assertEqual(len(posts), 1)


class ImageUpscaleUncertaintyRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def _upscale(self, *, unknown_error=None):
        handler = GenerationHandler.__new__(GenerationHandler)
        handler._update_request_log_progress = AsyncMock()
        client = handler.flow_client = FlowClient(None)
        client.generate_image = AsyncMock(return_value=(
            {"media": [{
                "name": MEDIA,
                "image": {"generatedImage": {"fifeUrl": IMAGE_URL}},
            }]},
            "synthetic-session",
            {},
        ))
        client._load_flow_frontend_bootstrap = AsyncMock(
            return_value='boq_labs-ai-sandbox-frontend_test "FdrFJe":"123"'
        )
        client._get_recaptcha_token = AsyncMock(return_value=("synthetic", None))
        client._notify_browser_captcha_request_finished = AsyncMock()
        client._update_flow_cookie_jar = lambda *args: None
        client._get_runtime_config = lambda: SimpleNamespace(upsample_timeout=30)
        if unknown_error is not None:
            client.upsample_image = AsyncMock(side_effect=unknown_error)
        token = _token(1)
        token.at, token.google_cookies = "synthetic", "SID=synthetic"
        posts = []

        class Session:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, **kwargs):
                rpc = parse_qs(urlparse(url).query)["rpcids"][0]
                posts.append(rpc)
                if len(posts) == 1:
                    raise TimeoutError("Operation timed out after upscale accepted")
                return SimpleNamespace(
                    status_code=200,
                    text=json.dumps([["wrb.fr", rpc, json.dumps([IMAGE_URL + "?4k=1"])]]),
                )

        response_state = handler._create_response_state()
        generation_result = {}
        with (
            patch("src.services.flow_client.AsyncSession", Session),
            patch("src.services.generation_handler.asyncio.sleep", new=AsyncMock()),
            patch.object(type(config), "flow_max_retries", new_callable=PropertyMock, return_value=3),
            patch.object(type(config), "cache_enabled", new_callable=PropertyMock, return_value=False),
        ):
            chunks = [chunk async for chunk in handler._handle_image_generation(
                token,
                PROJECT,
                {"model_name": "BELUGA", "aspect_ratio": "IMAGE_ASPECT_RATIO_LANDSCAPE", "upsample": "UPSAMPLE_IMAGE_RESOLUTION_4K"},
                "synthetic",
                None,
                False,
                generation_result=generation_result,
                response_state=response_state,
            )]
        return client, posts, response_state, chunks

    async def test_accepted_upscale_timeout_never_resubmits_and_delivers_original(self):
        client, posts, response_state, chunks = await self._upscale()
        self.assertEqual(posts, ["SPrCad"])
        client._get_recaptcha_token.assert_awaited_once()
        self.assertEqual(response_state["url"], IMAGE_URL)
        self.assertEqual(
            response_state["generated_assets"]["upscaled_image"]["delivery_mode"],
            "origin_fallback",
        )
        self.assertIn(IMAGE_URL, chunks[-1])
        self.assertNotIn("?4k=1", chunks[-1])

    async def test_outcome_unknown_upscale_never_retries(self):
        error = TimeoutError("upscale timed out; outcome unknown")
        error.outcome_unknown = True
        client, _, response_state, chunks = await self._upscale(unknown_error=error)
        client.upsample_image.assert_awaited_once()
        self.assertEqual(response_state["url"], IMAGE_URL)
        self.assertIn(IMAGE_URL, chunks[-1])


class CreditEntitlementRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_balance_alone_never_invents_an_entitlement(self):
        for credits in (0, 100, 25000):
            with self.subTest(credits=credits):
                client = FlowClient(None)
                client._current_rpc = AsyncMock(return_value=[credits])
                result = await client.get_credits(google_cookies="SID=synthetic")
                self.assertEqual(result["credits"], credits)
                self.assertIsNone(result["userPaygateTier"])

    async def test_explicit_entitlement_is_independent_of_balance(self):
        for tier in ("PAYGATE_TIER_NOT_PAID", "PAYGATE_TIER_ONE", "PAYGATE_TIER_TWO"):
            with self.subTest(tier=tier):
                client = FlowClient(None)
                client._current_rpc = AsyncMock(
                    return_value=[0, {"userPaygateTier": tier}]
                )
                result = await client.get_credits(google_cookies="SID=synthetic")
                self.assertEqual(result["credits"], 0)
                self.assertEqual(result["userPaygateTier"], tier)


class CacheFallbackRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_fallback_keeps_lock_and_never_publishes_partial_output(self):
        for fallback in ("wget", "curl"):
            with (
                self.subTest(fallback=fallback),
                tempfile.TemporaryDirectory() as directory,
            ):
                cache = FileCache(directory)
                filename = cache._generate_cache_filename(VIDEO_URL, "video")
                final_path = Path(directory) / filename
                started = threading.Event()
                release = threading.Event()
                finished = threading.Event()
                output_paths = []

                class Session:
                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        pass

                    async def get(self, *args, **kwargs):
                        return SimpleNamespace(status_code=403, content=b"")

                def run(command, **kwargs):
                    if command[0] != fallback:
                        raise FileNotFoundError(command[0])
                    flag = "-O" if fallback == "wget" else "-o"
                    output_path = Path(command[command.index(flag) + 1])
                    output_paths.append(output_path)
                    output_path.write_bytes(b"partial")
                    if len(output_paths) == 1:
                        started.set()
                        try:
                            if not release.wait(timeout=3):
                                raise TimeoutError("test did not release download")
                            output_path.write_bytes(b"complete")
                        finally:
                            finished.set()
                    else:
                        output_path.write_bytes(b"complete")
                    return SimpleNamespace(returncode=0, stderr=b"")

                first = second = None
                with (
                    patch("src.services.file_cache.AsyncSession", Session),
                    patch("subprocess.run", side_effect=run),
                ):
                    try:
                        first = asyncio.create_task(
                            cache.download_and_cache(VIDEO_URL, "video")
                        )
                        self.assertTrue(await asyncio.to_thread(started.wait, 1))
                        unpublished_while_running = not final_path.exists()
                        # A short cache TTL must not let background cleanup
                        # remove a staging file still owned by the subprocess.
                        os.utime(output_paths[0], (1, 1))
                        cache.default_timeout = 1
                        await cache._cleanup_expired_files()
                        first.cancel()
                        await asyncio.sleep(0)
                        first.cancel()  # Repeated cancellation must not orphan output.
                        await asyncio.sleep(0)
                        second = asyncio.create_task(
                            cache.download_and_cache(VIDEO_URL, "video")
                        )
                        await asyncio.sleep(0)
                        await asyncio.sleep(0)
                        first_waited_for_worker = not first.done()
                        second_waited_for_lock = not second.done()
                        live_output_exists = output_paths[0].exists()
                    finally:
                        release.set()
                        await asyncio.to_thread(finished.wait, 1)
                        results = await asyncio.gather(
                            *[task for task in (first, second) if task is not None],
                            return_exceptions=True,
                        )
                self.assertTrue(unpublished_while_running)
                self.assertTrue(first_waited_for_worker)
                self.assertTrue(second_waited_for_lock)
                self.assertTrue(live_output_exists)
                self.assertIsInstance(results[0], asyncio.CancelledError)
                self.assertEqual(results[1], filename)
                self.assertEqual(final_path.read_bytes(), b"complete")
                self.assertEqual(len(output_paths), 2)
                self.assertTrue(all(path != final_path for path in output_paths))
                self.assertEqual(list(Path(directory).iterdir()), [final_path])

    async def test_fallback_commands_allow_the_event_loop_to_run(self):
        for fallback in ("wget", "curl"):
            with (
                self.subTest(fallback=fallback),
                tempfile.TemporaryDirectory() as directory,
            ):
                cache = FileCache(directory)
                started = threading.Event()
                event_loop_ran = threading.Event()
                commands = []

                class Session:
                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        pass

                    async def get(self, *args, **kwargs):
                        return SimpleNamespace(status_code=403, content=b"")

                def run(command, **kwargs):
                    commands.append(command[0])
                    if command[0] == "wget" and fallback == "curl":
                        raise FileNotFoundError("wget")
                    started.set()
                    if not event_loop_ran.wait(timeout=0.5):
                        return SimpleNamespace(
                            returncode=1, stderr=b"event loop blocked"
                        )
                    output_flag = "-O" if fallback == "wget" else "-o"
                    target = command[command.index(output_flag) + 1]
                    Path(target).write_bytes(b"synthetic-media")
                    self.assertEqual(kwargs["timeout"], 90)
                    return SimpleNamespace(returncode=0, stderr=b"")

                async def tick():
                    while not started.is_set():
                        await asyncio.sleep(0.001)
                    event_loop_ran.set()

                with (
                    patch("src.services.file_cache.AsyncSession", Session),
                    patch("subprocess.run", side_effect=run),
                ):
                    result, _ = await asyncio.gather(
                        cache.download_and_cache(VIDEO_URL, "video"), tick()
                    )
                self.assertTrue(event_loop_ran.is_set())
                self.assertEqual((Path(directory) / result).read_bytes(), b"synthetic-media")
                self.assertEqual(commands[-1], fallback)


def _video_handler():
    token = _token(1)
    token.at, token.google_cookies, token.st = "synthetic", "SID=synthetic", ""
    handler, _ = _build_handler([token], set())
    handler._handle_video_generation = types.MethodType(
        GenerationHandler._handle_video_generation, handler
    )
    handler.proxy_manager = None
    handler.db = SimpleNamespace(create_task=AsyncMock(), update_task=AsyncMock())
    return handler


class VideoLifecycleRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, handler, model="veo_3_1_t2v_1080p"):
        with (
            patch.object(
                type(config), "cache_enabled",
                new_callable=PropertyMock, return_value=False,
            ),
            patch("src.services.generation_handler.asyncio.sleep", new=AsyncMock()),
            patch("src.services.generation_handler.record_generation_result"),
        ):
            return [chunk async for chunk in handler.handle_generation(model, "synthetic")]

    async def test_direct_video_records_usage_and_success_once(self):
        handler = _video_handler()
        result = FlowClient._normalize_frontend_video_submission(
            [VIDEO_URL],
            project_id="project-1",
            aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE",
            model_key="macaron_cookie_t2v_8s",
        )
        handler.flow_client.generate_video_text = AsyncMock(return_value=result)
        chunks = await self._run(handler, "omni-1.2-flash")
        self.assertIn(VIDEO_URL, chunks[-1])
        handler.token_manager.record_usage.assert_awaited_once_with(1, is_video=True)
        handler.token_manager.record_success.assert_awaited_once_with(1)

    async def test_original_task_is_finalized_for_upscale_success_and_failure(self):
        for outcome in (
            "success", "failed", "error", "missing_url", "poll_error",
            "timeout", "empty_submit", "submit_error",
        ):
            with self.subTest(outcome=outcome):
                handler = _video_handler()
                original = {
                    "operation": {"name": "original-task"},
                    "name": "original-task",
                    "status": "MEDIA_GENERATION_STATUS_ACTIVE",
                }
                upscale = {
                    "operation": {"name": "upscale-task"},
                    "name": "upscale-task",
                    "status": "MEDIA_GENERATION_STATUS_ACTIVE",
                }
                handler.flow_client.generate_video_text = AsyncMock(
                    return_value={"operations": [original]}
                )
                handler.flow_client.upsample_video = AsyncMock(
                    return_value={
                        "operations": [] if outcome == "empty_submit" else [upscale]
                    }
                )
                if outcome == "submit_error":
                    handler.flow_client.upsample_video.side_effect = RuntimeError(
                        "upscale rejected"
                    )

                async def checked(at, operations, **kwargs):
                    is_upscale = operations[0]["name"] == "upscale-task"
                    if is_upscale and outcome == "poll_error":
                        raise OSError("synthetic poll failure")
                    status = "MEDIA_GENERATION_STATUS_SUCCESSFUL"
                    if is_upscale:
                        status = {
                            "failed": "MEDIA_GENERATION_STATUS_FAILED",
                            "error": "MEDIA_GENERATION_STATUS_ERROR_TEST",
                            "timeout": "MEDIA_GENERATION_STATUS_ACTIVE",
                        }.get(outcome, status)
                    return {"operations": [{**operations[0], "status": status}]}

                async def resolve(token, operation):
                    is_upscale = operation["name"] == "upscale-task"
                    video_url = VIDEO_URL + ("?upscale=1" if is_upscale else "")
                    if is_upscale and outcome == "missing_url":
                        video_url = ""
                    return {
                        "video_url": video_url,
                        "video_media_id": MEDIA,
                        "aspect_ratio": "VIDEO_ASPECT_RATIO_LANDSCAPE",
                        "media_name": MEDIA,
                        "metadata": {},
                        "video_info": {},
                    }

                handler.flow_client.check_video_status = checked
                handler._resolve_video_asset = AsyncMock(side_effect=resolve)
                handler.flow_client.get_media = AsyncMock(return_value={})
                with patch.object(
                    type(config), "video_timeout",
                    new_callable=PropertyMock, return_value=0.01,
                ):
                    chunks = await self._run(handler)
                created_ids = [
                    call.args[0].task_id
                    for call in handler.db.create_task.await_args_list
                ]
                self.assertEqual(created_ids, ["original-task"])
                updates = handler.db.update_task.await_args_list
                self.assertTrue(updates)
                self.assertEqual([c.args[0] for c in updates], ["original-task"])
                expected_status = (
                    "completed"
                    if outcome in {"success", "empty_submit", "submit_error"}
                    else "failed"
                )
                self.assertEqual(updates[-1].kwargs["status"], expected_status)
                if expected_status == "completed":
                    self.assertIn(updates[-1].kwargs["result_urls"][0], chunks[-1])
                else:
                    self.assertIn("error", json.loads(chunks[-1]))
