"""A polled operation that Flow keeps answering "not found" for must not hold a slot until the timeout."""

import unittest
from unittest.mock import AsyncMock

from src.services.flow_client import FlowClient

PROJECT = "11111111-1111-4111-8111-111111111111"
MEDIA = "22222222-2222-4222-8222-222222222222"
OPERATION = "33333333-3333-4333-8333-333333333333"


def _client(get_media):
    client = FlowClient(None)
    client._current_rpc = AsyncMock(return_value=[None, None, [[OPERATION, PROJECT, MEDIA, None, None, [[1, 0], "x"]]]])
    client.get_media = get_media
    client._poll_not_found = {}
    return client


def _operations():
    return [{"name": OPERATION, "projectId": PROJECT, "operation": {"name": OPERATION}}]


class PollFailFastTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_not_found_ends_the_wait_with_a_clear_error(self):
        client = _client(AsyncMock(side_effect=RuntimeError("Flow frontend RPC rejected: rpc=as29s, code=[5]")))
        statuses = []
        for _ in range(FlowClient.POLL_NOT_FOUND_LIMIT):
            result = await client.check_video_status("at", _operations())
            statuses.append(result["operations"][0]["status"])
        self.assertEqual(["MEDIA_GENERATION_STATUS_ACTIVE"] * (FlowClient.POLL_NOT_FOUND_LIMIT - 1)
                         + ["MEDIA_GENERATION_STATUS_FAILED"], statuses)
        error = result["operations"][0]["operation"]["error"]
        self.assertEqual("OPERATION_NOT_FOUND", error["code"])
        self.assertIn(OPERATION, error["message"])
        self.assertEqual({}, client._poll_not_found)

    async def test_other_errors_and_recovery_never_trigger_it(self):
        client = _client(AsyncMock(side_effect=RuntimeError("timeout")))
        for _ in range(FlowClient.POLL_NOT_FOUND_LIMIT * 2):
            result = await client.check_video_status("at", _operations())
            self.assertEqual("MEDIA_GENERATION_STATUS_ACTIVE", result["operations"][0]["status"])

        outcomes = [RuntimeError("code=[5]")] * (FlowClient.POLL_NOT_FOUND_LIMIT - 1) + [{"video": {}}]
        client = _client(AsyncMock(side_effect=outcomes))
        for _ in outcomes:
            result = await client.check_video_status("at", _operations())
        self.assertEqual("MEDIA_GENERATION_STATUS_ACTIVE", result["operations"][0]["status"])
        self.assertEqual({}, client._poll_not_found)  # a found operation resets the count
        client.get_media = AsyncMock(side_effect=RuntimeError("code=[5]"))
        result = await client.check_video_status("at", _operations())
        self.assertEqual("MEDIA_GENERATION_STATUS_ACTIVE", result["operations"][0]["status"])


if __name__ == "__main__":
    unittest.main()
