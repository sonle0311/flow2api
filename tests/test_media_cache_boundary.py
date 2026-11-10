"""Local media cache references must stay inside the generated-file directory."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
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
async def test_cache_symlink_cannot_escape_directory(cache):
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
        assert await routes.retrieve_image_data("/tmp/" + link.name) is None
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
