"""Administrator actions for account-bound persistent browser sessions."""

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import admin
from ..services.token_manager import normalize_browser_account_email


router = APIRouter()
_SESSION_FIELDS = (
    "token_id", "enabled", "status", "browser_open", "last_sync_at", "error_code", "interval_minutes"
)


def _check_action_origin(request: Request):
    # A visible login window must only be opened by the administrator's own UI.
    # Non-browser clients without Origin can use the existing admin bearer token.
    origin = request.headers.get("origin")
    if request.method != "GET" and origin:
        source = urlsplit(origin)
        target = request.url
        if (source.scheme, source.netloc) != (target.scheme, target.netloc):
            raise HTTPException(status_code=403, detail="Forbidden")


def _service(request: Request):
    service = getattr(request.app.state, "managed_browser", None)
    if service is None:
        raise HTTPException(status_code=503, detail="浏览器会话服务不可用")
    return service


async def _session_action(request: Request, token_id: int, action: str):
    _check_action_origin(request)
    if token_id < 1 or await admin.db.get_token(token_id) is None:
        raise HTTPException(status_code=404, detail="Token不存在")
    service = _service(request)
    try:
        status = await getattr(service, action)(token_id)
    except LookupError:
        # Account deletion may race with a browser operation.
        raise HTTPException(status_code=404, detail="Token不存在") from None
    return JSONResponse(
        content={"success": True, "session": {key: status.get(key) for key in _SESSION_FIELDS}},
        headers={"Cache-Control": "no-store"},
    )


class BrowserAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def normalized_email(cls, value):
        return normalize_browser_account_email(value)


@router.post("/api/browser-sessions/accounts")
async def browser_account_create(request: Request, body: BrowserAccountRequest, token: str = Depends(admin.verify_admin_token)):
    """Start normal browser onboarding using only the intended Google email."""
    _check_action_origin(request)
    service = _service(request)
    account, created = await admin.token_manager.prepare_browser_account(body.email)
    if created and admin.concurrency_manager is not None:
        await admin.concurrency_manager.reset_token(
            account.id, image_concurrency=account.image_concurrency, video_concurrency=account.video_concurrency,
        )
    try:
        status = await service.start_login(account.id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Token不存在") from None
    except RuntimeError:
        raise HTTPException(status_code=503, detail="浏览器会话服务不可用") from None
    return JSONResponse(
        content={"success": True, "created": created, "session": {key: status.get(key) for key in _SESSION_FIELDS}},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/tokens/{token_id}/browser-session")
async def browser_session_status(request: Request, token_id: int, token: str = Depends(admin.verify_admin_token)):
    """Read profile synchronization status without opening a browser."""
    return await _session_action(request, token_id, "get_status")


@router.post("/api/tokens/{token_id}/browser-session/login")
async def browser_session_login(request: Request, token_id: int, token: str = Depends(admin.verify_admin_token)):
    """Open an account's dedicated visible browser for manual Google sign-in."""
    return await _session_action(request, token_id, "start_login")


@router.post("/api/tokens/{token_id}/browser-session/sync")
async def browser_session_sync(request: Request, token_id: int, token: str = Depends(admin.verify_admin_token)):
    """Validate and synchronize this profile's current Flow cookies."""
    return await _session_action(request, token_id, "sync")


@router.post("/api/tokens/{token_id}/browser-session/stop")
async def browser_session_stop(request: Request, token_id: int, token: str = Depends(admin.verify_admin_token)):
    """Stop automatic profile synchronization and close its runtime browser."""
    return await _session_action(request, token_id, "stop")
