"""Per-key model allow-list: enforcement on resolved models, filtered listings, admin API, migration."""

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
from src.core.model_resolver import get_known_model_names
from src.services.client_keys import ClientKeyService

IMAGE_LANDSCAPE = "gemini-3.1-flash-image-landscape"
IMAGE_SQUARE = "gemini-3.1-flash-image-square"
OTHER_IMAGE = "gemini-3.0-pro-image-landscape"
VIDEO = "veo-3.1-fast-4s-landscape"


class ClientKeyModelTests(unittest.IsolatedAsyncioTestCase):
    """The real routers with a stub generation handler: no upstream call is made."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = str(Path(self.temp.name) / "flow.db")
        self.db = Database(self.db_path)
        await self.db.init_db()
        self.service = ClientKeyService(self.db)
        self.service.known_models = lambda: get_known_model_names(routes.MODEL_CONFIG)
        await self.service.initialize()
        previous_auth = auth.get_client_key_service()
        previous_admin = admin.client_key_service
        previous_handler = routes.generation_handler
        auth.set_client_key_service(self.service)
        admin.set_client_key_service(self.service)
        self.addCleanup(auth.set_client_key_service, previous_auth)
        self.addCleanup(admin.set_client_key_service, previous_admin)
        self.addCleanup(routes.set_generation_handler, previous_handler)

        self.models = []

        async def generate(model, **kwargs):
            self.models.append(model)
            yield json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

        routes.set_generation_handler(SimpleNamespace(
            handle_generation=generate, admission_preflight=AsyncMock(return_value=None),
        ))
        app = FastAPI()
        app.include_router(routes.router)
        app.include_router(admin.router)
        self.session = "client-key-model-session"
        admin.active_admin_tokens.add(self.session)
        self.addCleanup(admin.active_admin_tokens.discard, self.session)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)

    def admin_headers(self):
        return {"Authorization": f"Bearer {self.session}"}

    async def create_key(self, allowed_models):
        response = await self.client.post(
            "/api/client-keys",
            json={"name": "acme", "rate_limit_per_minute": 0, "max_concurrent": 0, "allowed_models": allowed_models},
            headers=self.admin_headers(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["api_key"]

    def generate(self, secret, model, **extra):
        return self.client.post(
            "/v1/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": "a red apple"}], **extra},
            headers={"Authorization": f"Bearer {secret}"},
        )

    async def listed(self, secret, path="/v1/models"):
        response = await self.client.get(path, headers={"Authorization": f"Bearer {secret}"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        return [item["id"] for item in body["data"]] if "data" in body else [
            item["name"].removeprefix("models/") for item in body["models"]
        ]

    async def test_request_outside_the_allow_list_is_refused_before_any_generation(self):
        secret = await self.create_key([IMAGE_LANDSCAPE])
        allowed = await self.generate(secret, IMAGE_LANDSCAPE)
        self.assertEqual(allowed.status_code, 200)
        denied = await self.generate(secret, OTHER_IMAGE)
        self.assertEqual(denied.status_code, 403)
        error = denied.json()["error"]
        self.assertEqual((error["type"], error["code"]), ("permission_error", "model_not_allowed"))
        self.assertIn(OTHER_IMAGE, error["message"])
        gemini = await self.client.post(
            f"/v1beta/models/{OTHER_IMAGE}:generateContent",
            json={"contents": [{"parts": [{"text": "a red apple"}]}]},
            headers={"x-goog-api-key": secret},
        )
        self.assertEqual((gemini.status_code, gemini.json()["error"]["status"]), (403, "PERMISSION_DENIED"))
        streamed = await self.client.post(
            f"/v1beta/models/{OTHER_IMAGE}:streamGenerateContent",
            json={"contents": [{"parts": [{"text": "a red apple"}]}]},
            headers={"x-goog-api-key": secret},
        )
        self.assertEqual(streamed.status_code, 403)
        self.assertEqual(self.models, [IMAGE_LANDSCAPE])

    async def test_family_request_is_judged_by_the_model_it_resolves_to(self):
        secret = await self.create_key([IMAGE_SQUARE])
        square = await self.generate(secret, "gemini-3.1-flash-image", aspect_ratio="1:1")
        self.assertEqual(square.status_code, 200, square.text)
        wide = await self.generate(secret, "gemini-3.1-flash-image", aspect_ratio="16:9")
        self.assertEqual(wide.status_code, 403)
        self.assertEqual(self.models, [IMAGE_SQUARE])

    async def test_wildcards_and_media_type_entries(self):
        family = await self.create_key(["gemini-3.1-flash-image*"])
        self.assertEqual((await self.generate(family, IMAGE_LANDSCAPE)).status_code, 200)
        self.assertEqual((await self.generate(family, "gemini-3.1-flash-image")).status_code, 200)
        self.assertEqual((await self.generate(family, OTHER_IMAGE)).status_code, 403)
        # "*" matches inside a name only; it never turns into a regular expression.
        self.assertEqual((await self.generate(family, "gemini-3.1-flash-lite-image-landscape")).status_code, 403)
        video_only = await self.create_key(["type:video"])
        self.assertEqual((await self.generate(video_only, VIDEO)).status_code, 200)
        self.assertEqual((await self.generate(video_only, IMAGE_LANDSCAPE)).status_code, 403)

    async def test_empty_allow_list_and_master_key_allow_every_model(self):
        open_key = await self.create_key([])
        self.assertEqual((await self.generate(open_key, OTHER_IMAGE)).status_code, 200)
        self.assertEqual((await self.generate(auth.config.api_key, VIDEO)).status_code, 200)

    async def test_model_listings_only_show_what_the_key_may_use(self):
        everything = await self.listed(auth.config.api_key)
        secret = await self.create_key(["gemini-3.1-flash-image-*"])
        visible = await self.listed(secret)
        self.assertTrue(visible)
        self.assertTrue(all(name.startswith("gemini-3.1-flash-image-") for name in visible), visible)
        self.assertLess(len(visible), len(everything))
        aliases = await self.listed(secret, "/v1/models/aliases")
        self.assertEqual(aliases, ["gemini-3.1-flash-image"])
        gemini = await self.listed(secret, "/v1beta/models")
        self.assertEqual(sorted(gemini), sorted(visible))
        own = await self.client.get(f"/v1beta/models/{IMAGE_LANDSCAPE}", headers={"x-goog-api-key": secret})
        hidden = await self.client.get(f"/v1beta/models/{OTHER_IMAGE}", headers={"x-goog-api-key": secret})
        self.assertEqual((own.status_code, hidden.status_code), (200, 404))

    async def test_a_family_is_listed_when_one_of_its_variants_is_allowed(self):
        secret = await self.create_key(["omni-1.1-flash-10s-landscape"])
        visible = await self.listed(secret)
        self.assertIn("omni-1.1-flash", visible)
        self.assertIn("omni-1.1-flash-10s-landscape", visible)
        self.assertNotIn("omni-1.2-flash", visible)
        self.assertNotIn("omni-1.1-flash-8s-landscape", visible)

    async def test_admin_api_validates_and_updates_the_allow_list(self):
        for bad in (["no-such-model"], ["gemini-*-nothing"], ["bad name"], ["type:audio"], [""], ["a" * 101]):
            with self.subTest(entry=bad):
                response = await self.client.post(
                    "/api/client-keys", json={"name": "x", "allowed_models": bad}, headers=self.admin_headers(),
                )
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.service.list(), [])
        secret = await self.create_key([f" {IMAGE_LANDSCAPE} ", IMAGE_LANDSCAPE, "type:video"])
        key = self.service.authenticate(secret)
        self.assertEqual(key.allowed_models, [IMAGE_LANDSCAPE, "type:video"])
        updated = await self.client.put(
            f"/api/client-keys/{key.id}", json={"allowed_models": [OTHER_IMAGE]}, headers=self.admin_headers(),
        )
        self.assertEqual(updated.json()["client_key"]["allowed_models"], [OTHER_IMAGE])
        self.assertEqual((await self.generate(secret, IMAGE_LANDSCAPE)).status_code, 403)
        rejected = await self.client.put(
            f"/api/client-keys/{key.id}", json={"allowed_models": ["no-such-model"]}, headers=self.admin_headers(),
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(self.service.get(key.id).allowed_models, [OTHER_IMAGE])
        # Omitting the field keeps the list; an empty list opens the key to every model again.
        renamed = await self.client.put(f"/api/client-keys/{key.id}", json={"name": "renamed"}, headers=self.admin_headers())
        self.assertEqual(renamed.json()["client_key"]["allowed_models"], [OTHER_IMAGE])
        await self.client.put(f"/api/client-keys/{key.id}", json={"allowed_models": []}, headers=self.admin_headers())
        self.assertEqual((await self.generate(secret, IMAGE_LANDSCAPE)).status_code, 200)

    async def test_admin_catalog_lists_selectable_names(self):
        self.assertEqual((await self.client.get("/api/client-keys/models")).status_code, 401)
        response = await self.client.get("/api/client-keys/models", headers=self.admin_headers())
        models = {entry["id"]: entry for entry in response.json()["models"]}
        self.assertEqual(models[IMAGE_LANDSCAPE], {"id": IMAGE_LANDSCAPE, "type": "image", "kind": "model"})
        self.assertEqual(models["gemini-3.1-flash-image"]["kind"], "family")
        self.assertEqual(models["omni-1.1-flash"], {"id": "omni-1.1-flash", "type": "video", "kind": "family"})

    async def test_allow_list_survives_a_restart(self):
        secret = await self.create_key([IMAGE_LANDSCAPE, "type:video"])
        reloaded = ClientKeyService(self.db)
        await reloaded.initialize()
        self.assertEqual(reloaded.authenticate(secret).allowed_models, [IMAGE_LANDSCAPE, "type:video"])


class ClientKeyMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_table_created_before_allow_lists_gains_the_column(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "flow.db")
            db = Database(path)
            await db.init_db()
            with sqlite3.connect(path) as conn:
                conn.execute("""CREATE TABLE client_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE,
                    key_prefix TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
                    rate_limit_per_minute INTEGER NOT NULL DEFAULT 0, max_concurrent INTEGER NOT NULL DEFAULT 0,
                    total_requests INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, last_used_at TEXT)""")
                conn.execute(
                    "INSERT INTO client_keys (name, key_hash, key_prefix, created_at) VALUES ('old', 'h', 'sk-flow-abcd', 'now')"
                )
            service = ClientKeyService(db)
            await service.initialize()
            self.assertEqual(service.list()[0]["allowed_models"], [])
            description, _ = await service.create("new", allowed_models=["type:image"])
            self.assertEqual(description["allowed_models"], ["type:image"])


if __name__ == "__main__":
    unittest.main()
