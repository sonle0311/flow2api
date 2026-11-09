"""Account failover diagnostics are localized without altering account data."""

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

from src.core.i18n import I18nMiddleware, translate_message


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", "Generation failed: PUBLIC_ERROR_USER_QUOTA_REACHED (all 2 attempted accounts failed: #12 quota exhausted, #99 risk check triggered; no other account is available)"),
        ("vi", "Tạo nội dung thất bại: PUBLIC_ERROR_USER_QUOTA_REACHED (cả 2 tài khoản đã thử đều thất bại: #12 hết hạn mức, #99 bị kiểm tra rủi ro chặn; không còn tài khoản khác để chuyển sang)"),
    ],
)
def test_failover_summary_localizes_reasons_and_preserves_ids(language, expected):
    source = (
        "生成失败: PUBLIC_ERROR_USER_QUOTA_REACHED"
        "（已尝试 2 个账号均失败: #12 配额耗尽, #99 触发风控；没有其他可切换的账号）"
    )
    assert translate_message(source, language) == expected


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", "PUBLIC_ERROR_UNUSUAL_ACTIVITY (all 2 attempted accounts failed: #1 quota exhausted, #2 risk check triggered)"),
        ("vi", "PUBLIC_ERROR_UNUSUAL_ACTIVITY (cả 2 tài khoản đã thử đều thất bại: #1 hết hạn mức, #2 bị kiểm tra rủi ro chặn)"),
    ],
)
def test_failover_limit_summary_localizes_without_no_account_suffix(language, expected):
    source = (
        "PUBLIC_ERROR_UNUSUAL_ACTIVITY"
        "（已尝试 2 个账号均失败: #1 配额耗尽, #2 触发风控）"
    )
    assert translate_message(source, language) == expected


@pytest.mark.parametrize(
    ("source", "english", "vietnamese"),
    [
        (
            "当前账号配额已用尽，正在切换其他账号重试...\n",
            "This account's quota is exhausted; retrying with another account...\n",
            "Tài khoản hiện tại đã hết hạn mức, đang chuyển sang tài khoản khác để thử lại...\n",
        ),
        (
            "当前账号触发风控，正在切换其他账号重试...\n",
            "This account was blocked by a risk check; retrying with another account...\n",
            "Tài khoản hiện tại bị kiểm tra rủi ro chặn, đang chuyển sang tài khoản khác để thử lại...\n",
        ),
    ],
)
def test_catalog_can_translate_failover_notices_without_losing_newlines(source, english, vietnamese):
    assert translate_message(source, "en") == english
    assert translate_message(source, "vi") == vietnamese


@pytest.mark.parametrize("language", ["en", "vi"])
def test_unknown_failover_diagnostics_and_user_identifiers_are_preserved(language):
    diagnostic = "rpc=as29s, model=omni-1.2-flash, account=保存@example.com"
    source = diagnostic + "（已尝试 1 个账号均失败: #88 自定义上游原因）"
    translated = translate_message(source, language)
    assert diagnostic in translated
    assert "#88 自定义上游原因" in translated
    # A translated reason is not a rule for rewriting user-controlled text.
    assert translate_message("Account name: 配额耗尽", language) == "Account name: 配额耗尽"


def test_failover_api_localizes_only_message_and_keeps_sse_unchanged():
    app = FastAPI()
    app.add_middleware(I18nMiddleware)
    source = "PUBLIC_ERROR_USER_QUOTA_REACHED（已尝试 1 个账号均失败: #7 配额耗尽；没有其他可切换的账号）"
    user_data = {"account": "触发风控@example.com", "model": "omni-1.2-flash", "prompt": "配额耗尽"}
    stream_body = "data: " + json.dumps(
        {"content": "当前账号配额已用尽，正在切换其他账号重试...\n", "data": user_data},
        ensure_ascii=False,
    ) + "\n\ndata: [DONE]\n\n"

    @app.get("/v1/failover")
    async def error():
        return JSONResponse({"error": {"message": source, "code": "generation_failed"}, "data": user_data}, status_code=503)

    @app.get("/v1/failover-stream")
    async def stream():
        return StreamingResponse(iter([stream_body]), media_type="text/event-stream")

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
            response = await client.get("/v1/failover", headers={"Accept-Language": "vi"})
            assert response.status_code == 503
            assert response.json()["error"]["message"] == (
                "PUBLIC_ERROR_USER_QUOTA_REACHED (cả 1 tài khoản đã thử đều thất bại: "
                "#7 hết hạn mức; không còn tài khoản khác để chuyển sang)"
            )
            assert response.json()["error"]["code"] == "generation_failed"
            assert response.json()["data"] == user_data
            streamed = await client.get("/v1/failover-stream", headers={"Accept-Language": "vi"})
            assert streamed.text == stream_body
            assert "content-language" not in streamed.headers

    asyncio.run(check())
