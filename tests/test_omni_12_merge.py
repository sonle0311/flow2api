"""Verify the new model transport and local error policy together after merging."""

import json
import unittest
from unittest.mock import AsyncMock, patch

from src.core.integration_reference import build_integration_reference
from src.api.routes import _get_openai_model_catalog
from src.main import app
from src.services.flow_client import FlowClient
from src.services.generation_handler import MODEL_CONFIG
from tests.test_token_quota_failover import _build_handler, _collect, _token


class Omni12TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = FlowClient(proxy_manager=None)
        self.client._acquire_video_launch_gate = AsyncMock(return_value=(True, None, None))
        self.client._release_video_launch_gate = AsyncMock()
        self.client._get_recaptcha_token = AsyncMock(return_value=("test-captcha", "browser-1"))
        self.client._notify_browser_captcha_request_finished = AsyncMock()
        self.client._call_flow_frontend_rpc = AsyncMock(return_value=[[
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
            "33333333-3333-3333-3333-333333333333",
        ]])

    async def test_omni_12_text_request_uses_macaron_key(self):
        model = MODEL_CONFIG["omni-1.2-flash-8s-landscape"]
        result = await self.client.generate_video_text(
            at="test-at", project_id="22222222-2222-2222-2222-222222222222",
            prompt="A calm beach at sunset", model_key=model["model_key"],
            aspect_ratio=model["aspect_ratio"], google_cookies="SID=test-cookie",
        )
        rpc = self.client._call_flow_frontend_rpc.await_args.kwargs
        self.assertEqual(rpc["rpc_id"], "YhhmEf")
        self.assertEqual(rpc["argument"][0][0][1], "macaron_cookie_t2v_8s")
        self.assertTrue(result["operations"])

    async def test_omni_12_reference_request_keeps_15s_portrait_and_images(self):
        model = MODEL_CONFIG["omni-1.2-flash-15s-portrait"]
        await self.client.generate_video_reference_images(
            at="test-at", project_id="22222222-2222-2222-2222-222222222222",
            prompt="The reference character walks through a garden",
            model_key=model["reference_model_key"], aspect_ratio=model["aspect_ratio"],
            reference_images=[{"mediaId": "reference-image", "imageUsageType": "IMAGE_USAGE_TYPE_ASSET"}],
            google_cookies="SID=test-cookie",
        )
        rpc = self.client._call_flow_frontend_rpc.await_args.kwargs
        request = rpc["argument"][0][0]
        self.assertEqual(rpc["rpc_id"], "MZZa6b")
        self.assertEqual(request[1], [[None, "reference-image"]])
        self.assertEqual(request[2], "macaron_cookie_r2v_15s")
        self.assertEqual(request[3], 1)


class LocalAccountErrorPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_returned_content_filters_do_not_ban_or_fail_over_accounts(self):
        for code in (
            "PUBLIC_ERROR_DANGER_FILTER", "PUBLIC_ERROR_MINOR",
            "PUBLIC_ERROR_AUDIO_FILTERED", "PUBLIC_ERROR_SEXUAL",
        ):
            with self.subTest(code=code):
                handler, attempted = _build_handler([_token(1), _token(2)], set())

                async def blocked_video(token, *args, generation_result=None, **kwargs):
                    attempted.append(token.id)
                    handler._mark_generation_failed(generation_result, code)
                    yield handler._create_error_response(code, status_code=502)

                handler._handle_video_generation = blocked_video
                with patch("src.services.load_balancer.random.random", side_effect=[0.1, 0.9]):
                    chunks = await _collect(handler)
                self.assertEqual(attempted, [1])
                self.assertIn(code, json.loads(chunks[-1])["error"]["message"])
                handler.token_manager.record_error.assert_not_awaited()
                handler.token_manager.record_usage.assert_not_awaited()

    async def test_real_account_failures_still_count(self):
        handler, _ = _build_handler(
            [_token(1)], set(), errors_by_token={1: "HTTP 401 Unauthorized"},
        )
        await _collect(handler)
        handler.token_manager.record_error.assert_awaited_once_with(1)


def test_complete_integration_reference_keeps_local_features_and_adds_omni_12():
    reference = build_integration_reference(app)
    models = {model["id"]: model for model in reference["models"]}
    assert models["omni-1.2-flash-15s-portrait"]["duration_seconds"] == 15
    assert models["omni-1.2-flash-15s-portrait"]["max_images"] == 3
    assert "omni-1.2-flash-15s-landscape" not in models
    assert "omni-1.1-flash-8s-landscape" in models
    endpoints = {(entry["method"], entry["path"]) for entry in reference["endpoints"]}
    assert ("POST", "/api/browser-sessions/accounts") in endpoints
    assert ("GET", "/api/tokens/{token_id}/browser-session") in endpoints
    assert ("GET", "/api/browser-desktop/config") in endpoints


def test_public_catalog_preserves_previous_models_and_lists_all_omni_12_variants():
    listed = {model["id"] for model in _get_openai_model_catalog()}
    expected = {"omni-1.2-flash"}
    expected.update(
        f"omni-1.2-flash-{seconds}s-{orientation}"
        for seconds in range(3, 11) for orientation in ("landscape", "portrait")
    )
    expected.update(f"omni-1.2-flash-{seconds}s-portrait" for seconds in range(11, 16))
    assert {model for model in listed if model.startswith("omni-1.2-")} == expected
    assert len(listed - expected) == 82
    assert len(expected) == 22
