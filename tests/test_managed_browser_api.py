import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.api import admin
from src.main import app


ROOT = "/api/tokens/42/browser-session"
STATUS = {
    "token_id": 42, "enabled": True, "status": "ready", "browser_open": False,
    "last_sync_at": "2026-10-27T10:00:00+00:00", "error_code": None, "interval_minutes": 30,
}


@pytest.mark.parametrize("method,suffix", [("GET", ""), ("POST", "/login"), ("POST", "/sync"), ("POST", "/stop")])
def test_browser_actions_require_admin(method, suffix):
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost") as client:
            response = await client.request(method, ROOT + suffix)
        assert response.status_code == 401
    asyncio.run(check())


@pytest.mark.parametrize("method,suffix,action", [("GET", "", "get_status"), ("POST", "/login", "start_login"), ("POST", "/sync", "sync"), ("POST", "/stop", "stop")])
def test_browser_actions_use_service_and_never_expose_credentials(monkeypatch, method, suffix, action):
    service = SimpleNamespace(**{name: AsyncMock(return_value={**STATUS, "google_cookies": "secret", "profile_path": "private"}) for name in ("get_status", "start_login", "sync", "stop")})
    monkeypatch.setattr(app.state, "managed_browser", service, raising=False)
    monkeypatch.setattr(admin, "db", SimpleNamespace(get_token=AsyncMock(return_value=object())))
    admin.active_admin_tokens.add("managed-api-test")
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost", cookies={"admin_session": "managed-api-test"}) as client:
            response = await client.request(method, ROOT + suffix)
        assert response.status_code == 200, response.text
        assert response.json() == {"success": True, "session": STATUS}
        assert "no-store" in response.headers["cache-control"]
        getattr(service, action).assert_awaited_once_with(42)
        for name in ("get_status", "start_login", "sync", "stop"):
            if name != action:
                getattr(service, name).assert_not_awaited()
    try:
        asyncio.run(check())
    finally:
        admin.active_admin_tokens.discard("managed-api-test")


def test_missing_account_returns_404_without_opening_browser(monkeypatch):
    service = SimpleNamespace(start_login=AsyncMock())
    monkeypatch.setattr(app.state, "managed_browser", service, raising=False)
    monkeypatch.setattr(admin, "db", SimpleNamespace(get_token=AsyncMock(return_value=None)))
    admin.active_admin_tokens.add("managed-api-test")
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost", headers={"Authorization": "Bearer managed-api-test"}) as client:
            response = await client.post(ROOT + "/login")
        assert response.status_code == 404
        service.start_login.assert_not_awaited()
    try:
        asyncio.run(check())
    finally:
        admin.active_admin_tokens.discard("managed-api-test")


def test_managed_browser_script_is_served_without_caching():
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost") as client:
            response = await client.get("/static/managed-browser.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]
        assert "no-store" in response.headers["cache-control"]
        assert response.content == (Path(__file__).resolve().parents[1] / "static/managed-browser.js").read_bytes()
    asyncio.run(check())


def test_cross_origin_post_cannot_open_a_browser(monkeypatch):
    service = SimpleNamespace(start_login=AsyncMock())
    monkeypatch.setattr(app.state, "managed_browser", service, raising=False)
    admin.active_admin_tokens.add("managed-api-test")
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost", cookies={"admin_session": "managed-api-test"}) as client:
            response = await client.post(ROOT + "/login", headers={"Origin": "https://unrelated.example"})
        assert response.status_code == 403
        service.start_login.assert_not_awaited()
    try:
        asyncio.run(check())
    finally:
        admin.active_admin_tokens.discard("managed-api-test")
