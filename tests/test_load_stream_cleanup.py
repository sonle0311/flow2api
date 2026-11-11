"""The ASGI response owns the generation iterator until capacity is released."""
import asyncio
from unittest.mock import PropertyMock, patch

import pytest
from starlette.requests import ClientDisconnect, Request

from src.api import routes
from src.core.config import config
from src.core.models import ChatCompletionRequest, GeminiGenerateContentRequest
from test_load_generation_limits import make_handler, make_token, model_for


@pytest.fixture(autouse=True)
def local_generation_settings():
    with patch.object(type(config), "cache_enabled", new_callable=PropertyMock, return_value=False), \
         patch.object(type(config), "call_logic_mode", new_callable=PropertyMock, return_value="default"):
        yield


def scope(version="2.4"):
    return {"type": "http", "asgi": {"version": "3.0", "spec_version": version},
            "method": "POST", "scheme": "http", "path": "/v1/chat/completions",
            "query_string": b"", "headers": [(b"host", b"localhost:38000")]}


async def response_for(protocol):
    if protocol == "openai":
        return await routes.create_chat_completion(
            ChatCompletionRequest(model=model_for("image"), stream=True,
                                  messages=[{"role": "user", "content": "synthetic prompt"}]),
            Request(scope()), api_key="synthetic-key",
        )
    return await routes.stream_generate_content(
        model_for("image"), GeminiGenerateContentRequest(
            contents=[{"parts": [{"text": "synthetic prompt"}]}],
        ), Request(scope()), alt=None, api_key="synthetic-key",
    )


async def assert_capacity_available(handler):
    assert await handler.concurrency_manager.get_image_inflight(1) == 0
    selected = await handler.load_balancer.select_token(
        for_image_generation=True, reserve=True, model=model_for("image"),
    )
    assert selected is not None
    await handler.concurrency_manager.release_image(selected.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai", "gemini"])
async def test_close_adapter_releases_its_inner_generation_immediately(protocol):
    handler = await make_handler([make_token()])
    with patch.object(routes, "generation_handler", handler):
        response = await response_for(protocol)
        iterator = response.body_iterator
        try:
            for _ in range(5):
                await anext(iterator)
                if await handler.concurrency_manager.get_image_inflight(1):
                    break
            assert await handler.concurrency_manager.get_image_inflight(1) == 1
            await iterator.aclose()
            await assert_capacity_available(handler)
        finally:
            await iterator.aclose()
            await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai", "gemini"])
@pytest.mark.parametrize("exit_kind", ["cancel", "send_error", "disconnect"])
async def test_response_lifecycle_closes_a_retained_stream(protocol, exit_kind):
    handler = await make_handler([make_token()])
    entered = asyncio.Event()

    async def send(message):
        if message["type"] == "http.response.body" and await handler.concurrency_manager.get_image_inflight(1):
            entered.set()
            if exit_kind == "send_error":
                raise OSError("synthetic client disconnected")
            await asyncio.Event().wait()

    async def receive():
        await entered.wait()
        if exit_kind == "disconnect":
            return {"type": "http.disconnect"}
        await asyncio.Event().wait()

    with patch.object(routes, "generation_handler", handler):
        response = await response_for(protocol)
        running = asyncio.create_task(response(scope("2.0" if exit_kind == "disconnect" else "2.4"), receive, send))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            if exit_kind == "cancel":
                running.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await running
            elif exit_kind == "send_error":
                with pytest.raises(ClientDisconnect):
                    await running
            else:
                await asyncio.wait_for(running, 2)
            # Keep response strongly reachable: cleanup cannot depend on GC.
            assert response.body_iterator is not None
            await assert_capacity_available(handler)
        finally:
            if not running.done():
                running.cancel()
            await asyncio.gather(running, return_exceptions=True)
            await response.body_iterator.aclose()
            await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai", "gemini"])
async def test_repeated_response_cancellation_waits_for_capacity_cleanup(protocol):
    handler = await make_handler([make_token()])
    streaming, releasing, finish_release = (asyncio.Event() for _ in range(3))
    release = handler.concurrency_manager.release_image

    async def delayed_release(token_id):
        releasing.set()
        await finish_release.wait()
        await release(token_id)

    async def send(message):
        if message["type"] == "http.response.body" and await handler.concurrency_manager.get_image_inflight(1):
            streaming.set()
            await asyncio.Event().wait()

    async def receive():
        await asyncio.Event().wait()

    handler.concurrency_manager.release_image = delayed_release
    with patch.object(routes, "generation_handler", handler):
        response = await response_for(protocol)
        running = asyncio.create_task(response(scope(), receive, send))
        try:
            await asyncio.wait_for(streaming.wait(), 2)
            running.cancel()
            await asyncio.wait_for(releasing.wait(), 2)
            for _ in range(2):
                running.cancel()
                await asyncio.sleep(0)
            assert not running.done()
            assert await handler.concurrency_manager.get_image_inflight(1) == 1
            finish_release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(running, 2)
            await assert_capacity_available(handler)
        finally:
            finish_release.set()
            if not running.done():
                running.cancel()
            await asyncio.gather(running, return_exceptions=True)
            await response.body_iterator.aclose()
