# -*- coding: utf-8 -*-
"""Mock tests for flow2api.py. No paid generation: a local fake server answers every request.
Run: python3 test_flow2api.py"""
import io, json, os, pathlib, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import flow2api as F

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000")


class Fake(BaseHTTPRequestHandler):
    mode = "sse"; last_body = None; last_auth = None

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/files/"):
            self.send_response(200); self.send_header("Content-Type", "image/png"); self.end_headers(); self.wfile.write(PNG); return
        if self.headers.get("Authorization") != "Bearer good":
            self.send_response(401); self.end_headers(); self.wfile.write(b'{"detail":"Invalid API key"}'); return
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"data": [{"id": "gemini-3.1-flash-image"}]}).encode())

    def do_POST(self):
        Fake.last_auth = self.headers.get("Authorization")
        Fake.last_body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        m = Fake.mode
        if m == "401":
            self.send_response(401); self.end_headers(); self.wfile.write(b'{"detail":"Invalid API key"}'); return
        if m == "422":
            self.send_response(422); self.end_headers(); self.wfile.write(b'{"detail":"durationSeconds must be integer"}'); return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        if m == "sse_error":
            self.wfile.write(b'data: {"error":{"message":"Generation failed"}}\n\n'); return
        if m == "no_done":
            self.wfile.write(b'data: {"choices":[{"delta":{"reasoning_content":"working"}}]}\n\n'); return
        frames = [b'data: {"choices":[{"delta":{"reasoning_content":"\xc4\x91ang t\xe1\xba\xa1o"}}]}\r\n\r\n',
                  b'data: {"choices":[{"delta":{"content":"![img](/files/a.png)"}}]}\n\n', b"data: [DONE]"]
        if m == "video":
            frames[1] = b'data: {"choices":[{"delta":{"content":"```html\\n<video src=\\"/files/v.mp4\\" data-media-id=\\"MID123\\" controls></video>\\n```"}}]}\n\n'
        blob = b"".join(frames)
        for i in range(0, len(blob), 7):   # split frames and UTF-8 across chunks
            self.wfile.write(blob[i:i + 7]); self.wfile.flush()


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.root = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        cls.tmp = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_config_strips_v1_and_reads_env(self):
        os.environ["FLOW2API_BASE_URL"] = "http://x:8000/proxy/v1/"; os.environ["FLOW2API_API_KEY"] = "k"
        try:
            self.assertEqual(F.load_config(), ("http://x:8000/proxy", "k"))
        finally:
            del os.environ["FLOW2API_BASE_URL"], os.environ["FLOW2API_API_KEY"]

    def test_validation(self):
        F.validate_image("gemini-3.1-flash-image", "9:16", "2K", [])
        with self.assertRaises(F.Flow2APIError):
            F.validate_image("gemini-3.1-flash-image", "21:9", "1K", [])
        self.assertEqual(F.validate_video("veo-3.1-fast", "i2v", "9:16", 6, 2, None), "i2v")
        for bad in [("veo-3.1-quality", "r2v", "16:9", 8, 1, None), ("veo-3.1-fast", "i2v", "16:9", 8, 1, None),
                    ("veo-3.1-fast", "t2v", "16:9", 8, 1, None), ("omni-1.2-flash", "auto", "16:9", 12, 0, None),
                    ("veo-3.1-fast", "extend", "16:9", 8, 0, None), ("omni-1.1-flash", "auto", "16:9", 8, 4, None)]:
            with self.assertRaises(F.Flow2APIError, msg=str(bad)):
                F.validate_video(*bad)
        self.assertEqual(F.validate_video("omni-1.2-flash", "auto", "9:16", 15, 3, None), "auto")

    def test_payload_types_and_refs(self):
        p = pathlib.Path(self.tmp) / "r.png"; p.write_bytes(PNG)
        k, body = F.job_video({"kind": "video", "prompt": "x", "model": "veo-3.1-lite", "mode": "i2v", "ref": [str(p)]})
        vc = body["generationConfig"]["videoConfig"]
        self.assertEqual((vc["durationSeconds"], vc["mode"], vc["aspectRatio"]), (4, "i2v", "16:9"))
        self.assertIsInstance(vc["durationSeconds"], int); self.assertNotIn("imageConfig", body["generationConfig"])
        self.assertTrue(body["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        k, body = F.job_video({"kind": "video", "prompt": "go on", "mode": "extend", "extend": "MID123"})
        self.assertEqual(body["messages"][0]["content"][-1]["image_url"]["url"], "extend://MID123")
        with self.assertRaises(F.Flow2APIError):
            F.build_body("image", "  ", "gemini-3.1-flash-image", [], {})

    def test_sse_split_crlf_and_last_frame(self):
        blob = 'data: {"choices":[{"delta":{"reasoning_content":"đang"}}]}\r\n\r\ndata: {"choices":[{"delta":{"content":"A"}}]}\n\ndata: [DONE]'.encode()
        evs = list(F.parse_sse(blob[i:i + 3] for i in range(0, len(blob), 3)))
        self.assertEqual(evs, [("progress", "đang"), ("content", "A"), ("done", None)])
        with self.assertRaises(F.Flow2APIError):
            list(F.parse_sse([b'data: {"error":{"message":"quota exceeded"}}\n\n']))

    def test_extract_and_safe_url(self):
        self.assertEqual(F.extract_media("![a](https://h/x.png)")[:2], ("image", "https://h/x.png"))
        k, u, mid = F.extract_media('```html\n<video src="/c/v.mp4" data-media-id="M1"></video>\n```')
        self.assertEqual((k, u, mid), ("video", "/c/v.mp4", "M1"))
        with self.assertRaises(F.Flow2APIError):
            F.safe_url("javascript:alert(1)", "http://h")
        with self.assertRaises(F.Flow2APIError):
            F.safe_url("data:text/html;base64,AAAA", "http://h")

    def test_end_to_end_image_and_video(self):
        Fake.mode = "sse"
        meta = F.run_one({"kind": "image", "prompt": "a lake", "out": self.tmp, "name": "img"}, self.root, "good", quiet=True)
        self.assertEqual(pathlib.Path(meta["file"]).read_bytes(), PNG); self.assertEqual(Fake.last_auth, "Bearer good")
        self.assertTrue(Fake.last_body["stream"])
        Fake.mode = "video"
        meta = F.run_one({"kind": "video", "prompt": "pan", "out": self.tmp, "name": "vid"}, self.root, "good", quiet=True)
        self.assertEqual(meta["media_id"], "MID123"); self.assertTrue(meta["file"].endswith(".mp4"))

    def test_errors_do_not_leak_key(self):
        for mode, code in (("401", 401), ("422", 422)):
            Fake.mode = mode
            with self.assertRaises(F.Flow2APIError) as c:
                F.run_one({"kind": "image", "prompt": "x", "out": self.tmp}, self.root, "secret-key", quiet=True)
            self.assertEqual(c.exception.status, code); self.assertNotIn("secret-key", str(c.exception))
        Fake.mode = "sse_error"
        with self.assertRaises(F.Flow2APIError):
            F.run_one({"kind": "image", "prompt": "x", "out": self.tmp}, self.root, "good", quiet=True)
        Fake.mode = "no_done"
        with self.assertRaises(F.Flow2APIError) as c:
            F.run_one({"kind": "image", "prompt": "x", "out": self.tmp}, self.root, "good", quiet=True)
        self.assertIn("[DONE]", str(c.exception))

    def test_retryable_classification(self):
        self.assertTrue(F._retryable(429, "")); self.assertTrue(F._retryable(None, "reCAPTCHA evaluation failed"))
        self.assertFalse(F._retryable(400, "bad mode")); self.assertFalse(F._retryable(401, "Invalid API key"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
