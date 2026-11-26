# -*- coding: utf-8 -*-
"""Tests for flow2api.py. No paid generation: a local fake server answers every request.
Run: python3 test_flow2api.py   (Python 3.9+, standard library only)"""
import contextlib, io, json, os, pathlib, sys, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import flow2api as F

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000")
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16
KEY = "secret-key-123"


def completion(content):
    return {"id": "c1", "object": "chat.completion", "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}


class Fake(BaseHTTPRequestHandler):
    """scenario: ok | legacy | busy | budget | denied | restart | captcha_once | drop_once"""
    scenario = "ok"; calls = []; jobs = {}; idem = {}; busy_left = 0; polls = {}; failed_once = False; dropped = False; kind = "image"; live = 0; peak = 0

    @classmethod
    def reset(cls, scenario="ok", kind="image", busy_left=0):
        cls.scenario, cls.kind, cls.busy_left = scenario, kind, busy_left
        cls.calls, cls.jobs, cls.idem, cls.polls, cls.failed_once, cls.dropped = [], {}, {}, {}, False, False
        cls.live = cls.peak = 0

    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, headers=None, raw=None, ctype="application/json"):
        data = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers(); self.wfile.write(data)

    def _media(self):
        base = "http://127.0.0.1:%d" % self.server.server_port
        if Fake.kind == "video":
            return "<video src='%s/files/v.mp4' data-media-id='MID123' controls></video>" % base
        return "![img](%s/files/i.png)" % base

    def do_GET(self):
        Fake.calls.append(("GET", self.path, dict(self.headers)))
        path = self.path.split("?")[0]
        if path.startswith("/files/"):
            return self._send(200, raw=MP4 if path.endswith(".mp4") else PNG, ctype="application/octet-stream")
        if path == "/v1/models":
            return self._send(200, {"data": [{"id": "gemini-3.1-flash-image-landscape", "description": "x"}, {"id": "omni-1.2-flash-360p-3s-landscape", "description": "x"},
                                             {"id": "veo-3.1-fast-8s-landscape", "description": "Veo (retires 2026-12-05)"}]})
        if path == "/v1/models/aliases":
            return self._send(200, {"data": [{"id": "omni-1.2-flash", "description": "alias"}, {"id": "veo-3.1-fast", "description": "Veo alias (retires 2026-12-05)"}]})
        if path == "/v1/jobs":
            return self._send(404, {"detail": "Not Found"}) if Fake.scenario == "legacy" else self._send(200, {"object": "list", "data": []})
        if path.startswith("/v1/jobs/"):
            jid = path.rsplit("/", 1)[1]
            Fake.polls[jid] = Fake.polls.get(jid, 0) + 1
            if Fake.polls[jid] == 1:
                time.sleep(0.05)   # long enough for concurrent jobs to overlap
                return self._send(200, {"id": jid, "status": "running"}, {"Retry-After": "5"})
            if Fake.scenario == "restart" or (Fake.scenario == "captcha_once" and Fake.jobs.get(jid) == 1):
                msg, code = ("server restarted", "server_restarted") if Fake.scenario == "restart" else ("reCAPTCHA evaluation failed", "upstream_error")
                return self._send(200, {"id": jid, "status": "failed", "model": "m", "error": {"message": msg, "code": code, "status_code": 500}})
            Fake.live -= 1
            return self._send(200, {"id": jid, "status": "succeeded", "model": "m", "result": completion(self._media()), "output_url": "x"})
        self._send(404, {"detail": "nope"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        Fake.calls.append(("POST", self.path, dict(self.headers), body))
        if self.headers.get("Authorization") != "Bearer " + KEY:
            return self._send(401, {"detail": "Invalid API key " + self.headers.get("Authorization", "")})
        if self.path == "/v1/jobs":
            if Fake.scenario == "legacy":
                return self._send(404, {"detail": "Not Found"})
            if Fake.scenario == "denied":
                return self._send(403, {"error": {"message": "model not allowed", "type": "permission_error", "code": "model_not_allowed"}})
            if Fake.scenario == "budget":
                return self._send(429, {"error": {"message": "monthly credit budget used", "type": "rate_limit_error", "code": "credit_budget_exceeded", "retry_after": 99}}, {"Retry-After": "99"})
            if Fake.busy_left > 0:
                Fake.busy_left -= 1
                return self._send(429, {"error": {"message": "busy", "type": "rate_limit_error", "code": "server_busy", "retry_after": 7}}, {"Retry-After": "7"})
            if Fake.scenario == "drop_once" and not Fake.dropped:
                Fake.dropped = True; self.close_connection = True; return   # connection dies before any response
            idem = self.headers.get("Idempotency-Key")
            if idem in Fake.idem:
                return self._send(200, {"id": Fake.idem[idem], "status": "running"}, {"Idempotent-Replayed": "true"})
            jid = "job_%d" % (len(Fake.jobs) + 1)
            Fake.jobs[jid] = len(Fake.jobs) + 1
            Fake.live += 1; Fake.peak = max(Fake.peak, Fake.live)
            Fake.idem[idem] = jid
            return self._send(202, {"id": jid, "status": "queued"}, {"Location": "/v1/jobs/" + jid})
        if self.path == "/v1/chat/completions":
            if Fake.scenario == "422":
                return self._send(422, {"detail": "bad body"})
            blob = ('data: {"choices":[{"delta":{"reasoning_content":"working"}}]}\n\ndata: {"choices":[{"delta":{"content":%s}}]}\n\ndata: [DONE]\n\n' % json.dumps(self._media())).encode()
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            for i in range(0, len(blob), 7):
                self.wfile.write(blob[i:i + 7]); self.wfile.flush()
            return
        self._send(404, {"detail": "nope"})


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.root = "http://127.0.0.1:%d" % cls.srv.server_port
        cls.tmp = tempfile.mkdtemp()
        cls.contract = F.load_contract()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Fake.reset()
        self.sleeps = []
        self._old = (F._sleep, F.POLL_SECONDS)
        F._sleep = self.sleeps.append
        F.POLL_SECONDS = (0.0, 0.0)

    def tearDown(self):
        F._sleep, F.POLL_SECONDS = self._old

    def gen(self, kind="image", **kw):
        Fake.kind = kind
        body = F.build_body(kind, "a frog", "omni-1.2-flash-360p-3s-landscape" if kind == "video" else "gemini-3.1-flash-image-landscape", [], None)
        return F.generate(kind, body, self.tmp, kw.pop("name", None), self.root, KEY, quiet=True, **kw)

    def posts(self, path="/v1/jobs"):
        return [c for c in Fake.calls if c[0] == "POST" and c[1] == path]


class ValidationTests(Base):
    def v(self, *a, **k):
        return F.resolve_video(self.contract, *a, **k)

    def test_config_strips_v1_and_reads_env(self):
        os.environ["FLOW2API_BASE_URL"] = "http://x:8000/proxy/v1/"; os.environ["FLOW2API_API_KEY"] = "k"
        try:
            self.assertEqual(F.load_config(), ("http://x:8000/proxy", "k"))
        finally:
            del os.environ["FLOW2API_BASE_URL"], os.environ["FLOW2API_API_KEY"]

    def test_image_options_come_from_the_registry(self):
        self.assertEqual(F.validate_image(self.contract, "gemini-3.1-flash-image", "9:16", "2K", 0), {"aspectRatio": "9:16", "imageSize": "2K"})
        self.assertEqual(F.validate_image(self.contract, "gemini-3.1-flash-image", "portrait", None, 0)["aspectRatio"], "9:16")
        for model, aspect, size in (("gemini-3.1-flash-image", "21:9", None), ("gemini-3.1-flash-image", None, "8K"), ("nope", None, None), ("omni-1.2-flash", None, None)):
            with self.assertRaises(F.Flow2APIError):
                F.validate_image(self.contract, model, aspect, size, 0)

    def test_omni_12_takes_3_to_15_seconds_in_both_aspects(self):
        for aspect in ("16:9", "9:16"):
            self.assertEqual(self.v("omni-1.2-flash", None, aspect, 15, 3, None)["cfg"], {"durationSeconds": 15, "aspectRatio": aspect, "mode": "auto"})
        with self.assertRaises(F.Flow2APIError) as c:
            self.v("omni-1.2-flash", None, "16:9", 20, 0, None)
        self.assertIn("3, 4, 5", str(c.exception))

    def test_reference_image_limits_follow_the_variant(self):
        self.v("omni-1.2-flash", None, "16:9", 8, 10, None)
        with self.assertRaises(F.Flow2APIError):
            self.v("omni-1.2-flash", None, "16:9", 8, 11, None)
        with self.assertRaises(F.Flow2APIError):
            self.v("omni-1.1-flash", None, "16:9", 8, 8, None)   # Omni 1.1 allows 7

    def test_veo_modes_need_the_right_images_and_never_guess(self):
        self.assertEqual(self.v("veo-3.1-fast", None, None, None, 0, None)["mode"], "t2v")
        with self.assertRaises(F.Flow2APIError) as c:
            self.v("veo-3.1-fast", None, None, None, 1, None)   # i2v or r2v? asking costs nothing, guessing does
        self.assertIn("--mode i2v", str(c.exception))
        self.assertEqual(self.v("veo-3.1-fast", "i2v", None, None, 1, None)["cfg"]["durationSeconds"], 4)
        with self.assertRaises(F.Flow2APIError):
            self.v("veo-3.1-fast", "i2v", None, None, 0, None)
        with self.assertRaises(F.Flow2APIError):
            self.v("veo-3.1-quality", "r2v", None, None, 1, None)   # quality has no r2v
        with self.assertRaises(F.Flow2APIError):
            self.v("veo-3.1-fast", "r2v", None, 6, 1, None)         # r2v is 8 s only

    def test_extend_and_edit_need_a_source_video(self):
        self.assertEqual(self.v("omni-1.2-flash", "extend", "9:16", 5, 0, "MID.1")["cfg"]["mode"], "extend")
        with self.assertRaises(F.Flow2APIError):
            self.v("omni-1.2-flash", "extend", None, 4, 0, None)
        with self.assertRaises(F.Flow2APIError):
            self.v("omni-1.2-flash", "extend", None, 11, 0, "MID")   # extension is 3–10 s
        with self.assertRaises(F.Flow2APIError):
            self.v("omni-1.2-flash", "edit", None, None, 0, "MID")   # edit needs the source length
        self.assertEqual(self.v("omni-1.2-flash", "edit", None, 12, 0, "MID")["cfg"]["durationSeconds"], 12)
        with self.assertRaises(F.Flow2APIError):
            self.v("omni-1.2-flash", None, None, 4, 0, "MID")         # a source without a mode
        with self.assertRaises(F.Flow2APIError):
            self.v("omni-1.2-flash", "auto", None, 4, 0, "MID")
        with self.assertRaises(F.Flow2APIError):
            self.v("omni-1.2-flash", "extend", None, 4, 0, "http://x/y.mp4")   # a media id, not a URL

    def test_omni_frames_take_a_start_frame_and_an_end_frame_up_to_10_seconds(self):
        self.assertEqual(self.v("omni-1.2-flash", "i2v", "16:9", 5, 1, None)["variant"], "omni-1.2-flash-i2v-5s-landscape")
        self.assertEqual(self.v("omni-1.2-flash", "i2v", "9:16", 10, 2, None)["cfg"], {"durationSeconds": 10, "aspectRatio": "9:16", "mode": "i2v"})
        with self.assertRaises(F.Flow2APIError):
            self.v("omni-1.2-flash", "i2v", None, 5, 0, None)    # frames need a start frame
        with self.assertRaises(F.Flow2APIError):
            self.v("omni-1.2-flash", "i2v", None, 5, 3, None)
        self.v("omni-1.2-flash", "i2v", None, 15, 1, None)       # 11-15 s: start frame only
        with self.assertRaises(F.Flow2APIError):
            self.v("omni-1.2-flash", "i2v", None, 12, 2, None)   # Flow has no end-frame key above 10 s

    def test_360p_frames_draft(self):
        plan = F.resolve_draft("16:9", 4, 2, "i2v", None)
        self.assertEqual((plan["model"], plan["mode"], plan["cfg"]), ("omni-1.2-flash-360p-i2v-4s-landscape", "i2v", None))
        for args in (("16:9", 4, 0, "i2v", None), ("16:9", 12, 2, "i2v", None), ("16:9", 4, 3, "i2v", None)):
            with self.assertRaises(F.Flow2APIError):
                F.resolve_draft(*args)

    def test_360p_draft_is_an_explicit_id_without_generation_config(self):
        plan = F.resolve_draft("9:16", 5, 2, None, None)
        self.assertEqual((plan["model"], plan["cfg"]), ("omni-1.2-flash-360p-5s-portrait", None))
        for args in (("16:9", 16, 0, None, None), ("1:1", 5, 0, None, None), ("16:9", 5, 11, None, None), ("16:9", 5, 0, "extend", "M"), ("16:9", 5, 0, None, "M")):
            with self.assertRaises(F.Flow2APIError):
                F.resolve_draft(*args)
        self.assertNotIn("generationConfig", F.build_body("video", "p", plan["model"], [], plan["cfg"]))

    def test_payload_types_refs_and_source_marker(self):
        p = pathlib.Path(self.tmp) / "r.png"; p.write_bytes(PNG)
        b = F.build_body("video", "go", "omni-1.2-flash", [str(p), "https://h/x.png"], {"durationSeconds": 4, "aspectRatio": "16:9", "mode": "auto"}, "MID123", "proj/1")
        parts = b["messages"][0]["content"]
        self.assertEqual(b["generationConfig"], {"videoConfig": {"durationSeconds": 4, "aspectRatio": "16:9", "mode": "auto"}})
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(parts[2]["image_url"]["url"], "https://h/x.png")
        self.assertEqual(parts[3]["image_url"]["url"], "extend://MID123?project=proj%2F1")
        self.assertEqual(F.build_body("image", "x", "m", [], {"imageSize": "2K"})["generationConfig"], {"imageConfig": {"imageSize": "2K"}})
        for bad in ("/nonexistent.png", str(pathlib.Path(self.tmp) / "x.txt")):
            (pathlib.Path(self.tmp) / "x.txt").write_text("t")
            with self.assertRaises(F.Flow2APIError):
                F.build_body("image", "x", "m", [bad], {})
        with self.assertRaises(F.Flow2APIError):
            F.build_body("image", "  ", "m", [], {})

    def test_sse_split_crlf_and_last_frame(self):
        blob = 'data: {"choices":[{"delta":{"reasoning_content":"đang"}}]}\r\n\r\ndata: {"choices":[{"delta":{"content":"A"}}]}\n\ndata: [DONE]'.encode()
        chunks = [blob[i:i + 5] for i in range(0, len(blob), 5)]
        self.assertEqual([e[0] for e in F.parse_sse(chunks)], ["progress", "content", "done"])
        with self.assertRaises(F.Flow2APIError):
            list(F.parse_sse([b'data: {"error":{"message":"quota exceeded"}}\n\n']))

    def test_extract_and_safe_url(self):
        self.assertEqual(F.extract_media("![a](https://h/x.png)")[:2], ("image", "https://h/x.png"))
        self.assertEqual(F.extract_media("```html\n<video src='http://h/v.mp4' data-media-id='M1'></video>\n```"), ("video", "http://h/v.mp4", "M1"))
        with self.assertRaises(F.Flow2APIError):
            F.extract_media("no media here")
        with self.assertRaises(F.Flow2APIError):
            F.safe_url("file:///etc/passwd", "http://h")
        with self.assertRaises(F.Flow2APIError):
            F.safe_url("data:text/html;base64,AAAA", "http://h")

    def test_retry_classification(self):
        self.assertTrue(F._retryable(429, "", "server_busy")); self.assertTrue(F._retryable(None, "reCAPTCHA evaluation failed"))
        self.assertFalse(F._retryable(429, "budget", "credit_budget_exceeded"))
        self.assertFalse(F._retryable(400, "bad mode")); self.assertFalse(F._retryable(403, "x", "model_not_allowed"))


class WireTests(Base):
    def test_image_through_the_job_api_uses_an_idempotency_key_and_records_the_job(self):
        meta = self.gen("image", name="pic")
        post = self.posts()[0]
        self.assertRegex(post[2]["Idempotency-Key"], r"^[0-9a-f]{32}$")
        self.assertIs(post[3]["stream"], False)
        self.assertEqual(json.loads((pathlib.Path(self.tmp) / "pic.job").read_text())["job_id"], "job_1")
        self.assertEqual((meta["job_id"], meta["kind"], pathlib.Path(meta["file"]).suffix), ("job_1", "image", ".png"))
        self.assertEqual(self.posts("/v1/chat/completions"), [])

    def test_video_result_keeps_the_media_id_for_extend(self):
        meta = self.gen("video", name="clip")
        self.assertEqual((meta["media_id"], pathlib.Path(meta["file"]).suffix), ("MID123", ".mp4"))
        self.assertEqual(json.loads((pathlib.Path(self.tmp) / "clip.json").read_text())["media_id"], "MID123")

    def test_server_without_job_api_falls_back_to_streaming(self):
        Fake.reset("legacy")
        meta = self.gen("image", name="old")
        self.assertEqual(len(self.posts("/v1/chat/completions")), 1)
        self.assertIsNone(meta["job_id"]); self.assertTrue(meta["file"].endswith(".png"))
        Fake.reset("legacy")
        with self.assertRaises(F.Flow2APIError):
            self.gen("image", transport="jobs")

    def test_busy_429_waits_the_servers_retry_after_and_keeps_one_key(self):
        Fake.reset("ok", busy_left=2)
        self.gen("image", name="busy")
        keys = {p[2]["Idempotency-Key"] for p in self.posts()}
        self.assertEqual((len(self.posts()), len(keys)), (3, 1))
        self.assertTrue(all(s >= 7 for s in self.sleeps[:2]), self.sleeps)

    def test_exhausted_monthly_budget_is_not_retried(self):
        Fake.reset("budget")
        with self.assertRaises(F.Flow2APIError) as c:
            self.gen("image")
        self.assertEqual(len(self.posts()), 1)
        self.assertIn("hạn mức credit tháng", str(c.exception)); self.assertEqual(c.exception.code, "credit_budget_exceeded")

    def test_model_not_allowed_explains_the_key_limit(self):
        Fake.reset("denied")
        with self.assertRaises(F.Flow2APIError) as c:
            self.gen("image")
        self.assertEqual(len(self.posts()), 1); self.assertIn("check", str(c.exception))

    def test_a_lost_connection_while_submitting_is_retried_with_the_same_key(self):
        Fake.reset("drop_once")
        self.gen("image", name="drop")
        keys = {p[2]["Idempotency-Key"] for p in self.posts()}
        self.assertEqual((len(self.posts()), len(keys)), (2, 1))   # the key lets the server return the first job instead of a second charge

    def test_a_job_failed_by_a_server_restart_is_not_resubmitted(self):
        Fake.reset("restart")
        with self.assertRaises(F.Flow2APIError) as c:
            self.gen("image")
        self.assertEqual(len(self.posts()), 1); self.assertIn("khởi động lại", str(c.exception)); self.assertIn("credit", str(c.exception))

    def test_recaptcha_failure_after_start_is_retried_as_a_new_job(self):
        Fake.reset("captcha_once")
        meta = self.gen("image", name="cap")
        keys = [p[2]["Idempotency-Key"] for p in self.posts()]
        self.assertEqual(len(keys), 2); self.assertNotEqual(keys[0], keys[1])   # the first key would replay the failed job
        self.assertEqual(meta["job_id"], "job_2")

    def test_job_command_fetches_a_job_started_earlier(self):
        Fake.reset("ok", kind="video")
        Fake.jobs["job_9"] = 9
        out = io.StringIO()
        os.environ["FLOW2API_BASE_URL"], os.environ["FLOW2API_API_KEY"] = self.root, KEY
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(F.main(["job", "job_9", "--out", self.tmp, "--name", "resumed"]), 0)
        finally:
            del os.environ["FLOW2API_BASE_URL"], os.environ["FLOW2API_API_KEY"]
        self.assertEqual(json.loads(out.getvalue())["media_id"], "MID123"); self.assertTrue((pathlib.Path(self.tmp) / "resumed.mp4").exists())

    def test_dry_run_sends_nothing_and_needs_no_key(self):
        out = io.StringIO()
        old = (F.CONF_FILE, dict(os.environ))
        F.CONF_FILE = pathlib.Path(self.tmp) / "none"
        os.environ.pop("FLOW2API_API_KEY", None); os.environ["FLOW2API_BASE_URL"] = self.root
        try:
            with contextlib.redirect_stdout(out):
                self.assertEqual(F.main(["video", "a frog", "--duration", "3", "--aspect", "portrait", "--dry-run"]), 0)
        finally:
            F.CONF_FILE = old[0]; os.environ.clear(); os.environ.update(old[1])
        doc = json.loads(out.getvalue())
        self.assertEqual((doc["sent"], Fake.calls), (False, []))
        self.assertEqual(doc["request"]["generationConfig"]["videoConfig"], {"durationSeconds": 3, "aspectRatio": "9:16", "mode": "auto"})

    def batch(self, jobs, *argv, out=None):
        """Run `flow2api.py batch` against the fake server; returns (exit code, stdout)."""
        path = pathlib.Path(self.tmp) / ("jobs-%d.jsonl" % len(list(pathlib.Path(self.tmp).glob("jobs-*.jsonl"))))
        path.write_text("\n".join(json.dumps(dict(j, out=out or self.tmp)) for j in jobs) + "\n", encoding="utf-8")
        text = io.StringIO()
        os.environ["FLOW2API_BASE_URL"], os.environ["FLOW2API_API_KEY"] = self.root, KEY
        try:
            with contextlib.redirect_stdout(text):
                code = F.main(["batch", str(path), *argv])
        finally:
            del os.environ["FLOW2API_BASE_URL"], os.environ["FLOW2API_API_KEY"]
        return code, text.getvalue(), path

    def named(self, prefix, count):
        return [{"kind": "image", "prompt": "p%d" % i, "name": "%s-%d" % (prefix, i)} for i in range(count)]

    def test_batch_runs_jobs_at_the_same_time_but_not_more_than_asked(self):
        code, text, _ = self.batch(self.named("par", 8), "--parallel", "4")
        self.assertEqual(code, 0, text)
        self.assertEqual(len(self.posts()), 8)
        self.assertGreater(Fake.peak, 1)    # a sequential loop would never overlap
        self.assertLessEqual(Fake.peak, 4)

    def test_a_rerun_skips_finished_jobs_and_pays_for_none_twice(self):
        jobs = self.named("rerun", 3)
        code, _, path = self.batch(jobs)
        self.assertEqual((code, len(self.posts())), (0, 3))
        code, text, _ = self.batch(jobs)
        self.assertEqual((code, len(self.posts())), (0, 3), "nothing was sent the second time")
        self.assertIn("3 đã có từ trước", text)
        self.batch(jobs, "--force")
        self.assertEqual(len(self.posts()), 6)

    def test_a_partial_run_only_does_the_missing_jobs(self):
        jobs = self.named("part", 4)
        self.batch(jobs[:2])
        (pathlib.Path(self.tmp) / "part-1.json").unlink()   # one result was lost
        before = len(self.posts())
        code, text, _ = self.batch(jobs)
        self.assertEqual(len(self.posts()) - before, 3)
        self.assertIn("1 đã có từ trước", text)

    def test_batch_dry_run_reports_what_would_run_and_sends_nothing(self):
        self.batch(self.named("dry", 2))
        before = len(Fake.calls)
        code, text, _ = self.batch(self.named("dry", 2) + [{"kind": "image", "prompt": "no name"}], "--dry-run")
        self.assertEqual((code, len(Fake.calls)), (0, before))
        self.assertIn("1 sẽ chạy, 2 đã có kết quả", text)
        self.assertIn("không có \"name\"", text)

    def test_a_spent_budget_stops_the_rest_of_the_batch_instead_of_failing_each_job(self):
        Fake.reset("budget")
        code, text, path = self.batch(self.named("budget", 10), "--parallel", "2")
        self.assertEqual(code, 1)
        self.assertLessEqual(len(self.posts()), 2, "only the first wave was sent")
        self.assertIn("chưa chạy", text)
        self.assertIn("hạn mức credit tháng", text)

    def test_every_result_is_logged_next_to_the_jobs_file(self):
        code, _, path = self.batch(self.named("log", 2))
        lines = [json.loads(l) for l in pathlib.Path(str(path) + ".results.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sorted(l["name"] for l in lines), ["log-0", "log-1"])
        self.assertTrue(all(l["ok"] and l["file"] and l["job_id"] for l in lines))

    def test_an_invalid_job_stops_the_batch_before_anything_is_sent(self):
        jobs = self.named("bad", 3)
        jobs[1]["ref"] = ["/nonexistent/reference.png"]
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code, text, _ = self.batch(jobs)
        self.assertEqual((code, len(self.posts())), (1, 0))
        self.assertIn("job #2 (bad-1)", errors.getvalue())
        self.assertIn("Chưa gửi gì", errors.getvalue())

    def test_preflight_warns_about_retiring_and_invisible_models(self):
        msgs = []
        listing = F.fetch_listing(self.root, KEY)
        F.preflight("veo-3.1-fast", listing, msgs.append)
        F.preflight("omni-1.1-flash", listing, msgs.append)
        self.assertTrue(any("2026-12-05" in m for m in msgs)); self.assertTrue(any("không có trong danh sách" in m for m in msgs))

    def test_check_reports_models_and_job_api(self):
        out = io.StringIO()
        os.environ["FLOW2API_BASE_URL"], os.environ["FLOW2API_API_KEY"] = self.root, KEY
        try:
            with contextlib.redirect_stdout(out):
                self.assertEqual(F.main(["check"]), 0)
        finally:
            del os.environ["FLOW2API_BASE_URL"], os.environ["FLOW2API_API_KEY"]
        text = out.getvalue()
        self.assertIn("omni-1.2-flash", text); self.assertIn("2026-12-05", text); self.assertIn("job API", text); self.assertNotIn(KEY, text)

    def test_errors_do_not_leak_the_key(self):
        for scenario in ("422",):
            Fake.reset(scenario)
            with self.assertRaises(F.Flow2APIError) as c:
                F.post_stream(self.root, KEY, F.build_body("image", "x", "m", [], None), lambda s: None)
            self.assertNotIn(KEY, str(c.exception)); self.assertIn("422", str(c.exception))
        with self.assertRaises(F.Flow2APIError) as c:
            F.post_stream(self.root, "wrong" + KEY, F.build_body("image", "x", "m", [], None), lambda s: None)
        self.assertNotIn("wrong" + KEY, str(c.exception)); self.assertEqual(c.exception.status, 401)

    def test_stream_without_done_is_reported_not_trusted(self):
        class R:
            headers = {"Content-Type": "text/event-stream"}
            def __init__(self): self.d = [b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n', b""]
            def read(self, n): return self.d.pop(0)
        with self.assertRaises(F.Flow2APIError) as c:
            F.post_stream(self.root, KEY, {}, lambda s: None, opener=lambda req, timeout: R())
        self.assertIn("[DONE]", str(c.exception))


if __name__ == "__main__":
    unittest.main(verbosity=1)
