"""The Instrument UI must load locally without widening frontend access."""
import asyncio
from pathlib import Path

import httpx
import pytest

from src.main import app


@pytest.mark.parametrize("name, media_type", [
    ("instrument.css", "text/css"),
    ("instrument-utilities.css", "text/css"),
    ("instrument-shell.js", "application/javascript"),
    ("instrument-access.css", "text/css"),
])
def test_instrument_assets_are_current_local_files(name, media_type):
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
            response = await client.get("/static/" + name)
        assert response.status_code == 200
        assert media_type in response.headers["content-type"]
        assert "no-store" in response.headers["cache-control"]
        assert response.content == (Path(__file__).resolve().parents[1] / "static" / name).read_bytes()
    asyncio.run(check())


@pytest.mark.parametrize("name", ["be-vietnam-pro-regular.ttf", "be-vietnam-pro-semibold.ttf"])
def test_instrument_fonts_are_local_and_served_as_fonts(name):
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
            response = await client.get("/static/fonts/" + name)
        assert response.status_code == 200
        assert "font/ttf" in response.headers["content-type"]
        assert response.content == (Path(__file__).resolve().parents[1] / "static/fonts" / name).read_bytes()
    asyncio.run(check())


@pytest.mark.parametrize("path", [
    "/static/manage.html", "/static/test.html", "/static/browser-desktop.html",
    "/static/../config/setting.toml", "/static/%2e%2e%2fconfig%2fsetting.toml",
    "/static/fonts/%2e%2e%2finstrument.css", "/static/fonts/unknown.ttf",
    "/static/unknown.js",
])
def test_instrument_asset_routes_do_not_expose_other_files(path):
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
            response = await client.get(path)
        assert response.status_code == 404
    asyncio.run(check())


@pytest.mark.parametrize("page", ["login", "manage", "test", "browser-desktop"])
def test_production_pages_do_not_depend_on_tailwind_cdn(page):
    source = (Path(__file__).resolve().parents[1] / "static" / (page + ".html")).read_text(encoding="utf-8")
    assert "cdn.tailwindcss.com" not in source
    assert "/static/instrument.css" in source
