"""Admin-session protected noVNC assets and a fixed local RFB bridge.

The VNC server is deliberately confined to container loopback. Browser clients
only reach it through this same-origin, authenticated WebSocket endpoint.
"""

import asyncio
import os
from asyncio import open_connection
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.websockets import WebSocketDisconnect

from . import admin


router = APIRouter()
DESKTOP_PAGE = Path(__file__).resolve().parents[2] / "static" / "browser-desktop.html"
RFB_HOST = "127.0.0.1"
RFB_PORT = 5900
SESSION_CHECK_SECONDS = 10
_NO_CACHE = {
    "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN"
}


def desktop_enabled() -> bool:
    return os.environ.get("FLOW2API_DESKTOP_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _require_enabled():
    if not desktop_enabled():
        raise HTTPException(status_code=503, detail="browser_desktop_disabled")


@router.get("/api/browser-desktop/config")
async def desktop_config(token: str = Depends(admin.verify_admin_token)):
    enabled = desktop_enabled()
    return JSONResponse(
        {"success": True, "desktop": {"enabled": enabled, "url": "/browser-desktop/" if enabled else None}},
        headers=_NO_CACHE,
    )


@router.get("/browser-desktop/", include_in_schema=False)
async def desktop_page(request: Request):
    if not admin.is_admin_session_token_valid(admin.get_admin_token_from_cookie(request)):
        return RedirectResponse("/login", status_code=302)
    _require_enabled()
    if not DESKTOP_PAGE.is_file():
        raise HTTPException(status_code=503, detail="browser_desktop_unavailable")
    return FileResponse(DESKTOP_PAGE, media_type="text/html", headers=_NO_CACHE)


@router.get("/browser-desktop/assets/{asset_path:path}", include_in_schema=False)
async def desktop_asset(asset_path: str, token: str = Depends(admin.verify_admin_token)):
    _require_enabled()
    path = PurePosixPath(asset_path)
    if not asset_path or "\\" in asset_path or "\x00" in asset_path or path.is_absolute() or ".." in path.parts:
        raise HTTPException(status_code=404, detail="Not found")
    root = Path(os.environ.get("FLOW2API_NOVNC_ROOT", "/usr/share/novnc")).resolve()
    target = (root / asset_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    mime = "application/javascript" if target.suffix in {".js", ".mjs"} else None
    return FileResponse(target, media_type=mime, headers=_NO_CACHE)


def _trusted_websocket_origin(socket: WebSocket) -> bool:
    try:
        origin = urlsplit(socket.headers.get("origin", ""))
        expected_scheme = {"ws": "http", "wss": "https"}.get(socket.url.scheme, socket.url.scheme)
        return origin.scheme == expected_scheme and origin.netloc == socket.url.netloc
    except ValueError:
        return False


@router.websocket("/api/browser-desktop/ws")
async def desktop_websocket(socket: WebSocket):
    session = admin.get_admin_token_from_cookie(socket)
    if not admin.is_admin_session_token_valid(session) or not _trusted_websocket_origin(socket) or socket.query_params:
        await socket.close(code=1008)
        return
    if not desktop_enabled():
        await socket.close(code=1013)
        return
    try:
        reader, writer = await asyncio.wait_for(open_connection(RFB_HOST, RFB_PORT), timeout=3)
    except (OSError, asyncio.TimeoutError):
        await socket.close(code=1013)
        return

    tasks = []
    accepted = False
    close_code = 1000
    try:
        # Recheck after connecting, since logout can race with TCP establishment.
        if not admin.is_admin_session_token_valid(session):
            await socket.close(code=1008)
            return
        protocols = socket.scope.get("subprotocols", ())
        await socket.accept(subprotocol="binary" if "binary" in protocols else None)
        accepted = True

        async def browser_to_vnc():
            while True:
                message = await socket.receive()
                if message["type"] == "websocket.disconnect":
                    return 1000
                if not admin.is_admin_session_token_valid(session):
                    return 1008
                data = message.get("bytes")
                if data is None:
                    return 1003
                writer.write(data)
                await writer.drain()

        async def vnc_to_browser():
            while True:
                data = await reader.read(65536)
                if not data:
                    return 1000
                if not admin.is_admin_session_token_valid(session):
                    return 1008
                await socket.send_bytes(data)

        async def monitor_session():
            while True:
                await asyncio.sleep(SESSION_CHECK_SECONDS)
                if not admin.is_admin_session_token_valid(session) or not desktop_enabled():
                    return 1008

        tasks = [asyncio.create_task(operation()) for operation in (browser_to_vnc, vnc_to_browser, monitor_session)]
        finished, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in finished:
            try:
                result = task.result()
                if result != 1000:
                    close_code = result
            except (WebSocketDisconnect, OSError, RuntimeError):
                pass
    except (WebSocketDisconnect, OSError, RuntimeError):
        pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        if accepted:
            try:
                await socket.close(code=close_code)
            except (WebSocketDisconnect, RuntimeError):
                pass
