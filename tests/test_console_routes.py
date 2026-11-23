"""The separate console is served locally, behind the admin session, from an allowlist."""
import asyncio
from pathlib import Path

import httpx
import pytest

from src.api import admin
from src.main import app

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "static" / "console"
SESSION = "console-route-test-session"
ASSETS = [
    ("console.css", "text/css"), ("studio.css", "text/css"),
    ("app.js", "application/javascript"), ("api.js", "application/javascript"),
    ("models.js", "application/javascript"), ("studio.js", "application/javascript"),
    ("request-preview.js", "application/javascript"), ("locales.json", "application/json"),
]


def get(path, *, session=False):
    async def run():
        cookies = {admin.ADMIN_SESSION_COOKIE_NAME: SESSION} if session else {}
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost", cookies=cookies) as client:
            return await client.get(path)
    return asyncio.run(run())


@pytest.fixture
def admin_session():
    admin.active_admin_tokens.add(SESSION)
    yield
    admin.active_admin_tokens.discard(SESSION)


def test_console_page_requires_an_admin_session():
    response = get("/console")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_console_page_is_served_fresh_to_an_admin(admin_session):
    response = get("/console", session=True)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "no-store" in response.headers["cache-control"]
    assert response.content == (CONSOLE / "index.html").read_bytes()


@pytest.mark.parametrize("name, media_type", ASSETS)
def test_console_assets_are_local_files_with_fixed_types(name, media_type):
    response = get("/static/console/" + name)
    assert response.status_code == 200
    assert media_type in response.headers["content-type"]
    assert "no-store" in response.headers["cache-control"]
    assert response.content == (CONSOLE / name).read_bytes()


@pytest.mark.parametrize("path", [
    "/static/console/index.html", "/static/console/unknown.js",
    "/static/console/..%2fmanage.html", "/static/console/%2e%2e%2f%2e%2e%2fconfig%2fsetting.toml",
    "/static/console/../../config/setting.toml",
])
def test_console_asset_route_exposes_nothing_else(path):
    assert get(path).status_code == 404


def test_every_console_file_is_on_the_allowlist():
    shipped = {item.name for item in CONSOLE.iterdir() if item.is_file()}
    assert shipped == {name for name, _ in ASSETS} | {"index.html"}


def test_existing_pages_keep_their_guard():
    for path in ("/manage", "/test"):
        assert get(path).status_code == 302
