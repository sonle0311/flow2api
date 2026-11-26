"""Input images are uploaded to Flow once per account and project, in every mode that takes images."""

import asyncio
import json
import tempfile
import time
import unittest
from itertools import count
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.core.database import Database
from src.services import upload_cache as cache_module
from src.services.generation_handler import GenerationHandler
from src.services.upload_cache import UploadCache, looks_like_stale_media
from tests.test_token_quota_failover import _build_handler, _token

STALE = "Flow frontend RPC rejected: rpc=ogiZ0b, code=[5]"
STOP = "stop after upload"


class CacheServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(str(Path(self.temp.name) / "flow.db"))
        await self.db.init_db()
        self.cache = UploadCache(self.db, ttl=3600)
        self.ids = count(1)
        self.uploads = []

    async def upload(self, data=b"image"):
        async def uploader():
            self.uploads.append(data)
            return f"media-{next(self.ids)}"
        return uploader

    async def get(self, data=b"image", token=1, project="p1", **kwargs):
        return await self.cache.get_or_upload(token, project, data, await self.upload(data), **kwargs)

    async def test_the_same_image_is_uploaded_once_for_an_account_and_project(self):
        self.assertEqual(("media-1", False), await self.get())
        self.assertEqual(("media-1", True), await self.get())
        self.assertEqual(1, len(self.uploads))

    async def test_a_media_id_is_never_shared_across_images_accounts_or_projects(self):
        await self.get(b"a")
        for kwargs in ({"data": b"b"}, {"token": 2}, {"project": "p2"}):
            _, reused = await self.get(**{"data": b"a", **kwargs})
            self.assertFalse(reused, kwargs)
        self.assertEqual(4, len(self.uploads))

    async def test_concurrent_requests_for_one_new_image_share_a_single_upload(self):
        gate = asyncio.Event()

        async def slow():
            self.uploads.append(b"x")
            await gate.wait()
            return "media-slow"

        tasks = [asyncio.create_task(self.cache.get_or_upload(1, "p1", b"x", slow)) for _ in range(5)]
        await asyncio.sleep(0.05)
        gate.set()
        results = await asyncio.gather(*tasks)
        self.assertEqual(1, len(self.uploads))
        self.assertEqual({"media-slow"}, {media for media, _ in results})

    async def test_a_failed_first_upload_does_not_fail_the_requests_waiting_on_it(self):
        gate = asyncio.Event()

        async def failing():
            await gate.wait()
            raise RuntimeError("captcha unavailable")

        leader = asyncio.create_task(self.cache.get_or_upload(1, "p1", b"x", failing))
        await asyncio.sleep(0.05)
        waiter = asyncio.create_task(self.cache.get_or_upload(1, "p1", b"x", await self.upload(b"x")))
        await asyncio.sleep(0.05)
        gate.set()
        with self.assertRaises(RuntimeError):
            await leader
        self.assertEqual(("media-1", False), await waiter)

    async def test_entries_expire(self):
        await self.get()
        with patch.object(cache_module.time, "time", return_value=time.time() + 7200):
            self.assertFalse((await self.get())[1])

    async def test_a_refused_media_id_can_be_forgotten_and_bypassed(self):
        await self.get()
        self.assertEqual(1, await self.cache.forget_media(1, "p1", ["media-1"]))
        self.assertEqual(("media-2", False), await self.get())
        self.assertEqual(("media-3", False), await self.get(use_cache=False))   # bypass uploads and stores
        self.assertEqual(("media-3", True), await self.get())

    async def test_the_table_is_trimmed_to_its_limit(self):
        small = UploadCache(self.db, ttl=3600, max_entries=3)
        for index in range(6):
            await small.get_or_upload(1, "p1", f"img{index}".encode(), await self.upload())
        async with self.db._connect() as conn:
            rows = (await (await conn.execute("SELECT COUNT(*) FROM upload_cache")).fetchone())[0]
        self.assertEqual(3, rows)

    async def test_it_can_be_switched_off(self):
        for ttl in (0, None):
            with patch.dict("os.environ", {"FLOW2API_UPLOAD_CACHE_HOURS": "0"}):
                off = UploadCache(self.db, ttl=ttl)
            self.assertFalse(off.enabled)
            await off.get_or_upload(1, "p1", b"z", await self.upload())
            self.assertFalse((await off.get_or_upload(1, "p1", b"z", await self.upload()))[1])

    def test_only_flows_not_found_answer_marks_a_media_id_stale(self):
        self.assertTrue(looks_like_stale_media(RuntimeError(STALE)))
        for text in ("Flow frontend RPC rejected: rpc=ogiZ0b, error=PUBLIC_ERROR_UNUSUAL_ACTIVITY", "timeout", "PUBLIC_ERROR_USER_QUOTA_REACHED"):
            self.assertFalse(looks_like_stale_media(RuntimeError(text)))


class EveryModeUsesTheCacheTests(unittest.IsolatedAsyncioTestCase):
    """Run the real image and video handlers; only Flow itself is replaced."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(str(Path(self.temp.name) / "flow.db"))
        await self.db.init_db()
        token = _token(1)
        token.at, token.google_cookies, token.st = "at", "SID=x", ""
        self.handler, _ = _build_handler([token], set())
        for name in ("_handle_image_generation", "_handle_video_generation"):
            setattr(self.handler, name, getattr(GenerationHandler, name).__get__(self.handler))
        self.handler.db = self.db
        self.handler.proxy_manager = None
        self.ids = count(1)
        self.uploaded = []

        async def upload_image(at, data, aspect, **kwargs):
            self.uploaded.append(data)
            return f"media-{next(self.ids)}"

        flow = self.handler.flow_client
        flow.upload_image = AsyncMock(side_effect=upload_image)
        self.submits = []
        for method in ("generate_image", "generate_video_start_image", "generate_video_start_end", "generate_video_reference_images"):
            setattr(flow, method, AsyncMock(side_effect=self._submit(method)))
        self.failures = []   # errors to raise before the generic stop, oldest first

    def _submit(self, method):
        async def submit(*args, **kwargs):
            self.submits.append((method, kwargs))
            raise RuntimeError(self.failures.pop(0) if self.failures else STOP)
        return submit

    async def run_model(self, model, images):
        with patch("src.services.generation_handler.record_generation_result"), \
             patch("src.services.generation_handler.asyncio.sleep", new=AsyncMock()):
            return [chunk async for chunk in self.handler.handle_generation(model, "prompt", images=images)]

    def logged_trace(self):
        return self.handler._log_request.await_args.args[3]["performance"]

    async def assert_second_request_reuses(self, model, images, uploads):
        await self.run_model(model, images)
        self.assertEqual(uploads, len(self.uploaded), "first request uploads every distinct image once")
        await self.run_model(model, images)
        self.assertEqual(uploads, len(self.uploaded), "second request uploads nothing")
        trace = self.logged_trace()["upload_cache"]
        self.assertEqual((len(images), 0), (trace["hits"], trace["misses"]))

    async def test_reference_images_for_an_image(self):
        await self.assert_second_request_reuses("gemini-3.1-flash-image-landscape", [b"ref-a", b"ref-b"], 2)

    async def test_a_single_start_frame(self):
        await self.assert_second_request_reuses("omni-1.2-flash-i2v-4s-landscape", [b"start"], 1)
        self.assertEqual("generate_video_start_image", self.submits[-1][0])

    async def test_a_start_frame_and_an_end_frame(self):
        await self.assert_second_request_reuses("omni-1.2-flash-i2v-4s-landscape", [b"start", b"end"], 2)
        self.assertEqual("generate_video_start_end", self.submits[-1][0])

    async def test_veo_reference_images(self):
        await self.assert_second_request_reuses("veo-3.1-fast-r2v-8s-landscape", [b"ref-a", b"ref-b"], 2)

    async def test_omni_reference_images(self):
        await self.assert_second_request_reuses("omni-1.2-flash-8s-landscape", [b"ref-a", b"ref-b", b"ref-c"], 3)

    async def test_an_image_used_as_a_reference_is_reused_as_a_start_frame(self):
        await self.run_model("gemini-3.1-flash-image-landscape", [b"character"])
        await self.run_model("omni-1.2-flash-i2v-4s-landscape", [b"character", b"scene-two"])
        self.assertEqual([b"character", b"scene-two"], self.uploaded)

    async def test_the_request_log_says_what_was_reused_and_how_long_it_took(self):
        await self.run_model("omni-1.2-flash-i2v-4s-landscape", [b"start"])
        await self.run_model("omni-1.2-flash-i2v-4s-landscape", [b"start"])
        item = self.logged_trace()["upload_cache"]["used"][0]
        self.assertTrue(item["reused"])
        self.assertLess(item["ms"], 1000)

    async def test_a_media_id_flow_rejects_is_replaced_and_the_request_retried_once(self):
        await self.run_model("omni-1.2-flash-i2v-4s-landscape", [b"start"])            # caches media-1
        self.submits.clear()
        self.failures = [STALE]                                                         # Flow no longer has media-1
        await self.run_model("omni-1.2-flash-i2v-4s-landscape", [b"start"])
        self.assertEqual(2, len(self.submits), "one retry, not a loop")
        self.assertEqual("media-1", self.submits[0][1]["start_media_id"])
        self.assertEqual("media-2", self.submits[1][1]["start_media_id"], "the retry uploaded the image again")
        self.assertEqual(2, len(self.uploaded))
        self.assertEqual("media-2", self.handler.flow_client.generate_video_start_image.await_args.kwargs["start_media_id"])
        await self.run_model("omni-1.2-flash-i2v-4s-landscape", [b"start"])            # the fresh id is what is cached now
        self.assertEqual(2, len(self.uploaded))

    async def test_an_error_that_does_not_involve_the_cache_is_not_retried_as_stale(self):
        await self.run_model("omni-1.2-flash-i2v-4s-landscape", [b"start"])
        self.submits.clear()
        self.failures = ["Flow frontend RPC rejected: rpc=eb1hJf, error=PUBLIC_ERROR_AUDIO_FILTERED"]
        await self.run_model("omni-1.2-flash-i2v-4s-landscape", [b"start"])
        self.assertEqual(1, len(self.submits))
        self.assertEqual(1, len(self.uploaded))

    async def test_a_stale_error_after_a_fresh_upload_is_reported_not_looped(self):
        self.failures = [STALE, STALE, STALE]
        chunks = await self.run_model("omni-1.2-flash-i2v-4s-landscape", [b"start"])
        self.assertEqual(1, len(self.submits), "nothing was taken from the cache, so nothing to retry")
        self.assertIn("code=[5]", chunks[-1])


if __name__ == "__main__":
    unittest.main()
