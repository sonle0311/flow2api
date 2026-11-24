"""Omni 1.2 extend/edit: request layouts, source lookups and project ownership.

The layouts were captured from the Flow web app on 2026-11-24 and confirmed by real sends
(docs/flow-omni-edit-extend-protocol.md); nothing here talks to Flow.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from src.core.database import Database
from src.services.flow_client import FlowClient
from src.services.video_sources import VideoSourceStore, parse_source

PROJECT = "11111111-1111-4111-8111-111111111111"
MEDIA = "22222222-2222-4222-8222-222222222222"
GENERATING_OP = "33333333-3333-4333-8333-333333333333"
CURRENT_OP = "44444444-4444-4444-8444-444444444444"


class ParseSourceTests(unittest.TestCase):
    def test_plain_id_and_project_suffix(self):
        self.assertEqual(parse_source(MEDIA), (MEDIA, None))
        self.assertEqual(parse_source(f" {MEDIA}?project={PROJECT} "), (MEDIA, PROJECT))
        self.assertEqual(parse_source(f"{MEDIA}?other=1"), (MEDIA, None))
        self.assertEqual(parse_source(None), ("", None))


class VideoSourceStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_video_is_traced_back_to_its_project(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / "flow.db"))
            await db.init_db()
            store = VideoSourceStore(db)
            self.assertIsNone(await store.project_of(MEDIA))
            await store.record(MEDIA, PROJECT, 4)
            self.assertEqual(await store.project_of(MEDIA), PROJECT)
            await store.record(MEDIA, "other-project", 4)  # a later result replaces the mapping
            self.assertEqual(await store.project_of(MEDIA), "other-project")
            await store.record("", PROJECT, 4)  # nothing to remember without an ID
            self.assertIsNone(await store.project_of(""))


class RequestLayoutTests(unittest.TestCase):
    def _argument(self, mode, **extra):
        rpc, argument = FlowClient(None)._build_frontend_video_generation_argument(
            project_id=PROJECT,
            prompt="make it orange",
            model_key="macaron_cookie_edit" if mode == "edit" else "macaron_cookie_extend_4s",
            aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE",
            recaptcha_token="token",
            session_id=";1700000000000",
            mode=mode,
            video_media_id=MEDIA,
            source_operation_id=CURRENT_OP,
            source_seconds=8,
            **extra,
        )
        return rpc, argument

    def test_extend_header_names_the_current_operation_and_length_in_frames(self):
        rpc, argument = self._argument("extend")
        item = argument[0][0]
        header, prompt, model_key, _aspect, _gap, source = item[:6]
        self.assertEqual(rpc, "fZytfe")
        self.assertEqual(header, [None, CURRENT_OP, 0, 8 * 24])
        self.assertEqual(prompt[2][0][0][0], "make it orange")
        self.assertEqual(model_key, "macaron_cookie_extend_4s")
        self.assertEqual(source[1], MEDIA)

    def test_edit_header_also_carries_the_source_seconds(self):
        rpc, argument = self._argument("edit")
        item = argument[0][0]
        header, _prompt, model_key, _aspect, source = item[:5]
        self.assertEqual(rpc, "jIps6")
        self.assertEqual(header, [None, CURRENT_OP, 0, 8 * 24, None, [], [8]])
        self.assertEqual(model_key, "macaron_cookie_edit")
        self.assertEqual(source[1], MEDIA)

    def test_missing_source_state_is_refused_instead_of_guessed(self):
        with self.assertRaises(ValueError):
            FlowClient(None)._build_frontend_video_generation_argument(
                project_id=PROJECT, prompt="x", model_key="macaron_cookie_edit",
                aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE", recaptcha_token="t", session_id="s",
                mode="edit", video_media_id=MEDIA,
            )


def _listing(media, operation):
    return [[[media, None, None, ["Title", [1795463080, 0], None, None, operation, "UPPER-ID", [1, 0]], PROJECT]]]


class SourceStateTests(unittest.IsolatedAsyncioTestCase):
    def _client(self, handler):
        client = FlowClient(None)
        client._current_rpc = AsyncMock(side_effect=lambda **kwargs: handler(kwargs))
        return client

    async def test_id_returned_by_this_server_is_resolved_to_flows_media_id(self):
        def handler(call):
            if call["rpc_id"] == "Zzl0ze":
                return _listing(MEDIA, CURRENT_OP)
            if call["argument"] == [GENERATING_OP]:  # a result ID is the generating operation
                return [GENERATING_OP, PROJECT, MEDIA, [None, None, [4]]]
            if call["argument"] == [CURRENT_OP]:
                return [CURRENT_OP, PROJECT, MEDIA, [None, None, [8]]]
            raise AssertionError(call)

        state = await self._client(handler).get_source_state(GENERATING_OP, PROJECT)
        self.assertEqual(state, (MEDIA, CURRENT_OP, 8))

    async def test_flows_own_media_id_is_accepted_when_it_is_not_an_operation(self):
        def handler(call):
            if call["rpc_id"] == "Zzl0ze":
                return _listing(MEDIA, CURRENT_OP)
            if call["argument"] == [MEDIA]:
                raise RuntimeError("Flow frontend RPC rejected: rpc=as29s, code=[5]")
            return [CURRENT_OP, PROJECT, MEDIA, [None, None, [12]]]

        state = await self._client(handler).get_source_state(MEDIA, PROJECT)
        self.assertEqual(state, (MEDIA, CURRENT_OP, 12))

    async def test_other_lookup_errors_are_not_mistaken_for_a_media_id(self):
        def handler(call):
            raise RuntimeError("Flow frontend RPC rejected: rpc=as29s, error=PUBLIC_ERROR_UNUSUAL_ACTIVITY")

        with self.assertRaisesRegex(RuntimeError, "UNUSUAL_ACTIVITY"):
            await self._client(handler).get_source_state(MEDIA, PROJECT)

    async def test_video_missing_from_the_project_is_reported(self):
        def handler(call):
            if call["rpc_id"] == "Zzl0ze":
                return _listing("55555555-5555-4555-8555-555555555555", CURRENT_OP)
            raise RuntimeError("rpc=as29s, code=[5]")

        with self.assertRaisesRegex(RuntimeError, "no video"):
            await self._client(handler).get_source_state(MEDIA, PROJECT)


if __name__ == "__main__":
    unittest.main()
