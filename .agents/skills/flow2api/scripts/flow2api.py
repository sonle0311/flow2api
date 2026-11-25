#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flow2API client: generate images and videos from the command line. Python 3.9+, standard library only.

  flow2api.py check                         GET /v1/models (free, read-only)
  flow2api.py models                        print the registered model table (local)
  flow2api.py image  "prompt" [--ref a.png ...] [--model M] [--aspect 9:16] [--size 2K] [--out DIR] [--name N]
  flow2api.py video  "prompt" [--mode t2v|i2v|r2v|auto|extend] [--ref first.png [last.png]] [--extend MEDIA_ID]
                     [--model M] [--aspect 16:9] [--duration 8] [--out DIR] [--name N]
  flow2api.py batch  jobs.jsonl [--parallel N]   one JSON job per line: {"kind":"image","prompt":...,"ref":[...],...}

Config (never printed): FLOW2API_BASE_URL (default http://localhost:8000, no /v1) and FLOW2API_API_KEY,
read from the environment or from ~/.config/flow2api/env (KEY=value lines, chmod 600).
Every image/video call is a paid generation: run it only when the user asked for it. POSTs are never retried
automatically except on HTTP 429 / quota / reCAPTCHA errors (backoff 5, 15, 45 s).
"""
import argparse, base64, json, mimetypes, os, pathlib, random, re, sys, threading, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_ROOT = "http://localhost:8000"
CONF_FILE = pathlib.Path.home() / ".config" / "flow2api" / "env"

IMAGE_MODELS = {m: {"aspect": ["16:9", "9:16", "1:1", "4:3", "3:4"], "size": ["1K", "2K", "4K"]}
                for m in ("gemini-3.0-pro-image", "gemini-3.1-flash-image", "gemini-3.1-flash-lite-image")}
# video: model -> mode -> (aspects, durations, (min_refs, max_refs), default_duration)
_VEO = {"t2v": (["16:9", "9:16"], [4, 6, 8], (0, 0), 8), "i2v": (["16:9", "9:16"], [4, 6], (1, 2), 4),
        "r2v": (["16:9", "9:16"], [8], (1, 3), 8), "extend": (["16:9", "9:16"], [8], (0, 0), 8)}
VIDEO_MODELS = {
    "veo-3.1-fast": dict(_VEO), "veo-3.1-lite": dict(_VEO),
    "veo-3.1-quality": {k: v for k, v in _VEO.items() if k != "r2v"},
    "omni-1.1-flash": {"auto": (["16:9", "9:16"], [4, 6, 8, 10], (0, 3), 8)},
    "omni-1.2-flash": {"auto": (["16:9", "9:16"], list(range(3, 16)), (0, 3), 8)},
}
OMNI12_169_MAX = 10      # omni-1.2-flash: 16:9 allows 3–10 s, 9:16 allows 3–15 s
MAX_PAR = {"image": int(os.environ.get("FLOW2API_MAX_PARALLEL_IMAGE", 9)), "video": int(os.environ.get("FLOW2API_MAX_PARALLEL_VIDEO", 6))}
_SEM = {k: threading.Semaphore(v) for k, v in MAX_PAR.items()}
MAX_REF_BYTES = 20 * 1024 * 1024


class Flow2APIError(Exception):
    def __init__(self, msg, status=None, retryable=False):
        super().__init__(msg); self.status = status; self.retryable = retryable


# ---------------- config ----------------
def load_config():
    vals = {}
    if CONF_FILE.exists():
        for line in CONF_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); vals[k.strip()] = v.strip().strip('"').strip("'")
    root = os.environ.get("FLOW2API_BASE_URL") or vals.get("FLOW2API_BASE_URL") or DEFAULT_ROOT
    key = os.environ.get("FLOW2API_API_KEY") or vals.get("FLOW2API_API_KEY") or ""
    root = root.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return root, key


def redact(text, key):
    return text.replace(key, "***") if key else text


# ---------------- validation ----------------
def validate_image(model, aspect, size, refs):
    if model not in IMAGE_MODELS:
        raise Flow2APIError("Unknown image model %r. Choose one of: %s" % (model, ", ".join(IMAGE_MODELS)))
    spec = IMAGE_MODELS[model]
    if aspect not in spec["aspect"]:
        raise Flow2APIError("aspect %s not registered for %s (allowed %s)" % (aspect, model, spec["aspect"]))
    if size not in spec["size"]:
        raise Flow2APIError("size %s not registered for %s (allowed %s)" % (size, model, spec["size"]))


def video_defaults(model, mode):
    if model not in VIDEO_MODELS:
        raise Flow2APIError("Unknown video model %r. Choose one of: %s" % (model, ", ".join(VIDEO_MODELS)))
    modes = VIDEO_MODELS[model]
    mode = mode or ("auto" if "auto" in modes else "t2v")
    if mode not in modes:
        raise Flow2APIError("mode %s not registered for %s (allowed %s)" % (mode, model, list(modes)))
    return mode, modes[mode][3]


def validate_video(model, mode, aspect, duration, nrefs, extend_id):
    mode, _ = video_defaults(model, mode)
    aspects, durations, (lo, hi), _ = VIDEO_MODELS[model][mode]
    if model == "omni-1.2-flash" and aspect == "16:9":
        durations = [d for d in durations if d <= OMNI12_169_MAX]
    if aspect not in aspects:
        raise Flow2APIError("aspect %s not registered for %s/%s (allowed %s)" % (aspect, model, mode, aspects))
    if duration not in durations:
        raise Flow2APIError("duration %s s not registered for %s/%s/%s (allowed %s)" % (duration, model, mode, aspect, durations))
    if not (lo <= nrefs <= hi):
        raise Flow2APIError("%s/%s takes %d–%d images, got %d" % (model, mode, lo, hi, nrefs))
    if mode == "extend" and not re.fullmatch(r"[A-Za-z0-9_\-:.]+", extend_id or ""):
        raise Flow2APIError("extend needs --extend <Flow mediaGenerationId> kept from an earlier stream (not a chat id or URL)")
    if mode != "extend" and extend_id:
        raise Flow2APIError("--extend only works with --mode extend")
    return mode


# ---------------- request building ----------------
def image_part(ref):
    if re.match(r"^https://", ref):
        return {"type": "image_url", "image_url": {"url": ref}}
    p = pathlib.Path(ref).expanduser()
    if not p.is_file():
        raise Flow2APIError("reference image not found: %s" % ref)
    mime = mimetypes.guess_type(p.name)[0] or ""
    if mime not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        raise Flow2APIError("reference must be PNG/JPEG/WebP/GIF: %s" % ref)
    data = p.read_bytes()
    if len(data) > MAX_REF_BYTES:
        raise Flow2APIError("reference too large (%d MB > 20 MB): %s" % (len(data) >> 20, ref))
    return {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii"))}}


def build_body(kind, prompt, model, refs, cfg, extend_id=None, stream=True):
    if not (prompt or "").strip():
        raise Flow2APIError("prompt is empty")
    parts = [image_part(r) for r in refs]
    if extend_id:
        parts.append({"type": "image_url", "image_url": {"url": "extend://" + extend_id}})
    content = prompt if not parts else [{"type": "text", "text": prompt}] + parts
    gc = {"imageConfig": cfg} if kind == "image" else {"videoConfig": cfg}
    return {"model": model, "messages": [{"role": "user", "content": content}], "stream": stream, "generationConfig": gc}


# ---------------- HTTP + SSE ----------------
def _error_message(status, raw):
    try:
        j = json.loads(raw)
        if isinstance(j, dict):
            if "detail" in j:
                return str(j["detail"])
            e = j.get("error")
            if isinstance(e, dict):
                return str(e.get("message") or e)
            if e:
                return str(e)
    except Exception:
        pass
    return raw[:500]


HINT = {401: "Kiểm tra FLOW2API_API_KEY (generation key).", 403: "Tài khoản/model chưa có quyền.",
        400: "Sai tổ hợp model/mode/ảnh hoặc thiếu prompt.", 422: "Body sai kiểu dữ liệu.",
        429: "Đang bị giới hạn tốc độ.", 502: "Lỗi upstream.", 503: "Máy chủ hết token/không sẵn sàng.", 504: "Upstream quá thời gian."}


def _retryable(status, msg):
    return status == 429 or bool(re.search(r"recaptcha evaluation failed|quota|rate limit", msg or "", re.I))


def parse_sse(chunks):
    """Yield ('progress', text) | ('content', text) | ('media_id', id) | ('done', None) from byte chunks.
    Handles frames split across chunks, CRLF, a last frame without a trailing blank line, and errors inside a 200 stream."""
    buf = ""; dec = __import__("codecs").getincrementaldecoder("utf-8")()
    done = False

    def frame(block):
        nonlocal done
        data = "\n".join(l[5:].lstrip(" ") if l.startswith("data:") else "" for l in re.split(r"\r?\n", block) if l.startswith("data:"))
        if not data:
            return []
        if data.strip() == "[DONE]":
            done = True; return [("done", None)]
        ev = json.loads(data)
        if ev.get("error"):
            e = ev["error"]; m = e.get("message") if isinstance(e, dict) else str(e)
            raise Flow2APIError("lỗi trong stream: %s" % m, retryable=_retryable(None, m))
        out = []
        for ch in ev.get("choices") or []:
            d = ch.get("delta") or {}
            if isinstance(d.get("reasoning_content"), str) and d["reasoning_content"]:
                out.append(("progress", d["reasoning_content"]))
            if isinstance(d.get("content"), str) and d["content"]:
                out.append(("content", d["content"]))
                for mid in re.findall(r'data-media-id\s*=\s*["\']([^"\']+)', d["content"]):
                    out.append(("media_id", mid))
        return out

    for chunk in chunks:
        buf += dec.decode(chunk)
        while True:
            m = re.search(r"\r?\n\r?\n", buf)
            if not m:
                break
            block, buf = buf[:m.start()], buf[m.end():]
            for ev in frame(block):
                yield ev
            if done:
                return
    buf += dec.decode(b"", final=True)
    if buf.strip():
        for ev in frame(buf):
            yield ev


def extract_media(content):
    """Return (kind, url, media_id) from final content: Markdown image or <video src> (maybe in a code fence)."""
    mid = None
    m = re.search(r'data-media-id\s*=\s*["\']([^"\']+)', content)
    if m:
        mid = m.group(1)
    m = re.search(r"!\[[^\]]*\]\(([^\s)]+)\)", content)
    if m:
        return "image", m.group(1), mid
    m = re.search(r"<video\b[^>]*\bsrc\s*=\s*(['\"])(.*?)\1", content, re.I | re.S)
    if m:
        return "video", m.group(2), mid
    raise Flow2APIError("không tìm thấy media trong kết quả: %s" % content[:300])


def safe_url(url, root):
    if url.startswith("data:"):
        if not re.match(r"^data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$", url) or len(url) > 30_000_000:
            raise Flow2APIError("data URI không hợp lệ")
        return url
    full = urllib.parse.urljoin(root + "/", url)
    p = urllib.parse.urlparse(full)
    if p.scheme not in ("http", "https"):
        raise Flow2APIError("scheme không cho phép: %s" % p.scheme)
    return full


def download(url, dest, key, root):
    url = safe_url(url, root)
    if url.startswith("data:"):
        dest.write_bytes(base64.b64decode(url.split(",", 1)[1])); return dest
    req = urllib.request.Request(url)
    if urllib.parse.urlparse(url).netloc == urllib.parse.urlparse(root).netloc:
        req.add_header("Authorization", "Bearer " + key)
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
        while True:
            b = r.read(1 << 16)
            if not b:
                break
            f.write(b)
    return dest


def post_stream(root, key, body, on_progress, timeout=3600, opener=None):
    req = urllib.request.Request(root + "/v1/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "Accept": "text/event-stream"})
    try:
        resp = (opener or urllib.request.urlopen)(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raw = redact(e.read().decode("utf-8", "replace"), key); msg = _error_message(e.code, raw)
        raise Flow2APIError("HTTP %d: %s %s" % (e.code, msg, HINT.get(e.code, "")), e.code, _retryable(e.code, msg))
    ctype = resp.headers.get("Content-Type", "")
    if "text/event-stream" not in ctype:   # server answered without streaming
        j = json.loads(resp.read().decode("utf-8"))
        if j.get("error"):
            raise Flow2APIError(_error_message(200, json.dumps(j)), retryable=_retryable(None, str(j["error"])))
        return j["choices"][0]["message"]["content"], None
    content, mid, saw_done = "", None, False
    for kind, val in parse_sse(iter(lambda: resp.read1(8192) if hasattr(resp, "read1") else resp.read(8192), b"")):
        if kind == "progress":
            on_progress(val)
        elif kind == "content":
            content += val
        elif kind == "media_id":
            mid = val
        elif kind == "done":
            saw_done = True
    if not saw_done:
        raise Flow2APIError("stream kết thúc trước [DONE]; kiểm tra kết quả trên máy chủ trước khi gửi lại")
    if not content.strip():
        raise Flow2APIError("không có nội dung media cuối")
    return content, mid


def generate(kind, body, out_dir, name, root, key, quiet=False):
    """Run one paid generation with the per-kind concurrency limit and 429 backoff. Returns metadata dict."""
    out_dir = pathlib.Path(out_dir).expanduser(); out_dir.mkdir(parents=True, exist_ok=True)
    log = (lambda s: None) if quiet else (lambda s: print("  … " + s.strip()[:160], file=sys.stderr, flush=True))
    delays = [5, 15, 45]
    with _SEM[kind]:
        for attempt in range(len(delays) + 1):
            try:
                content, mid = post_stream(root, key, body, log)
                break
            except Flow2APIError as e:
                if e.retryable and attempt < len(delays):
                    d = delays[attempt] * random.uniform(0.8, 1.3)
                    print("  giới hạn tốc độ/quota, thử lại sau %.0f s (%s)" % (d, e), file=sys.stderr); time.sleep(d); continue
                raise
    mkind, url, mid2 = extract_media(content)
    mid = mid or mid2
    ext = ".mp4" if mkind == "video" else (".png" if ".png" in url.lower() or url.startswith("data:image/png") else ".jpg" if re.search(r"\.jpe?g|image/jpeg", url, re.I) else ".png")
    stem = name or time.strftime("%Y%m%d-%H%M%S") + "-" + kind
    dest = download(url, out_dir / (stem + ext), key, root)
    head = dest.read_bytes()[:12]   # trust the bytes, not the URL: CDN links have no extension
    real = ".jpg" if head[:3] == b"\xff\xd8\xff" else ".png" if head[:8] == b"\x89PNG\r\n\x1a\n" else ".webp" if head[8:12] == b"WEBP" else ".gif" if head[:4] == b"GIF8" else ext
    if mkind == "image" and real != dest.suffix:
        dest = dest.rename(dest.with_suffix(real))
    meta = {"file": str(dest), "kind": mkind, "model": body["model"], "generationConfig": body["generationConfig"],
            "prompt": body["messages"][0]["content"] if isinstance(body["messages"][0]["content"], str) else body["messages"][0]["content"][0]["text"],
            "media_id": mid, "source_url": url if not url.startswith("data:") else "data-uri", "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (out_dir / (stem + ".json")).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


# ---------------- commands ----------------
def cmd_check(a):
    root, key = load_config()
    print("root:", root, "| key:", "đã đặt" if key else "CHƯA ĐẶT")
    if not key:
        print("Đặt FLOW2API_API_KEY trong môi trường hoặc %s rồi chạy lại." % CONF_FILE); return 2
    for path in ("/v1/models", "/v1/models/aliases"):
        req = urllib.request.Request(root + path, headers={"Authorization": "Bearer " + key})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    j = json.loads(r.read().decode("utf-8"))
                ids = [m.get("id") for m in j.get("data", [])] if isinstance(j, dict) else []
                print("%s: OK, %d mục%s" % (path, len(ids), (": " + ", ".join(ids[:12]) + (" …" if len(ids) > 12 else "")) if ids else ""))
                break
            except urllib.error.HTTPError as e:
                print("%s: HTTP %d %s" % (path, e.code, redact(_error_message(e.code, e.read().decode("utf-8", "replace")), key))); break
            except Exception as e:
                if attempt == 2:
                    print("%s: lỗi kết nối: %s" % (path, e))
                time.sleep(1 + attempt)
    return 0


def cmd_models(a):
    print("ẢNH (aspect × size; ảnh tham chiếu 0–nhiều):")
    for m, s in IMAGE_MODELS.items():
        print("  %-28s aspect %s | size %s" % (m, ",".join(s["aspect"]), ",".join(s["size"])))
    print("VIDEO (mode: aspect | giây | số ảnh):")
    for m, modes in VIDEO_MODELS.items():
        for mode, (asp, dur, (lo, hi), dflt) in modes.items():
            extra = " (16:9 tối đa %d s)" % OMNI12_169_MAX if m == "omni-1.2-flash" else ""
            print("  %-16s %-6s %s | %s s%s | %d–%d ảnh | mặc định %d s" % (m, mode, ",".join(asp), ",".join(map(str, dur)), extra, lo, hi, dflt))
    print("Giới hạn song song: ảnh %d, video %d (FLOW2API_MAX_PARALLEL_IMAGE/VIDEO)" % (MAX_PAR["image"], MAX_PAR["video"]))
    return 0


def job_image(j):
    model = j.get("model") or "gemini-3.1-flash-image"; aspect = j.get("aspect") or "16:9"; size = j.get("size") or "1K"
    refs = j.get("ref") or []
    validate_image(model, aspect, size, refs)
    return "image", build_body("image", j["prompt"], model, refs, {"aspectRatio": aspect, "imageSize": size})


def job_video(j):
    model = j.get("model") or "veo-3.1-fast"
    mode, dflt = video_defaults(model, j.get("mode"))
    aspect = j.get("aspect") or "16:9"; duration = int(j.get("duration") or dflt); refs = j.get("ref") or []
    mode = validate_video(model, mode, aspect, duration, len(refs), j.get("extend"))
    return "video", build_body("video", j["prompt"], model, refs, {"durationSeconds": duration, "aspectRatio": aspect, "mode": mode}, j.get("extend"))


def run_one(j, root, key, quiet=False):
    kind, body = (job_image if j.get("kind", "image") == "image" else job_video)(j)
    return generate(kind, body, j.get("out") or "flow2api-out", j.get("name"), root, key, quiet)


def cmd_gen(a, kind):
    root, key = load_config()
    if not key:
        print("Thiếu FLOW2API_API_KEY (môi trường hoặc %s)." % CONF_FILE, file=sys.stderr); return 2
    j = {"kind": kind, "prompt": a.prompt, "model": a.model, "aspect": a.aspect, "ref": a.ref or [], "out": a.out, "name": a.name}
    if kind == "image":
        j["size"] = a.size
    else:
        j.update(mode=a.mode, duration=a.duration, extend=a.extend)
    if a.prompt_file:
        j["prompt"] = pathlib.Path(a.prompt_file).read_text(encoding="utf-8")
    try:
        meta = run_one(j, root, key)
    except Flow2APIError as e:
        print("LỖI: " + redact(str(e), key), file=sys.stderr); return 1
    print(json.dumps(meta, ensure_ascii=False, indent=1)); return 0


def cmd_batch(a):
    root, key = load_config()
    if not key:
        print("Thiếu FLOW2API_API_KEY.", file=sys.stderr); return 2
    jobs = [json.loads(l) for l in pathlib.Path(a.jobs).read_text(encoding="utf-8").splitlines() if l.strip()]
    for j in jobs:   # validate everything before sending anything
        (job_image if j.get("kind", "image") == "image" else job_video)(j)
    results = [None] * len(jobs)

    def work(i):
        time.sleep(0.4 * i)   # stagger submissions
        try:
            results[i] = run_one(jobs[i], root, key, quiet=True); print("[%d/%d] xong: %s" % (i + 1, len(jobs), results[i]["file"]), flush=True)
        except Exception as e:
            results[i] = {"error": redact(str(e), key)}; print("[%d/%d] lỗi: %s" % (i + 1, len(jobs), results[i]["error"]), flush=True)
    with ThreadPoolExecutor(max_workers=max(1, min(a.parallel, MAX_PAR["image"] + MAX_PAR["video"]))) as ex:
        list(ex.map(work, range(len(jobs))))
    ok = sum(1 for r in results if r and "error" not in r)
    print("Hoàn tất %d/%d." % (ok, len(jobs)))
    return 0 if ok == len(jobs) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Flow2API: tạo ảnh/video (mỗi lệnh image/video là một lần tạo tính phí)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check"); sub.add_parser("models")
    for kind in ("image", "video"):
        p = sub.add_parser(kind)
        p.add_argument("prompt", nargs="?", default="")
        p.add_argument("--prompt-file"); p.add_argument("--model"); p.add_argument("--aspect")
        p.add_argument("--ref", action="append", help="ảnh tham chiếu (file cục bộ hoặc https), lặp lại theo thứ tự")
        p.add_argument("--out", default="flow2api-out"); p.add_argument("--name")
        if kind == "image":
            p.add_argument("--size")
        else:
            p.add_argument("--mode", choices=["t2v", "i2v", "r2v", "auto", "extend"]); p.add_argument("--duration", type=int)
            p.add_argument("--extend", help="Flow mediaGenerationId đã giữ từ lần tạo trước")
    p = sub.add_parser("batch"); p.add_argument("jobs"); p.add_argument("--parallel", type=int, default=3)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        return cmd_check(a)
    if a.cmd == "models":
        return cmd_models(a)
    if a.cmd == "batch":
        return cmd_batch(a)
    return cmd_gen(a, a.cmd)


if __name__ == "__main__":
    sys.exit(main())
