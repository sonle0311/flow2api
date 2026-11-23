"""Per-client API keys: secrets stored hashed, rate and concurrency limits, admin API, endpoint enforcement."""

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI

from src.api import admin, routes
from src.core import auth
from src.core.database import Database
from src.services.client_keys import (
    KEY_PREFIX,
    ClientKeyService,
    ClientLimitExceeded,
)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ClientKeyServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = str(Path(self.temp.name) / "flow.db")
        self.db = Database(self.db_path)
        await self.db.init_db()
        self.clock = Clock()
        self.service = ClientKeyService(self.db, clock=self.clock)
        await self.service.initialize()

    async def make(self, name="client", rate=60, concurrent=3):
        description, secret = await self.service.create(name, rate, concurrent)
        return description["id"], secret

    async def test_secret_is_shown_once_and_only_its_hash_is_stored(self):
        description, secret = await self.service.create("acme")
        self.assertTrue(secret.startswith(KEY_PREFIX))
        self.assertEqual(description["key_prefix"], secret[: len(KEY_PREFIX) + 4])
        self.assertNotIn(secret, json.dumps(self.service.list()))
        with sqlite3.connect(self.db_path) as conn:
            stored = " ".join(str(value) for row in conn.execute("SELECT * FROM client_keys") for value in row)
        self.assertNotIn(secret, stored)
        self.assertEqual(self.service.authenticate(secret).name, "acme")
        self.assertIsNone(self.service.authenticate(secret + "x"))
        self.assertIsNone(self.service.authenticate("sk-other-key"))

    async def test_keys_survive_a_restart(self):
        key_id, secret = await self.make("persisted", 5, 2)
        reloaded = ClientKeyService(self.db)
        await reloaded.initialize()
        record = reloaded.authenticate(secret)
        self.assertEqual((record.id, record.rate_limit_per_minute, record.max_concurrent), (key_id, 5, 2))

    async def test_rate_limit_counts_admitted_requests_in_a_sliding_minute(self):
        key_id, secret = await self.make(rate=3, concurrent=0)
        record = self.service.authenticate(secret)
        for _ in range(3):
            self.service.admit(record).release()
            self.clock.now += 10
        with self.assertRaises(ClientLimitExceeded) as caught:
            self.service.admit(record)
        self.assertEqual((caught.exception.reason, caught.exception.limit), ("rate_limit", 3))
        # The oldest hit was 30 s ago, so it frees up in 30 s.
        self.assertEqual(caught.exception.retry_after, 30)
        self.assertIn("每分钟 3 次", caught.exception.message)
        self.clock.now += 30
        self.service.admit(record).release()

    async def test_rejected_requests_do_not_consume_the_rate_budget(self):
        _, secret = await self.make(rate=2, concurrent=1)
        record = self.service.authenticate(secret)
        lease = self.service.admit(record)
        for _ in range(5):
            with self.assertRaises(ClientLimitExceeded) as caught:
                self.service.admit(record)
            self.assertEqual(caught.exception.reason, "concurrency")
        lease.release()
        self.service.admit(record).release()
        with self.assertRaises(ClientLimitExceeded):
            self.service.admit(record)

    async def test_concurrency_limit_frees_up_when_a_lease_is_released_once(self):
        _, secret = await self.make(rate=0, concurrent=2)
        record = self.service.authenticate(secret)
        first, second = self.service.admit(record), self.service.admit(record)
        with self.assertRaises(ClientLimitExceeded) as caught:
            self.service.admit(record)
        self.assertEqual((caught.exception.reason, caught.exception.retry_after), ("concurrency", 5))
        first.release()
        first.release()  # idempotent: must not free a second slot
        self.service.admit(record)
        with self.assertRaises(ClientLimitExceeded):
            self.service.admit(record)
        second.release()

    async def test_zero_means_unlimited_and_keys_are_independent(self):
        _, unlimited = await self.make("free", rate=0, concurrent=0)
        _, limited = await self.make("tight", rate=1, concurrent=1)
        free, tight = self.service.authenticate(unlimited), self.service.authenticate(limited)
        for _ in range(500):
            self.service.admit(free)
        self.service.admit(tight)
        with self.assertRaises(ClientLimitExceeded):
            self.service.admit(tight)

    async def test_disabled_rotated_and_deleted_keys_stop_working_immediately(self):
        key_id, secret = await self.make()
        await self.service.update(key_id, is_active=False)
        self.assertIsNone(self.service.authenticate(secret))
        await self.service.update(key_id, is_active=True)
        self.assertIsNotNone(self.service.authenticate(secret))
        description, new_secret = await self.service.rotate(key_id)
        self.assertIsNone(self.service.authenticate(secret))
        self.assertEqual(self.service.authenticate(new_secret).id, key_id)
        self.assertEqual(description["key_prefix"], new_secret[: len(KEY_PREFIX) + 4])
        self.assertTrue(await self.service.delete(key_id))
        self.assertIsNone(self.service.authenticate(new_secret))
        self.assertFalse(await self.service.delete(key_id))
        self.assertIsNone(await self.service.rotate(key_id))
        self.assertIsNone(await self.service.update(key_id, name="x"))

    async def test_updates_validate_input_and_persist(self):
        key_id, secret = await self.make()
        updated = await self.service.update(key_id, name=" renamed ", rate_limit_per_minute=7, max_concurrent=0)
        self.assertEqual((updated["name"], updated["rate_limit_per_minute"], updated["max_concurrent"]), ("renamed", 7, 0))
        for bad in ({"rate_limit_per_minute": -1}, {"max_concurrent": True}, {"name": "  "}, {"rate_limit_per_minute": "5"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                await self.service.update(key_id, **bad)
        reloaded = ClientKeyService(self.db)
        await reloaded.initialize()
        self.assertEqual(reloaded.authenticate(secret).name, "renamed")

    async def test_usage_is_counted_in_memory_and_flushed_without_double_counting(self):
        key_id, secret = await self.make(rate=0, concurrent=0)
        record = self.service.authenticate(secret)
        for _ in range(4):
            self.service.admit(record).release()
        description = self.service.describe(record)
        self.assertEqual((description["total_requests"], description["requests_last_minute"]), (4, 4))
        self.assertIsNotNone(description["last_used_at"])
        await self.service.flush_usage()
        await self.service.flush_usage()
        self.service.admit(record).release()
        await self.service.close()
        reloaded = ClientKeyService(self.db)
        await reloaded.initialize()
        self.assertEqual(reloaded.get(key_id).total_requests, 5)


class ClientKeyEndpointTests(unittest.IsolatedAsyncioTestCase):
    """The real routers with a stub generation handler: no upstream call is made."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(str(Path(self.temp.name) / "flow.db"))
        await self.db.init_db()
        self.service = ClientKeyService(self.db)
        await self.service.initialize()
        self.previous_auth = auth.get_client_key_service()
        self.previous_admin = admin.client_key_service
        self.previous_handler = routes.generation_handler
        auth.set_client_key_service(self.service)
        admin.set_client_key_service(self.service)
        self.addCleanup(auth.set_client_key_service, self.previous_auth)
        self.addCleanup(admin.set_client_key_service, self.previous_admin)
        self.addCleanup(routes.set_generation_handler, self.previous_handler)

        self.release = asyncio.Event()
        self.started = 0

        async def generate(**kwargs):
            self.started += 1
            await self.release.wait()
            yield json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

        self.handler = SimpleNamespace(
            handle_generation=generate, admission_preflight=AsyncMock(return_value=None),
        )
        routes.set_generation_handler(self.handler)

        app = FastAPI()
        app.include_router(routes.router)
        app.include_router(admin.router)
        self.session = "client-key-admin-session"
        admin.active_admin_tokens.add(self.session)
        self.addCleanup(admin.active_admin_tokens.discard, self.session)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)

    def admin_headers(self):
        return {"Authorization": f"Bearer {self.session}"}

    async def create_key(self, **body):
        response = await self.client.post(
            "/api/client-keys", json={"name": "acme", **body}, headers=self.admin_headers(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def generate(self, secret, **extra):
        return self.client.post(
            "/v1/chat/completions",
            json={"model": "gemini-3.1-flash-image-landscape", "messages": [{"role": "user", "content": "a red apple"}], **extra},
            headers={"Authorization": f"Bearer {secret}"},
        )

    async def test_admin_api_creates_lists_updates_rotates_and_deletes(self):
        created = await self.create_key(rate_limit_per_minute=10, max_concurrent=2)
        secret, key_id = created["api_key"], created["client_key"]["id"]
        self.assertTrue(secret.startswith(KEY_PREFIX))
        listing = (await self.client.get("/api/client-keys", headers=self.admin_headers())).json()
        self.assertEqual([item["id"] for item in listing["client_keys"]], [key_id])
        self.assertNotIn(secret, json.dumps(listing))
        updated = await self.client.put(
            f"/api/client-keys/{key_id}", json={"is_active": False}, headers=self.admin_headers(),
        )
        self.assertFalse(updated.json()["client_key"]["is_active"])
        self.assertEqual(updated.json()["client_key"]["rate_limit_per_minute"], 10)
        rotated = (await self.client.post(f"/api/client-keys/{key_id}/rotate", headers=self.admin_headers())).json()
        self.assertNotEqual(rotated["api_key"], secret)
        deleted = await self.client.delete(f"/api/client-keys/{key_id}", headers=self.admin_headers())
        self.assertTrue(deleted.json()["success"])
        for method, url in (("PUT", f"/api/client-keys/{key_id}"), ("POST", f"/api/client-keys/{key_id}/rotate"), ("DELETE", f"/api/client-keys/{key_id}")):
            missing = await self.client.request(method, url, json={"name": "x"} if method == "PUT" else None, headers=self.admin_headers())
            self.assertEqual(missing.status_code, 404)

    async def test_admin_api_needs_an_admin_session_and_validates_input(self):
        self.assertEqual((await self.client.get("/api/client-keys")).status_code, 401)
        self.assertEqual((await self.client.post("/api/client-keys", json={"name": "x"})).status_code, 401)
        for body in ({"name": ""}, {"name": "x", "rate_limit_per_minute": -1}, {"name": "x", "max_concurrent": 10**6}, {"name": "x", "extra": 1}):
            with self.subTest(body=body):
                response = await self.client.post("/api/client-keys", json=body, headers=self.admin_headers())
                self.assertEqual(response.status_code, 422)

    async def test_client_key_authenticates_generation_and_disabled_key_is_rejected(self):
        created = await self.create_key(rate_limit_per_minute=0, max_concurrent=0)
        self.release.set()
        self.assertEqual((await self.generate(created["api_key"])).status_code, 200)
        await self.client.put(
            f"/api/client-keys/{created['client_key']['id']}", json={"is_active": False}, headers=self.admin_headers(),
        )
        self.assertEqual((await self.generate(created["api_key"])).status_code, 401)
        self.assertEqual((await self.generate("sk-flow-unknown")).status_code, 401)

    async def test_rate_limit_answers_429_with_retry_after_in_openai_and_gemini_shapes(self):
        created = await self.create_key(rate_limit_per_minute=1, max_concurrent=0)
        secret = created["api_key"]
        self.release.set()
        self.assertEqual((await self.generate(secret)).status_code, 200)
        limited = await self.generate(secret)
        self.assertEqual(limited.status_code, 429)
        self.assertGreaterEqual(int(limited.headers["retry-after"]), 1)
        error = limited.json()["error"]
        self.assertEqual((error["type"], error["code"]), ("rate_limit_error", "rate_limit_exceeded"))
        self.assertEqual(error["retry_after"], int(limited.headers["retry-after"]))
        gemini = await self.client.post(
            "/v1beta/models/gemini-3.1-flash-image-landscape:generateContent",
            json={"contents": [{"parts": [{"text": "a red apple"}]}]},
            headers={"x-goog-api-key": secret},
        )
        self.assertEqual(gemini.status_code, 429)
        self.assertEqual(gemini.json()["error"]["status"], "RESOURCE_EXHAUSTED")
        self.assertEqual(gemini.headers["retry-after"], limited.headers["retry-after"])

    async def test_concurrency_limit_holds_the_slot_until_the_request_finishes(self):
        created = await self.create_key(rate_limit_per_minute=0, max_concurrent=1)
        secret = created["api_key"]
        running = asyncio.create_task(self.generate(secret))
        for _ in range(100):
            if self.started:
                break
            await asyncio.sleep(0.01)
        rejected = await self.generate(secret)
        self.assertEqual(rejected.status_code, 429)
        self.assertEqual(rejected.json()["error"]["code"], "concurrency_limit_exceeded")
        self.assertEqual(self.started, 1)
        self.release.set()
        self.assertEqual((await running).status_code, 200)
        self.assertEqual((await self.generate(secret)).status_code, 200)
        listing = (await self.client.get("/api/client-keys", headers=self.admin_headers())).json()["client_keys"][0]
        self.assertEqual(listing["in_flight"], 0)

    async def test_validation_errors_and_streams_release_the_slot(self):
        created = await self.create_key(rate_limit_per_minute=0, max_concurrent=1)
        secret = created["api_key"]
        bad = await self.client.post(
            "/v1/chat/completions", json={"model": "gemini-3.1-flash-image-landscape", "messages": [{"role": "user", "content": ""}]},
            headers={"Authorization": f"Bearer {secret}"},
        )
        self.assertEqual(bad.status_code, 400)
        self.release.set()
        streamed = await self.generate(secret, stream=True)
        self.assertEqual(streamed.status_code, 200)
        self.assertIn("[DONE]", streamed.text)
        # Both the 400 and the finished stream gave the single slot back.
        self.assertEqual((await self.generate(secret)).status_code, 200)

    async def test_master_key_is_unaffected_and_client_keys_do_not_open_other_apis(self):
        self.release.set()
        master = auth.config.api_key
        for _ in range(5):
            self.assertEqual((await self.generate(master)).status_code, 200)
        created = await self.create_key()
        self.assertFalse(auth.AuthManager.verify_api_key(created["api_key"]))


if __name__ == "__main__":
    unittest.main()
