"""The guide runtime must be served by the actual application, not just test fixtures."""

import asyncio
import json
import re
import subprocess
import shutil
from pathlib import Path

import httpx
import pytest

from src.main import app
from src.api import admin
from src.services.generation_handler import MODEL_CONFIG
from src.core.model_resolver import get_base_model_aliases
from src.core.models import ChatCompletionRequest, GeminiGenerateContentRequest


def test_integration_runtime_is_served_with_fresh_content():
    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            response = await client.get("/static/integration.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]
        assert "no-store" in response.headers["cache-control"]
        assert response.content == (Path(__file__).resolve().parents[1] / "static/integration.js").read_bytes()

    asyncio.run(check())


def test_complete_reference_requires_an_admin_session():
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
            response = await client.get("/api/integration/reference")
        assert response.status_code == 401
    asyncio.run(check())


def test_complete_reference_matches_routes_and_models_without_runtime_secrets(monkeypatch):
    from src.core.config import config
    monkeypatch.setitem(config._config["global"], "api_key", "PRIVATE-KEY-NOT-FOR-DOCS-72910")
    session = "admin-integration-reference-test"
    admin.active_admin_tokens.add(session)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
            response = await client.get("/api/integration/reference", headers={"Authorization": f"Bearer {session}"})
        assert response.status_code == 200
        reference = response.json()
        documented = {(endpoint["method"], endpoint["path"]) for endpoint in reference["endpoints"]}
        for route in app.routes:
            for method in getattr(route, "methods", ()) or ():
                assert (method, route.path) in documented
        assert ("WEBSOCKET", "/captcha_ws") in documented
        assert ("MOUNT", "/tmp") in documented
        assert {model["id"] for model in reference["models"]} == set(MODEL_CONFIG)
        assert {alias["id"] for alias in reference["aliases"]} == set(get_base_model_aliases())
        assert sum(model["listed"] for model in reference["models"]) == sum(c.get("listed", True) for c in MODEL_CONFIG.values())
        r2v = next(model for model in reference["models"] if model["id"] == "veo-3.1-fast-r2v-8s-landscape")
        assert r2v["min_images"] == 1
        assert r2v["locally_validated_min_images"] == 0
        assert "ChatCompletionRequest" in reference["schemas"]
        assert "PRIVATE-KEY-NOT-FOR-DOCS-72910" not in response.text
        assert session not in response.text
        endpoints = {(e["method"], e["path"]): e for e in reference["endpoints"]}
        assert all(endpoint["notes"].get("summary") and endpoint["notes"].get("details") for endpoint in reference["endpoints"])
        assert endpoints[("POST", "/v1/chat/completions")]["auth"] == "api_key"
        assert endpoints[("GET", "/api/tokens")]["auth"] == "admin_session"
        assert endpoints[("GET", "/health")]["auth"] == "public"
        assert "request_body" in endpoints[("POST", "/api/tokens")]
        assert endpoints[("POST", "/api/captcha/config")]["notes"]["body_example"]
    try:
        asyncio.run(check())
    finally:
        admin.active_admin_tokens.discard(session)


def test_documented_recipes_use_supported_models_and_valid_payloads():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed to validate generated JavaScript recipes")
    root = Path(__file__).resolve().parents[1]
    script = "global.window={};require('./static/integration-recipes.js');console.log(JSON.stringify(['en','vi','zh-CN'].map(locale=>window.Flow2APIIntegrationRecipes.build('https://example.com/flow',locale))))"
    guides = json.loads(subprocess.check_output([node, "-e", script], cwd=root, encoding="utf-8"))
    supported = set(MODEL_CONFIG) | set(get_base_model_aliases())
    for guide in guides:
        assert "https://example.com/flow" in guide
        for block in re.findall(r"```json\n(.*?)\n```", guide, re.S):
            payload = json.loads(block)
            if isinstance(payload, dict) and "model" in payload and "messages" in payload:
                ChatCompletionRequest.model_validate(payload)
                assert payload["model"] in supported
            elif isinstance(payload, dict) and "contents" in payload:
                GeminiGenerateContentRequest.model_validate(payload)
        for block in re.findall(r"```python\n(.*?)\n```", guide, re.S):
            compile(block, "integration-recipe", "exec")
        for block in re.findall(r"```javascript\n(.*?)\n```", guide, re.S):
            subprocess.run([node, "--check"], input=block, encoding="utf-8", check=True, capture_output=True)


def test_endpoint_body_examples_conform_to_declared_request_models():
    from src.core.integration_docs import ENDPOINT_NOTES
    for route in app.routes:
        for method in getattr(route, "methods", ()) or ():
            example = ENDPOINT_NOTES.get(f"{method} {route.path}", {}).get("body_example")
            if example is None:
                continue
            for parameter in getattr(getattr(route, "dependant", None), "body_params", ()):
                model = getattr(parameter, "type_", None)
                if hasattr(model, "model_validate"):
                    model.model_validate(example)


def test_desktop_reference_uses_admin_auth_for_the_page_and_websocket():
    from src.core.integration_reference import build_integration_reference
    endpoints = {(e["method"], e["path"]): e for e in build_integration_reference(app)["endpoints"]}
    assert endpoints[("GET", "/browser-desktop/")]["auth"] == "admin_session"
    assert endpoints[("WEBSOCKET", "/api/browser-desktop/ws")]["auth"] == "admin_session"
