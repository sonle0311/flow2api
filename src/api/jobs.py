"""Asynchronous generation jobs: POST /v1/jobs, GET /v1/jobs/{id}, DELETE /v1/jobs/{id}."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..core.auth import get_client_key_service, verify_api_key_flexible
from ..core.models import ChatCompletionRequest
from ..services.client_keys import ClientLimitExceeded, ModelNotAllowed
from ..services.jobs import (
    ACTIVE_STATUSES,
    MAX_IDEMPOTENCY_KEY_LENGTH,
    POLL_HINT_SECONDS,
    IdempotencyConflict,
    JobLimitExceeded,
    JobManager,
)
from . import routes

router = APIRouter()

_manager: Optional[JobManager] = None
_IDEMPOTENCY_KEY_RE = re.compile(r"[A-Za-z0-9._:\-]+")


def set_job_manager(manager: Optional[JobManager]) -> None:
    global _manager
    _manager = manager


def _jobs() -> JobManager:
    if _manager is None:
        raise HTTPException(status_code=503, detail="Job service not initialized")
    return _manager


def _owner(api_key: str) -> str:
    """Jobs belong to the key that created them; one client key cannot see another's."""
    service = get_client_key_service()
    record = service.authenticate(api_key) if service is not None else None
    return f"client:{record.id}" if record is not None else "master"


def _error(status_code: int, message: str, code: str, error_type: str, **extra: Any) -> JSONResponse:
    body: Dict[str, Any] = {"error": {"message": message, "type": error_type, "code": code, "status_code": status_code, **extra}}
    headers = {"Retry-After": str(extra["retry_after"])} if "retry_after" in extra else None
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def _present(document: Dict[str, Any]) -> Dict[str, Any]:
    """Add a direct media URL next to the raw OpenAI-style result."""
    result = document.get("result")
    if isinstance(result, dict):
        url = routes._extract_url_from_openai_payload(result)
        if url:
            document = {**document, "output_url": url}
    return document


def _poll_headers(document: Dict[str, Any]) -> Optional[Dict[str, str]]:
    return {"Retry-After": str(POLL_HINT_SECONDS)} if document["status"] in ACTIVE_STATUSES else None


def _fingerprint(request: ChatCompletionRequest) -> str:
    body = request.model_dump(mode="json", exclude={"stream"})
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


@router.post("/v1/jobs")
async def create_job(
    request: ChatCompletionRequest,
    raw_request: Request,
    api_key: str = Depends(verify_api_key_flexible),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Start a generation in the background and return a job to poll.

    Same body as POST /v1/chat/completions (``stream`` is ignored). Send an Idempotency-Key so
    a retry after a timeout returns the original job instead of paying for a second generation.
    """
    manager = _jobs()
    key = (idempotency_key or "").strip() or None
    if key and (len(key) > MAX_IDEMPOTENCY_KEY_LENGTH or not _IDEMPOTENCY_KEY_RE.fullmatch(key)):
        return _error(400, f"Idempotency-Key must be 1-{MAX_IDEMPOTENCY_KEY_LENGTH} characters of A-Z a-z 0-9 . _ : -",
                      "invalid_idempotency_key", "invalid_request_error")
    owner = _owner(api_key)
    fingerprint = _fingerprint(request)
    try:
        replay = await manager.find_replay(owner, key, fingerprint)
    except IdempotencyConflict:
        return _error(409, "This Idempotency-Key was already used with a different request body.",
                      "idempotency_key_reused", "invalid_request_error")
    if replay is not None:
        return JSONResponse(status_code=200, content=_present(replay),
                            headers={"Idempotent-Replayed": "true", "Location": f"/v1/jobs/{replay['id']}", **(_poll_headers(replay) or {})})

    try:
        lease = routes._admit_client(api_key)
    except ClientLimitExceeded as exc:
        return routes._client_limit_response(exc)
    handed_off = False
    try:
        base_url = routes._get_request_base_url(raw_request)
        normalized = await routes._normalize_openai_request(request, request_base_url=base_url)
        routes._authorize_model(api_key, request.model, normalized.model)
        normalized.client_key_id = routes._client_key_id(api_key)
        if not normalized.prompt:
            raise HTTPException(status_code=400, detail="Prompt cannot be empty")
        rejected = await routes._ensure_generation_handler().admission_preflight(normalized.model)
        if rejected is not None:
            return routes._rejection_response(rejected)

        async def work() -> str:
            return await routes._collect_non_stream_result(
                normalized.model,
                normalized.prompt,
                normalized.images,
                base_url_override=base_url,
                video_media_id=normalized.video_media_id,
                client_key_id=normalized.client_key_id,
            )

        try:
            document, replayed = await manager.submit(
                owner=owner, idempotency_key=key, fingerprint=fingerprint,
                model=normalized.model, work=work, release=lease.release,
            )
        except IdempotencyConflict:
            handed_off = True  # submit() already released the lease
            return _error(409, "This Idempotency-Key was already used with a different request body.",
                          "idempotency_key_reused", "invalid_request_error")
        except JobLimitExceeded as exc:
            handed_off = True
            return _error(429, "Too many jobs are running; retry shortly.", "too_many_jobs", "rate_limit_error",
                          retry_after=exc.retry_after)
        handed_off = True
        headers = {"Location": f"/v1/jobs/{document['id']}", **(_poll_headers(document) or {})}
        if replayed:
            headers["Idempotent-Replayed"] = "true"
        return JSONResponse(status_code=200 if replayed else 202, content=_present(document), headers=headers)
    except ModelNotAllowed as exc:
        return routes._model_denied_response(exc)
    finally:
        if not handed_off:
            lease.release()


@router.get("/v1/jobs/{job_id}")
async def get_job(job_id: str, api_key: str = Depends(verify_api_key_flexible)):
    document = await _jobs().get(_owner(api_key), job_id)
    if document is None:
        return _error(404, f"No job {job_id}", "job_not_found", "invalid_request_error")
    return JSONResponse(content=_present(document), headers=_poll_headers(document))


@router.get("/v1/jobs")
async def list_jobs(limit: int = Query(50, ge=1, le=200), api_key: str = Depends(verify_api_key_flexible)):
    documents = await _jobs().list(_owner(api_key), limit)
    return {"object": "list", "data": [_present(document) for document in documents]}


@router.delete("/v1/jobs/{job_id}")
async def cancel_job(job_id: str, api_key: str = Depends(verify_api_key_flexible)):
    """Stop waiting for a job and free its slot.

    Generation that was already submitted to Flow cannot be recalled and may still be charged.
    """
    document = await _jobs().cancel(_owner(api_key), job_id)
    if document is None:
        return _error(404, f"No job {job_id}", "job_not_found", "invalid_request_error")
    return JSONResponse(content={**_present(document), "upstream_cancelled": False})
