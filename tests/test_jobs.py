"""Asynchronous jobs: polling, Idempotency-Key replay, cancellation, ownership, restart handling."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI

from src.api import admin, jobs as jobs_api, routes
from src.core import auth
from src.core.config import config
from src.core.database import Database
from src.core.model_resolver import get_known_model_names
from src.services.client_keys import ClientKeyService
from src.services.jobs import JobManager

MODEL = "gemini-3.1-flash-image-landscape"
MASTER = "master-test-key"
ANSWER = {"choices": [{"message": {"role": "assistant", "content": "![image](https://cdn.example/out.png)"}}]}


class JobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(str(Path(self.temp.name) / "flow.db"))
        await self.db.init_db()
        self.service = ClientKeyService(self.db)
        self.service.known_models = lambda: get_known_model_names(routes.MODEL_CONFIG)
        await self.service.initialize()
        previous_key, previous_auth = config.api_key, auth.get_client_key_service()
        previous_handler, previous_manager = routes.generation_handler, jobs_api._manager
        config.api_key = MASTER
        auth.set_client_key_service(self.service)
        admin.set_client_key_service(self.service)
        self.addCleanup(setattr, config, "api_key", previous_key)
        self.addCleanup(auth.set_client_key_service, previous_auth)
        self.addCleanup(routes.set_generation_handler, previous_handler)
        self.addCleanup(jobs_api.set_job_manager, previous_manager)

        self.release = asyncio.Event()
        self.calls = []
        self.outcome = json.dumps(ANSWER)

        async def generate(model, **kwargs):
            self.calls.append(model)
            await self.release.wait()
            yield self.outcome

        routes.set_generation_handler(SimpleNamespace(
            handle_generation=generate, admission_preflight=AsyncMock(return_value=None),
        ))
        self.manager = JobManager(self.db)
        await self.manager.start()
        self.addAsyncCleanup(self.manager.close)
        jobs_api.set_job_manager(self.manager)
        app = FastAPI()
        app.include_router(routes.router)
        app.include_router(admin.router)
        app.include_router(jobs_api.router)
        self.session = "jobs-test-session"
        admin.active_admin_tokens.add(self.session)
        self.addCleanup(admin.active_admin_tokens.discard, self.session)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)

    async def client_key(self, max_concurrent=0):
        response = await self.client.post(
            "/api/client-keys",
            json={"name": "acme", "rate_limit_per_minute": 0, "max_concurrent": max_concurrent, "allowed_models": []},
            headers={"Authorization": f"Bearer {self.session}"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["api_key"]

    def submit(self, key=MASTER, idempotency=None, prompt="a red apple"):
        headers = {"Authorization": f"Bearer {key}"}
        if idempotency:
            headers["Idempotency-Key"] = idempotency
        return self.client.post(
            "/v1/jobs", json={"model": MODEL, "messages": [{"role": "user", "content": prompt}]}, headers=headers
        )

    def fetch(self, job_id, key=MASTER):
        return self.client.get(f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {key}"})

    async def wait_for(self, job_id, status, key=MASTER):
        for _ in range(200):
            body = (await self.fetch(job_id, key)).json()
            if body["status"] == status:
                return body
            await asyncio.sleep(0.01)
        self.fail(f"job never reached {status}: {body}")

    async def test_job_runs_in_the_background_and_returns_the_same_result_as_a_sync_call(self):
        created = await self.submit()
        self.assertEqual(created.status_code, 202)
        job = created.json()
        self.assertEqual(created.headers["location"], f"/v1/jobs/{job['id']}")
        self.assertIn(job["status"], {"queued", "running"})
        running = await self.wait_for(job["id"], "running")
        self.assertEqual("5", (await self.fetch(job["id"])).headers["retry-after"])
        self.assertNotIn("result", running)
        self.release.set()
        done = await self.wait_for(job["id"], "succeeded")
        self.assertEqual(ANSWER, done["result"])
        self.assertEqual("https://cdn.example/out.png", done["output_url"])
        self.assertNotIn("retry-after", (await self.fetch(job["id"])).headers)
        listing = (await self.client.get("/v1/jobs", headers={"Authorization": f"Bearer {MASTER}"})).json()
        self.assertEqual([job["id"]], [item["id"] for item in listing["data"]])

    async def test_failed_generation_is_reported_on_the_job(self):
        self.outcome = json.dumps({"error": {"message": "boom", "type": "server_error", "code": "generation_failed", "status_code": 503}})
        self.release.set()
        job = (await self.submit()).json()
        failed = await self.wait_for(job["id"], "failed")
        self.assertEqual(("boom", 503), (failed["error"]["message"], failed["error"]["status_code"]))
        self.assertNotIn("result", failed)

    async def test_retry_with_the_same_idempotency_key_returns_the_original_job(self):
        first = await self.submit(idempotency="order-1")
        second = await self.submit(idempotency="order-1")
        self.assertEqual((202, 200), (first.status_code, second.status_code))
        self.assertEqual("true", second.headers["idempotent-replayed"])
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.release.set()
        await self.wait_for(first.json()["id"], "succeeded")
        self.assertEqual(1, len(self.calls))  # one paid generation, however often the client retried
        # Even after it finished, a retry still gets the stored result.
        late = await self.submit(idempotency="order-1")
        self.assertEqual(("succeeded", 200), (late.json()["status"], late.status_code))
        self.assertEqual(1, len(self.calls))

    async def test_idempotency_key_with_a_different_body_is_refused_and_no_key_means_a_new_job(self):
        await self.submit(idempotency="order-2")
        conflict = await self.submit(idempotency="order-2", prompt="a green pear")
        self.assertEqual(409, conflict.status_code)
        self.assertEqual("idempotency_key_reused", conflict.json()["error"]["code"])
        self.assertEqual(1, len(await self.manager.list("master")))
        a, b = await self.submit(), await self.submit()
        self.assertNotEqual(a.json()["id"], b.json()["id"])
        bad = await self.submit(idempotency="not allowed!")
        self.assertEqual(400, bad.status_code)

    async def test_cancel_frees_the_slot_and_says_upstream_work_is_not_recalled(self):
        secret = await self.client_key(max_concurrent=1)
        job = (await self.submit(secret)).json()
        await self.wait_for(job["id"], "running", secret)
        busy = await self.submit(secret, prompt="second")
        self.assertEqual((429, "concurrency_limit_exceeded"), (busy.status_code, busy.json()["error"]["code"]))
        cancelled = await self.client.delete(f"/v1/jobs/{job['id']}", headers={"Authorization": f"Bearer {secret}"})
        self.assertEqual("canceled", cancelled.json()["status"])
        self.assertFalse(cancelled.json()["upstream_cancelled"])
        self.assertEqual(0, self.manager.active_jobs)
        again = await self.submit(secret, prompt="third")
        self.assertEqual(202, again.status_code)

    async def test_a_key_cannot_see_or_cancel_another_keys_jobs(self):
        mine = await self.client_key()
        theirs = await self.client_key()
        job = (await self.submit(mine)).json()
        for response in (await self.fetch(job["id"], theirs), await self.fetch(job["id"], MASTER),
                         await self.client.delete(f"/v1/jobs/{job['id']}", headers={"Authorization": f"Bearer {theirs}"})):
            self.assertEqual((404, "job_not_found"), (response.status_code, response.json()["error"]["code"]))
        self.assertEqual(200, (await self.fetch(job["id"], mine)).status_code)
        unauthenticated = await self.client.get(f"/v1/jobs/{job['id']}")
        self.assertEqual(401, unauthenticated.status_code)

    async def test_jobs_still_running_at_a_restart_are_marked_failed_and_old_ones_expire(self):
        job = (await self.submit()).json()
        await self.wait_for(job["id"], "running")
        restarted = JobManager(self.db)
        await restarted.start()
        self.addAsyncCleanup(restarted.close)
        document = await restarted.get("master", job["id"])
        self.assertEqual(("failed", "server_restarted"), (document["status"], document["error"]["code"]))
        async with self.db._connect(write=True) as conn:
            await conn.execute("UPDATE jobs SET finished_at = 1 WHERE id = ?", (job["id"],))
            await conn.commit()
        self.assertEqual(1, await restarted.purge_expired())
        self.assertIsNone(await restarted.get("master", job["id"]))


class VideoResultTests(unittest.TestCase):
    """A finished video must name its media id, or a job result can never be extended or edited."""

    def completion(self, **kwargs):
        from src.services.generation_handler import GenerationHandler
        handler = GenerationHandler.__new__(GenerationHandler)
        return json.loads(handler._create_completion_response("https://cdn.example/v.mp4", media_type="video", **kwargs))

    def test_video_result_carries_the_media_id_and_the_url_is_still_found(self):
        payload = self.completion(media_id="MEDIA-1")
        content = payload["choices"][0]["message"]["content"]
        self.assertIn("data-media-id='MEDIA-1'", content)
        self.assertEqual("https://cdn.example/v.mp4", routes._extract_url_from_openai_payload(payload))

    def test_without_a_media_id_the_result_is_unchanged(self):
        content = self.completion()["choices"][0]["message"]["content"]
        self.assertNotIn("data-media-id", content)


if __name__ == "__main__":
    unittest.main()
