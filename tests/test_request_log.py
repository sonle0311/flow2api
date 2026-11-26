"""The request log: who made each request, filtering and paging, the summary, time breakdowns and retention."""

import asyncio
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from src.api import admin
from src.core.database import Database
from src.core.models import RequestLog, Token
from src.core.request_context import client_key_id_var, job_id_var
from src.services import log_insights
from src.services.generation_handler import GenerationHandler
from src.services.jobs import JobManager
from src.services.log_retention import LogRetention

PERFORMANCE = {
    "total_ms": 70000,
    "token_select_ms": 5,
    "ensure_at_ms": 2,
    "ensure_project_ms": 1,
    "image_generation": {
        "slot_wait_ms": 10,
        "launch_queue_wait_ms": 20,
        "launch_stagger_wait_ms": 30,
        "upload_images_ms": 16000,
        "generate_api_ms": 40000,
        "upsample_ms": 9000,
        "input_image_count": 2,
    },
    "upload_cache": {"hits": 1, "misses": 1},
}


def stamp(hours_ago: float = 0) -> str:
    return log_insights.format_timestamp(datetime.now(timezone.utc) - timedelta(hours=hours_ago))


class LogCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "flow.db")
        self.db = Database(self.path)
        await self.db.init_db()
        for number in (1, 2):
            await self.db.add_token(Token(st=f"synthetic-session-{number}", email=f"account{number}@example.test"))

    async def add(self, *, model="gemini-3.1-flash-image-landscape", prompt="a red fox", status=200, duration=10.0,
                  token_id=1, operation="generate_image", client_key_id=None, job_id=None, response=None, hours_ago=0):
        log_id = await self.db.add_request_log(RequestLog(
            token_id=token_id, operation=operation,
            request_body=json.dumps({"model": model, "prompt": prompt}),
            response_body=json.dumps(response if response is not None else {"status": "ok"}),
            status_code=status, duration=duration, model=model, prompt_excerpt=prompt,
            client_key_id=client_key_id, job_id=job_id,
        ))
        if hours_ago:
            with sqlite3.connect(self.path) as conn:
                conn.execute("UPDATE request_logs SET created_at = ? WHERE id = ?", (stamp(hours_ago), log_id))
        return log_id


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_logs_written_before_the_columns_existed_get_their_model_and_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "flow.db")
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "CREATE TABLE request_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, token_id INTEGER, operation TEXT NOT NULL, "
                    "request_body TEXT, response_body TEXT, status_code INTEGER NOT NULL, duration FLOAT NOT NULL, "
                    "status_text TEXT DEFAULT '', progress INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                    "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
                conn.execute(
                    "INSERT INTO request_logs (operation, request_body, status_code, duration) VALUES (?, ?, 200, 1)",
                    ("generate_image", json.dumps({"model": "m1", "prompt": "line one\nline two"})),
                )
                conn.execute("INSERT INTO request_logs (operation, request_body, status_code, duration) VALUES ('x', 'not json', 500, 1)")
            db = Database(path)
            await db.init_db()
            await db.init_db()  # a second start must not redo or break anything
            rows, total = await db.query_request_logs()
        by_id = {row["id"]: row for row in rows}
        self.assertEqual(2, total)
        self.assertEqual(("m1", "line one line two"), (by_id[1]["model"], by_id[1]["prompt_excerpt"]))
        self.assertIsNone(by_id[2]["model"])


class QueryTests(LogCase):
    async def test_filters_combine_and_the_total_ignores_the_page(self):
        await self.add(prompt="fox in snow", client_key_id=3, job_id="job_a")
        await self.add(prompt="owl at night", status=500)
        await self.add(prompt="city lights", model="veo_3_1_t2v_lite", operation="generate_video", status=102)
        await self.add(prompt="fox again", token_id=2, status=500)

        async def ids(**filters):
            rows, total = await self.db.query_request_logs(**filters)
            return [row["id"] for row in rows], total

        self.assertEqual(([4, 3, 2, 1], 4), await ids())
        self.assertEqual(([4, 2], 2), await ids(status="failed"))
        self.assertEqual(([3], 1), await ids(status="running"))
        self.assertEqual(([1], 1), await ids(status="success"))
        self.assertEqual(([3], 1), await ids(model="veo_3_1_t2v_lite"))
        self.assertEqual(([4], 1), await ids(token_id=2))
        self.assertEqual(([1], 1), await ids(client_key_id=3))
        self.assertEqual(([1], 1), await ids(job_id="job_a"))
        self.assertEqual(([4, 1], 2), await ids(query="fox"))
        self.assertEqual(([4], 1), await ids(query="fox", status="failed"))
        self.assertEqual(([2, 1], 4), await ids(limit=2, offset=2))
        with self.assertRaises(ValueError):
            await ids(status="bogus")

    async def test_search_text_is_literal_not_a_pattern(self):
        await self.add(prompt="100% sure")
        await self.add(prompt="a_b")
        await self.add(prompt="axb")
        self.assertEqual(1, (await self.db.query_request_logs(query="100%"))[1])
        self.assertEqual(1, (await self.db.query_request_logs(query="a_b"))[1])

    async def test_search_finds_text_deep_in_a_long_prompt_and_in_error_messages(self):
        await self.add(prompt="x" * 500 + " needle")
        await self.add(status=500, response={"error": "Flow rejected: rpc=ogiZ0b"})
        self.assertEqual(1, (await self.db.query_request_logs(query="needle"))[1])
        self.assertEqual(1, (await self.db.query_request_logs(query="ogiZ0b"))[1])

    async def test_a_time_window_hides_older_logs(self):
        await self.add(hours_ago=30)
        await self.add(hours_ago=2)
        await self.add()
        self.assertEqual(3, (await self.db.query_request_logs())[1])
        self.assertEqual(2, (await self.db.query_request_logs(since=log_insights.window_start(24)))[1])
        self.assertEqual(1, (await self.db.query_request_logs(since=log_insights.window_start(1)))[1])

    async def test_updating_a_row_keeps_the_new_fields_in_sync(self):
        log_id = await self.add(status=102, model="m", prompt="p")
        await self.db.update_request_log(log_id, status_code=200, model="m", prompt_excerpt="p", job_id="job_z")
        row = (await self.db.query_request_logs(job_id="job_z"))[0][0]
        self.assertEqual((log_id, 200), (row["id"], row["status_code"]))


class SummaryTests(unittest.TestCase):
    def rows(self):
        def row(model, status, duration, token=1, email="a@x", key=0, hits=None, misses=None, minutes_ago=5):
            return {"model": model, "status_code": status, "duration": duration, "token_id": token, "token_email": email,
                    "client_key_id": key, "cache_hits": hits, "cache_misses": misses,
                    "created_at": log_insights.format_timestamp(datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))}
        return [
            row("img", 200, 10, hits=1, misses=1), row("img", 200, 20, hits=3, misses=0),
            row("img", 200, 30, token=2, email="b@x", key=4), row("img", 500, 0, token=2, email="b@x"),
            row("vid", 102, 0), row("vid", 200, 100, key=4, minutes_ago=50),
        ]

    def test_counts_rates_and_percentiles(self):
        summary = log_insights.summarize(self.rows(), since=log_insights.window_start(1), client_key_names={4: "agent"})
        self.assertEqual((6, 4, 1, 1), (summary["total"], summary["success"], summary["failed"], summary["running"]))
        self.assertEqual(0.8, summary["success_rate"])
        self.assertEqual({"count": 4, "median": 25.0, "p95": 100.0}, summary["duration"])
        img = next(item for item in summary["by_model"] if item["model"] == "img")
        self.assertEqual((4, 3, 1, 0.75, 20.0), (img["requests"], img["success"], img["failed"], img["success_rate"], img["median"]))
        self.assertEqual([("a@x", 4), ("b@x", 2)], [(a["email"], a["requests"]) for a in summary["by_account"]][:2])
        self.assertEqual({4: "agent"}, {k["client_key_id"]: k["name"] for k in summary["by_client_key"] if k["client_key_id"]})

    def test_cache_hit_rate_counts_only_requests_that_uploaded_images(self):
        cache = log_insights.summarize(self.rows(), since=None)["upload_cache"]
        self.assertEqual({"requests": 2, "hits": 4, "misses": 1, "hit_rate": 0.8}, cache)

    def test_an_empty_window_has_no_rates(self):
        summary = log_insights.summarize([], since=log_insights.window_start(1))
        self.assertEqual((0, None, None, []), (summary["total"], summary["success_rate"], summary["upload_cache"]["hit_rate"], summary["buckets"]))
        self.assertEqual({"count": 0, "median": None, "p95": None}, summary["duration"])

    def test_buckets_cover_the_window_and_count_failures(self):
        summary = log_insights.summarize(self.rows(), since=log_insights.window_start(1))
        self.assertEqual(6, sum(slot["requests"] for slot in summary["buckets"]))
        self.assertEqual(1, sum(slot["failed"] for slot in summary["buckets"]))
        self.assertLessEqual(len(summary["buckets"]), 26)


class TimingTests(unittest.TestCase):
    def test_stages_come_in_order_and_the_remainder_is_what_no_stage_covers(self):
        timings = log_insights.extract_timings(json.dumps({"performance": PERFORMANCE}))
        self.assertEqual(
            ["token_select", "ensure_at", "ensure_project", "slot_wait", "launch_queue_wait", "launch_stagger_wait",
             "upload_images", "generate_api", "upsample"],
            [stage["id"] for stage in timings["stages"]],
        )
        self.assertEqual(70000, timings["total_ms"])
        self.assertEqual(70000 - (5 + 2 + 1 + 10 + 20 + 30 + 16000 + 40000 + 9000), timings["other_ms"])
        self.assertEqual({"hits": 1, "misses": 1}, timings["upload_cache"])
        self.assertEqual(2, timings["input_images"])

    def test_a_video_trace_reads_its_own_stages(self):
        body = {"performance": {"total_ms": 90000, "video_generation": {"slot_wait_ms": 5, "submit_generation_ms": 4000, "input_image_count": 0}}}
        stages = {stage["id"]: stage["ms"] for stage in log_insights.extract_timings(json.dumps(body))["stages"]}
        self.assertEqual({"slot_wait": 5, "submit_generation": 4000}, stages)

    def test_logs_without_a_trace_have_no_timings(self):
        for body in (None, "", "not json", json.dumps({"error": "x"}), json.dumps({"performance": {}})):
            self.assertIsNone(log_insights.extract_timings(body))


class RetentionTests(LogCase):
    async def test_only_logs_older_than_the_limit_are_deleted_and_zero_keeps_everything(self):
        for hours in (24 * 10, 24 * 3, 1):
            await self.add(hours_ago=hours)
        retention = LogRetention(self.db)
        self.assertEqual(0, await retention.get_days())
        self.assertEqual(0, await retention.set_days(0))
        self.assertEqual(3, (await self.db.query_request_logs())[1])
        self.assertEqual(1, await retention.set_days(7))
        self.assertEqual(2, (await self.db.query_request_logs())[1])
        self.assertEqual(7, await retention.get_days())
        self.assertEqual(1, await retention.set_days(2))
        self.assertEqual(1, (await self.db.query_request_logs())[1])

    async def test_invalid_settings_are_refused_and_not_stored(self):
        retention = LogRetention(self.db)
        for bad in (-1, 3651, 1.5, "7", True):
            with self.assertRaises(ValueError):
                await retention.set_days(bad)
        self.assertEqual(0, await retention.get_days())

    async def test_the_cleanup_loop_applies_the_setting_without_being_asked(self):
        await self.add(hours_ago=24 * 5)
        retention = LogRetention(self.db, interval=0.05)
        await retention.set_days(0)
        async with self.db._connect(write=True) as conn:
            await conn.execute("UPDATE log_retention SET days = 1 WHERE id = 1")
            await conn.commit()
        retention.start()
        for _ in range(60):
            if (await self.db.query_request_logs())[1] == 0:
                break
            await asyncio.sleep(0.05)
        await retention.close()
        self.assertEqual(0, (await self.db.query_request_logs())[1])


class WhoMadeTheRequestTests(LogCase):
    async def test_the_log_records_the_model_prompt_client_key_and_job(self):
        handler = GenerationHandler.__new__(GenerationHandler)
        handler.db = self.db
        client_key_id_var.set(7)
        job_id_var.set("job_1")
        self.addCleanup(client_key_id_var.set, 0)
        self.addCleanup(job_id_var.set, None)
        log_id = await handler._log_request(
            token_id=None, operation="generate_image",
            request_data={"model": "m", "prompt": "line one\n\n  line two " + "x" * 500},
            response_data={"status": "processing"}, status_code=102, duration=0,
        )
        await handler._log_request(
            token_id=2, operation="generate_image", request_data={"model": "m", "prompt": "p"},
            response_data={"status": "ok"}, status_code=200, duration=4.2, log_id=log_id,
        )
        row = (await self.db.query_request_logs(job_id="job_1"))[0][0]
        self.assertEqual((7, "m", 2, 200), (row["client_key_id"], row["model"], row["token_id"], row["status_code"]))
        self.assertEqual("p", row["prompt_excerpt"])

    async def test_a_request_without_a_key_or_job_leaves_them_empty(self):
        handler = GenerationHandler.__new__(GenerationHandler)
        handler.db = self.db
        await handler._log_request(token_id=1, operation="generate_image", request_data={"model": "m", "prompt": "q"},
                                   response_data={}, status_code=200, duration=1)
        row = (await self.db.query_request_logs())[0][0]
        self.assertEqual((None, ""), (row["client_key_id"], row["job_id"] or ""))

    async def test_a_long_prompt_is_cut_to_one_line_for_the_list(self):
        handler = GenerationHandler.__new__(GenerationHandler)
        handler.db = self.db
        await handler._log_request(token_id=1, operation="generate_image",
                                   request_data={"model": "m", "prompt": "a\n" * 300}, response_data={}, status_code=200, duration=1)
        excerpt = (await self.db.query_request_logs())[0][0]["prompt_excerpt"]
        self.assertEqual(200, len(excerpt))
        self.assertNotIn("\n", excerpt)

    async def test_a_job_logs_under_its_own_id(self):
        manager = JobManager(self.db)
        seen = []

        async def work():
            seen.append(job_id_var.get())
            return json.dumps({"ok": True})

        document, _ = await manager.submit(owner="o", idempotency_key=None, fingerprint="f", model="m", work=work, release=lambda: None)
        await asyncio.gather(*manager._tasks.values())
        self.assertEqual([document["id"]], seen)

    async def test_the_client_key_reaches_the_task_that_logs_it(self):
        from tests.test_token_quota_failover import _build_handler, _token
        handler, _ = _build_handler([_token(1)], set())
        async for _chunk in handler.handle_generation("no-such-model", "p", client_key_id=9):
            pass
        self.assertEqual(9, client_key_id_var.get())
        client_key_id_var.set(0)


class AdminEndpointTests(LogCase):
    async def request(self, method, url, **kwargs):
        app = FastAPI()
        app.include_router(admin.router)
        app.dependency_overrides[admin.verify_admin_token] = lambda: "test"
        retention = LogRetention(self.db)
        with patch.object(admin, "db", self.db), patch.object(admin, "log_retention", retention):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
                return await client.request(method, url, **kwargs)

    async def test_the_list_is_filtered_paged_and_reports_the_total_in_a_header(self):
        for index in range(5):
            await self.add(prompt=f"fox {index}", status=500 if index % 2 else 200)
        page = await self.request("GET", "/api/logs?status=failed&limit=1&offset=1")
        self.assertEqual(200, page.status_code)
        self.assertEqual("2", page.headers["X-Total-Count"])
        body = page.json()
        self.assertEqual(1, len(body))
        self.assertEqual({"model", "prompt_excerpt", "client_key_id", "client_key_name", "job_id"} - set(body[0]), set())
        self.assertEqual("fox 1", body[0]["prompt_excerpt"])
        self.assertEqual(422, (await self.request("GET", "/api/logs?status=bogus")).status_code)
        self.assertEqual(5, len((await self.request("GET", "/api/logs?limit=9999")).json()))

    async def test_summary_and_retention_routes_are_not_taken_for_a_log_id(self):
        await self.add()
        summary = await self.request("GET", "/api/logs/summary?hours=24")
        self.assertEqual(200, summary.status_code)
        self.assertEqual(1, summary.json()["total"])
        self.assertEqual(200, (await self.request("GET", "/api/logs/retention")).status_code)
        self.assertEqual(200, (await self.request("GET", "/api/logs/1")).status_code)

    async def test_setting_retention_deletes_old_logs_and_rejects_bad_values(self):
        await self.add(hours_ago=24 * 9)
        await self.add()
        bad = await self.request("PUT", "/api/logs/retention", json={"retention_days": -1})
        self.assertEqual(422, bad.status_code)
        saved = await self.request("PUT", "/api/logs/retention", json={"retention_days": 7})
        self.assertEqual((7, 1), (saved.json()["retention_days"], saved.json()["purged"]))
        self.assertEqual(1, (await self.db.query_request_logs())[1])

    async def test_the_detail_carries_the_time_breakdown(self):
        log_id = await self.add(response={"performance": PERFORMANCE})
        detail = (await self.request("GET", f"/api/logs/{log_id}")).json()
        self.assertEqual(70000, detail["timings"]["total_ms"])
        self.assertEqual("gemini-3.1-flash-image-landscape", detail["model"])


if __name__ == "__main__":
    unittest.main()
