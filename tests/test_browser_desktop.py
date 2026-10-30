import asyncio
from contextlib import asynccontextmanager
from importlib import import_module
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api import admin


SESSION = "desktop-test-session"
ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def desktop(monkeypatch):
    module = import_module("src.api.browser_desktop")
    monkeypatch.setenv("FLOW2API_DESKTOP_ENABLED", "true")
    admin.active_admin_tokens.add(SESSION)
    yield module
    admin.active_admin_tokens.discard(SESSION)


def app_for(module, lifespan=None):
    app = FastAPI(lifespan=lifespan)
    app.include_router(module.router)
    return app


def test_desktop_config_is_admin_only_and_exposes_no_internal_paths(desktop, monkeypatch):
    with TestClient(app_for(desktop)) as client:
        assert client.get("/api/browser-desktop/config").status_code == 401
        client.cookies.set("admin_session", SESSION)
        response = client.get("/api/browser-desktop/config")
        assert response.json() == {"success": True, "desktop": {"enabled": True, "url": "/browser-desktop/"}}
        assert "no-store" in response.headers["cache-control"]
        monkeypatch.delenv("FLOW2API_DESKTOP_ENABLED")
        response = client.get("/api/browser-desktop/config")
        assert response.json()["desktop"] == {"enabled": False, "url": None}


def test_desktop_page_redirects_to_login_and_requires_enabled_runtime(desktop, monkeypatch, tmp_path):
    html = tmp_path / "desktop.html"
    html.write_text("<!doctype html><title>Desktop fixture</title>")
    monkeypatch.setattr(desktop, "DESKTOP_PAGE", html)
    with TestClient(app_for(desktop)) as client:
        response = client.get("/browser-desktop/", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login"
        client.cookies.set("admin_session", SESSION)
        response = client.get("/browser-desktop/")
        assert response.status_code == 200 and "Desktop fixture" in response.text
        assert "no-store" in response.headers["cache-control"]
        assert response.headers.get("x-frame-options") == "SAMEORIGIN"
        monkeypatch.setenv("FLOW2API_DESKTOP_ENABLED", "false")
        assert client.get("/browser-desktop/").status_code == 503


def test_novnc_assets_require_auth_and_preserve_javascript_mime(desktop, monkeypatch, tmp_path):
    root = tmp_path / "novnc"
    (root / "core").mkdir(parents=True)
    (root / "core" / "rfb.js").write_text("export default class RFB {}")
    monkeypatch.setenv("FLOW2API_NOVNC_ROOT", str(root))
    with TestClient(app_for(desktop)) as client:
        assert client.get("/browser-desktop/assets/core/rfb.js").status_code == 401
        client.cookies.set("admin_session", SESSION)
        response = client.get("/browser-desktop/assets/core/rfb.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]
        assert "export default" in response.text
        assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("path", ["..%2fprivate.txt", "..%5cprivate.txt", "%2fetc/passwd", "core/%2e%2e/%2e%2e/private.txt"])
def test_asset_traversal_never_serves_outside_root(desktop, monkeypatch, tmp_path, path):
    root = tmp_path / "novnc"
    root.mkdir()
    (tmp_path / "private.txt").write_text("PRIVATE-FILE-MUST-NOT-BE-SERVED")
    monkeypatch.setenv("FLOW2API_NOVNC_ROOT", str(root))
    with TestClient(app_for(desktop), cookies={"admin_session": SESSION}) as client:
        response = client.get("/browser-desktop/assets/" + path)
        assert response.status_code == 404
        assert "PRIVATE-FILE" not in response.text


@pytest.mark.parametrize("headers,cookie,query", [
    (ORIGIN, None, ""),
    ({"Origin": "https://unrelated.example"}, SESSION, ""),
    ({}, SESSION, ""),
    ({"Origin": "null"}, SESSION, ""),
    ({"Origin": "http://testserver", "Authorization": f"Bearer {SESSION}"}, None, ""),
    (ORIGIN, None, "?token=" + SESSION),
])
def test_websocket_denies_untrusted_clients_before_any_tcp_connection(desktop, monkeypatch, headers, cookie, query):
    connect = AsyncMock()
    monkeypatch.setattr(desktop, "open_connection", connect)
    with TestClient(app_for(desktop)) as client:
        if cookie:
            client.cookies.set("admin_session", cookie)
        with pytest.raises(WebSocketDisconnect) as failure:
            with client.websocket_connect("/api/browser-desktop/ws" + query, headers=headers):
                pass
        assert failure.value.code == 1008
    connect.assert_not_awaited()


def test_disabled_desktop_denies_websocket_without_connecting(desktop, monkeypatch):
    monkeypatch.setenv("FLOW2API_DESKTOP_ENABLED", "false")
    connect = AsyncMock()
    monkeypatch.setattr(desktop, "open_connection", connect)
    with TestClient(app_for(desktop), cookies={"admin_session": SESSION}) as client:
        with pytest.raises(WebSocketDisconnect) as failure:
            with client.websocket_connect("/api/browser-desktop/ws", headers=ORIGIN):
                pass
        assert failure.value.code == 1013
    connect.assert_not_awaited()


def test_unavailable_vnc_has_sanitized_close_code(desktop, monkeypatch):
    connect = AsyncMock(side_effect=OSError("PRIVATE INTERNAL PATH AND PASSWORD"))
    monkeypatch.setattr(desktop, "open_connection", connect)
    with TestClient(app_for(desktop), cookies={"admin_session": SESSION}) as client:
        with pytest.raises(WebSocketDisconnect) as failure:
            with client.websocket_connect("/api/browser-desktop/ws", headers=ORIGIN):
                pass
        assert failure.value.code == 1013
        assert not failure.value.reason
    connect.assert_awaited_once_with("127.0.0.1", 5900)


def fake_vnc_app(desktop, monkeypatch):
    state = {"connections": 0, "received": [], "closed": False}

    @asynccontextmanager
    async def lifespan(app):
        async def serve(reader, writer):
            state["connections"] += 1
            try:
                writer.write(b"RFB 003.008\n")
                await writer.drain()
                while data := await reader.read(65536):
                    state["received"].append(data)
                    writer.write(b"ACK:" + data)
                    await writer.drain()
            finally:
                state["closed"] = True
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        monkeypatch.setattr(desktop, "RFB_PORT", server.sockets[0].getsockname()[1])
        yield
        server.close()
        await server.wait_closed()

    return app_for(desktop, lifespan), state


def test_binary_websocket_relay_exchanges_real_tcp_bytes_and_closes_connection(desktop, monkeypatch):
    app, state = fake_vnc_app(desktop, monkeypatch)
    with TestClient(app, cookies={"admin_session": SESSION}) as client:
        with client.websocket_connect("/api/browser-desktop/ws", headers=ORIGIN, subprotocols=["binary"]) as socket:
            assert socket.accepted_subprotocol == "binary"
            assert socket.receive_bytes() == b"RFB 003.008\n"
            socket.send_bytes(b"user-key-event")
            assert socket.receive_bytes() == b"ACK:user-key-event"
        assert state["connections"] == 1
        assert state["received"] == [b"user-key-event"]
    assert state["closed"]


def test_text_websocket_messages_are_rejected(desktop, monkeypatch):
    app, state = fake_vnc_app(desktop, monkeypatch)
    with TestClient(app, cookies={"admin_session": SESSION}) as client:
        with client.websocket_connect("/api/browser-desktop/ws", headers=ORIGIN) as socket:
            assert socket.receive_bytes().startswith(b"RFB")
            socket.send_text("not-binary")
            with pytest.raises(WebSocketDisconnect) as failure:
                socket.receive_bytes()
            assert failure.value.code == 1003
    assert state["received"] == []


def test_idle_viewer_disconnects_after_admin_session_is_invalidated(desktop, monkeypatch):
    monkeypatch.setattr(desktop, "SESSION_CHECK_SECONDS", 0.01)
    app, state = fake_vnc_app(desktop, monkeypatch)
    with TestClient(app, cookies={"admin_session": SESSION}) as client:
        with client.websocket_connect("/api/browser-desktop/ws", headers=ORIGIN) as socket:
            assert socket.receive_bytes().startswith(b"RFB")
            admin.active_admin_tokens.discard(SESSION)
            with pytest.raises(WebSocketDisconnect) as failure:
                socket.receive_bytes()
            assert failure.value.code == 1008
    assert state["closed"]
