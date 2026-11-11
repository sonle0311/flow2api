"""Local media cache references must stay inside the generated-file directory."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from src.api import routes
from src.core.config import config


@pytest.fixture
def cache(tmp_path):
    directory = tmp_path / "media"
    directory.mkdir()
    handler = SimpleNamespace(file_cache=SimpleNamespace(cache_dir=directory))
    with patch.object(routes, "generation_handler", handler):
        yield directory


@pytest.mark.asyncio
@pytest.mark.parametrize("uri", ["/tmp/../private.png", "/tmp/%2e%2e/private.png", "file:///tmp/../private.png"])
async def test_cache_reference_cannot_read_parent_file(cache, uri):
    (cache.parent / "private.png").write_bytes(b"synthetic-private-file")
    with patch.object(routes, "AsyncSession") as session:
        assert await routes.retrieve_image_data(uri) is None
        session.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "http://localhost:38000"])
async def test_cache_symlink_cannot_escape_directory(cache, prefix):
    outside = cache.parent / "private.png"
    outside.write_bytes(b"synthetic-private-file")
    link = cache / ("a" * 32 + ".png")
    native_resolve = Path.resolve
    try:
        link.symlink_to(outside)
    except OSError:
        # Windows may deny symlink creation. Exercise the same resolved-path
        # boundary without requiring elevation or changing machine settings.
        link.write_bytes(b"synthetic-private-file")

    def resolve(path, *args, **kwargs):
        return outside if path == link else native_resolve(path, *args, **kwargs)

    with patch.object(Path, "resolve", autospec=True, side_effect=resolve), patch.object(routes, "AsyncSession") as session:
        assert await routes.retrieve_image_data(
            prefix + "/tmp/" + link.name, request_base_url="http://localhost:38000"
        ) is None
        session.assert_not_called()


@pytest.mark.asyncio
async def test_generated_cache_file_remains_readable(cache):
    name = "b" * 32 + "_4K.jpg"
    (cache / name).write_bytes(b"synthetic-image")
    assert await routes.retrieve_image_data("/tmp/" + name) == b"synthetic-image"


@pytest.mark.asyncio
async def test_remote_tmp_url_does_not_alias_an_unrelated_local_cache_file(cache):
    name = "c" * 32 + ".png"
    (cache / name).write_bytes(b"local-image")
    client = AsyncMock()
    client.get.return_value = SimpleNamespace(status_code=200, content=b"remote-image")
    with patch.object(routes, "AsyncSession") as session:
        session.return_value.__aenter__.return_value = client
        assert await routes.retrieve_image_data("https://images.example/tmp/" + name) == b"remote-image"
        client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_configured_public_cache_url_remains_a_local_reference(cache):
    name = "d" * 32 + ".jpg"
    (cache / name).write_bytes(b"configured-cache-image")
    with patch.dict(config._config.setdefault("cache", {}), {"base_url": "https://cache.example/prefix"}):
        with patch.object(routes, "AsyncSession") as session:
            assert await routes.retrieve_image_data("https://cache.example/prefix/tmp/" + name) == b"configured-cache-image"
            session.assert_not_called()


@pytest.mark.asyncio
async def test_gemini_generated_output_uses_its_own_cached_image(cache):
    name = "e" * 32 + ".png"
    (cache / name).write_bytes(b"synthetic-generated-image")
    with patch.object(routes, "AsyncSession") as session:
        parts = await routes._build_image_parts_from_uri("https://service.example/tmp/" + name)
        assert parts[0]["inlineData"]["mimeType"] == "image/png"
        session.assert_not_called()


@pytest.mark.asyncio
async def test_non_media_file_in_cache_is_not_read(cache):
    (cache / "settings.toml").write_bytes(b"synthetic-settings")
    with patch.object(routes, "AsyncSession") as session:
        assert await routes.retrieve_image_data("/tmp/settings.toml") is None
        session.assert_not_called()


@pytest.mark.asyncio
async def test_ordinary_remote_image_still_uses_http(cache):
    client = AsyncMock()
    client.get.return_value = SimpleNamespace(status_code=200, content=b"remote-image")
    with patch.object(routes, "AsyncSession") as session:
        session.return_value.__aenter__.return_value = client
        assert await routes.retrieve_image_data("https://images.example/photo.png") == b"remote-image"
        client.get.assert_awaited_once()


def request_for(host, *, scheme="http", extra_headers=()):
    return Request({
        "type": "http", "method": "POST", "scheme": scheme,
        "path": "/v1/chat/completions", "query_string": b"",
        "headers": [(b"host", host.encode("ascii")), *extra_headers],
        "server": ("127.0.0.1", 8000), "client": ("192.0.2.10", 12345),
    })


def test_public_base_uses_host_and_trusted_asgi_scheme():
    request = request_for("service.example:8443", scheme="https", extra_headers=[
        (b"x-forwarded-host", b"untrusted.example"),
        (b"x-forwarded-proto", b"http"),
    ])
    assert routes._get_request_base_url(request) == "https://service.example:8443"


@pytest.mark.parametrize("host", ["service.example/path", "service.example#fragment", "user@service.example", "service.example\\path", "service.example:invalid"])
def test_malformed_public_authority_is_rejected(host):
    with pytest.raises(HTTPException) as error:
        routes._get_request_base_url(request_for(host))
    assert error.value.status_code == 400


def test_ipv6_public_base_is_supported():
    assert routes._get_request_base_url(request_for("[::1]:8000")) == "http://[::1]:8000"


def cache_reuse_payload(case, uri):
    model = "gemini-3.1-flash-image"
    content = [{"role": "user", "parts": [
        {"text": "Edit this cached image"},
        {"fileData": {"mimeType": "image/png", "fileUri": uri}},
    ]}]
    if case.startswith("gemini"):
        suffix = "streamGenerateContent" if case.endswith("stream") else "generateContent"
        return f"/v1beta/models/{model}:{suffix}", {"contents": content}
    if case == "openai_contents":
        return "/v1/chat/completions", {"model": model, "contents": content}
    messages = [{"role": "user", "content": "Edit this cached image"}]
    body = {"model": model, "messages": messages}
    if case == "openai_history":
        messages.insert(0, {"role": "assistant", "content": f"![result]({uri})"})
    elif case == "openai_image":
        body["image"] = uri
    else:
        messages[0]["content"] = [
            {"type": "text", "text": "Edit this cached image"},
            {"type": "image_url", "image_url": {"url": uri}},
        ]
    if case == "openai_stream":
        body["stream"] = True
    return "/v1/chat/completions", body


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "openai_message", "openai_image", "openai_history", "openai_contents",
    "openai_stream", "gemini_generate", "gemini_stream",
])
async def test_endpoints_reuse_request_origin_cache_without_http(cache, case):
    """The public Docker port need not be reachable from inside the container."""
    name = "f" * 32 + ".png"
    image = b"synthetic-cached-image"
    (cache / name).write_bytes(image)
    endpoint, body = cache_reuse_payload(case, "http://localhost:38000/tmp/" + name)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.verify_api_key_flexible] = lambda: "synthetic-key"
    normalized_images = []

    async def collect(model, prompt, images, **kwargs):
        normalized_images.append(images)
        return json.dumps({"choices": [{"message": {"content": "synthetic-result"}}]})

    async def stream(normalized, *args):
        normalized_images.append(normalized.images)
        yield "data: [DONE]\n\n"

    remote = AsyncMock()
    remote.get.return_value = SimpleNamespace(status_code=503, content=b"")
    with patch.dict(config._config.setdefault("cache", {}), {"base_url": ""}), \
         patch.object(routes, "AsyncSession") as session, \
         patch.object(routes, "_collect_non_stream_result", collect), \
         patch.object(routes, "_iterate_openai_stream", stream), \
         patch.object(routes, "_iterate_gemini_stream", stream):
        session.return_value.__aenter__.return_value = remote
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:38000") as client:
            response = await client.post(endpoint, json=body)
        assert response.status_code == 200, response.text
        assert normalized_images == [[image]]
        session.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("origin,prefix", [
    ("https://other.example", "/tmp/"),
    ("https://localhost:38000", "/tmp/"),
    ("http://localhost:8000", "/tmp/"),
    ("http://localhost:38000", "/other/tmp/"),
    ("http://localhost:38000@other.example", "/tmp/"),
])
async def test_request_cache_fallback_does_not_alias_other_urls(cache, origin, prefix):
    name = "a" * 32 + ".jpg"
    (cache / name).write_bytes(b"local-image")
    remote = AsyncMock()
    remote.get.return_value = SimpleNamespace(status_code=200, content=b"remote-image")
    with patch.dict(config._config.setdefault("cache", {}), {"base_url": ""}), \
         patch.object(routes, "AsyncSession") as session:
        session.return_value.__aenter__.return_value = remote
        assert await routes.retrieve_image_data(
            origin + prefix + name, request_base_url="http://localhost:38000"
        ) == b"remote-image"
        remote.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_configured_cache_root_takes_precedence_over_request_origin(cache):
    name = "b" * 32 + ".png"
    (cache / name).write_bytes(b"configured-cache-image")
    remote = AsyncMock()
    remote.get.return_value = SimpleNamespace(status_code=200, content=b"remote-image")
    with patch.dict(config._config.setdefault("cache", {}), {"base_url": "https://cache.example/prefix"}), \
         patch.object(routes, "AsyncSession") as session:
        session.return_value.__aenter__.return_value = remote
        assert await routes.retrieve_image_data(
            "https://cache.example/prefix/tmp/" + name,
            request_base_url="http://localhost:38000",
        ) == b"configured-cache-image"
        session.assert_not_called()
        assert await routes.retrieve_image_data(
            "http://localhost:38000/tmp/" + name,
            request_base_url="http://localhost:38000",
        ) == b"remote-image"
        remote.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_requests_keep_cache_origins_isolated(cache):
    name = "c" * 32 + ".png"
    (cache / name).write_bytes(b"first-origin-cache")
    uri = "https://first.example/tmp/" + name
    remote = AsyncMock()
    remote.get.return_value = SimpleNamespace(status_code=200, content=b"remote-image")
    with patch.dict(config._config.setdefault("cache", {}), {"base_url": ""}), \
         patch.object(routes, "AsyncSession") as session:
        session.return_value.__aenter__.return_value = remote
        results = await asyncio.gather(
            routes.retrieve_image_data(uri, request_base_url="https://first.example"),
            routes.retrieve_image_data(uri, request_base_url="https://second.example"),
        )
        assert results == [b"first-origin-cache", b"remote-image"]
        remote.get.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/tmp/../", "/tmp/%2e%2e/", "/tmp/%5c", "/tmp/%00"])
async def test_request_origin_does_not_bypass_cache_path_validation(cache, path):
    name = "d" * 32 + ".png"
    (cache / name).write_bytes(b"local-image")
    with patch.dict(config._config.setdefault("cache", {}), {"base_url": ""}), \
         patch.object(routes, "AsyncSession") as session:
        assert await routes.retrieve_image_data(
            "http://localhost:38000" + path + name,
            request_base_url="http://localhost:38000",
        ) is None
        session.assert_not_called()
