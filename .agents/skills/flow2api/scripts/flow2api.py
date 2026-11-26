#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flow2API client: generate images and videos from the command line. Python 3.9+, standard library only.

  flow2api.py check                         free: key, models this key may use, retiring models, jobs API
  flow2api.py models                        print the model table (from references/contract.json)
  flow2api.py image  "prompt" [--ref a.png ...] [--model M] [--aspect 9:16] [--size 2K] [--out DIR] [--name N]
  flow2api.py video  "prompt" [--model omni-1.2-flash] [--mode auto|t2v|i2v|r2v|extend|edit] [--draft]
                     [--ref first.png [last.png]] [--source MEDIA_ID [--source-project ID]]
                     [--aspect 16:9] [--duration 8] [--out DIR] [--name N]
  flow2api.py job   JOB_ID [--out DIR] [--name N]   fetch a job started earlier (after a disconnect)
  flow2api.py jobs  [--limit 20]                    list this key's recent jobs
  flow2api.py batch jobs.jsonl [--parallel N]       one JSON job per line: {"kind":"image","prompt":...,"ref":[...],...}

image/video/batch accept --dry-run: validate and print the request without sending anything (free).

Config (never printed): FLOW2API_BASE_URL (default http://localhost:8000, no /v1) and FLOW2API_API_KEY,
read from the environment or from ~/.config/flow2api/env (KEY=value lines, chmod 600).

Every image/video call is a paid generation: run it only when the user asked for it. The job API
(POST /v1/jobs with an Idempotency-Key) is used when the server has it, so a dropped connection or a
retry never pays twice; older servers fall back to the streaming endpoint. HTTP 429 is retried after the
server's Retry-After, except credit_budget_exceeded (the monthly budget is spent: stop).
"""
import argparse, base64, codecs, json, mimetypes, os, pathlib, random, re, sys, threading, time, urllib.error, urllib.parse, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor

DEFAULT_ROOT = "http://localhost:8000"
CONF_FILE = pathlib.Path.home() / ".config" / "flow2api" / "env"
CONTRACT_FILE = pathlib.Path(__file__).resolve().parent.parent / "references" / "contract.json"
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image"
DEFAULT_VIDEO_MODEL = "omni-1.2-flash"
DRAFT_FAMILY = "omni-1.2-flash"           # 360p drafts are explicit ids omni-1.2-flash-360p-{N}s-{landscape|portrait}
DRAFT_DURATIONS = list(range(3, 16))
DRAFT_MAX_REFS = 10
DEFAULT_PARALLEL = 6        # batch: how many generations run at once (the gateway spreads them over its accounts)
FRAMES_END_MAX_SECONDS = 10   # Omni 1.2 frames: an end frame (2 images) exists for 3-10 s, 11-15 s take a start frame only
ASPECT_WORDS = {"landscape": "16:9", "portrait": "9:16", "square": "1:1", "four-three": "4:3", "three-four": "3:4"}
MAX_PAR = {"image": int(os.environ.get("FLOW2API_MAX_PARALLEL_IMAGE", 9)), "video": int(os.environ.get("FLOW2API_MAX_PARALLEL_VIDEO", 6))}
_SEM = {k: threading.Semaphore(v) for k, v in MAX_PAR.items()}
MAX_REF_BYTES = 20 * 1024 * 1024
MAX_BUSY_RETRIES = 4          # HTTP 429 and other pre-submission rejections
MAX_CAPTCHA_RETRIES = 3       # reCAPTCHA / quota failures reported after a job started
POLL_SECONDS = (2.0, 15.0)    # clamp for the server's Retry-After
RETRY_TEXT = re.compile(r"recaptcha evaluation failed|quota|rate limit", re.I)


def _sleep(seconds):
    time.sleep(seconds)


class Flow2APIError(Exception):
    def __init__(self, msg, status=None, retryable=False, code=None, retry_after=None, after_submit=False):
        super().__init__(msg)
        self.status, self.retryable, self.code, self.retry_after, self.after_submit = status, retryable, code, retry_after, after_submit


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


def load_contract(path=None):
    """Model registry generated from the gateway (scripts/sync_contract.py): {family id: contract}."""
    return {c["id"]: c for c in json.loads(pathlib.Path(path or CONTRACT_FILE).read_text(encoding="utf-8"))}


# ---------------- validation ----------------
def _aspect(value, default):
    return ASPECT_WORDS.get(value, value) if value else default


def validate_image(contract, model, aspect, size, nrefs):
    fam = contract.get(model)
    if not fam or fam["type"] != "image":
        raise Flow2APIError("Unknown image model %r. Choose one of: %s" % (model, ", ".join(k for k, v in contract.items() if v["type"] == "image")))
    aspect = _aspect(aspect, fam["defaults"]["aspectRatio"]); size = size or fam["defaults"]["imageSize"]
    for name, value in (("aspectRatio", aspect), ("imageSize", size)):
        allowed = fam["parameters"][name]["values"]
        if value not in allowed:
            raise Flow2APIError("%s %s not registered for %s (allowed %s)" % (name, value, model, allowed))
    return {"aspectRatio": aspect, "imageSize": size}


def resolve_video(contract, model, mode, aspect, duration, nrefs, source):
    """Check a video request against the registry. Returns {model, mode, cfg, variant}; raises before anything is sent."""
    fam = contract.get(model)
    if not fam or fam["type"] != "video":
        raise Flow2APIError("Unknown video model %r. Choose one of: %s" % (model, ", ".join(k for k, v in contract.items() if v["type"] == "video")))
    modes = fam["parameters"]["mode"]["values"]
    if mode is None:
        if source:
            raise Flow2APIError("--source needs --mode extend or edit")
        if "auto" in modes:
            mode = "auto"
        elif nrefs and "t2v" in modes:
            raise Flow2APIError("%s with images needs --mode i2v (first/last frame) or r2v (references)" % model)
        else:
            mode = "t2v"
    if mode not in modes:
        raise Flow2APIError("mode %s not registered for %s (allowed %s)" % (mode, model, modes))
    defaults = fam["mode_defaults"][mode]
    if mode == "edit" and not duration:
        raise Flow2APIError("edit needs --duration <length of the source video in seconds>")
    aspect = _aspect(aspect, defaults["aspectRatio"]); duration = int(duration or defaults["durationSeconds"])
    variants = [v for v in fam["variants"] if v["mode"] == mode]
    aspects = sorted({v["aspectRatio"] for v in variants})
    if aspect not in aspects:
        raise Flow2APIError("aspect %s not registered for %s/%s (allowed %s)" % (aspect, model, mode, aspects))
    durations = sorted({v["durationSeconds"] for v in variants if v["aspectRatio"] == aspect})
    if duration not in durations:
        raise Flow2APIError("duration %s s not registered for %s/%s/%s (allowed %s)" % (duration, model, mode, aspect, durations))
    variant = next(v for v in variants if v["aspectRatio"] == aspect and v["durationSeconds"] == duration)
    lo, hi = variant["min_images"], variant["max_images"]
    if nrefs < lo or (hi is not None and nrefs > hi):
        raise Flow2APIError("%s/%s takes %d–%s images, got %d" % (model, mode, lo, "many" if hi is None else hi, nrefs))
    if mode in ("extend", "edit"):
        if not re.fullmatch(r"[A-Za-z0-9_\-:.]+", source or ""):
            raise Flow2APIError("%s needs --source <Flow media id> (the media_id of an earlier video, not a URL)" % mode)
    elif source:
        raise Flow2APIError("--source only works with --mode extend or edit")
    return {"model": model, "mode": mode, "variant": variant["id"], "cfg": {"durationSeconds": duration, "aspectRatio": aspect, "mode": mode}}


def resolve_draft(aspect, duration, nrefs, mode, source):
    """Omni 1.2 360p drafts (a third of the credits) are requested by explicit id, without generationConfig."""
    if mode not in (None, "auto", "i2v") or source:
        raise Flow2APIError("--draft (360p) only supports generation (mode auto) and frames (mode i2v), not extend/edit")
    aspect = _aspect(aspect, "16:9"); duration = int(duration or 8)
    if aspect not in ("16:9", "9:16"):
        raise Flow2APIError("aspect %s not registered for 360p drafts (allowed ['16:9', '9:16'])" % aspect)
    if duration not in DRAFT_DURATIONS:
        raise Flow2APIError("duration %s s not registered for 360p drafts (allowed %s)" % (duration, DRAFT_DURATIONS))
    side = "landscape" if aspect == "16:9" else "portrait"
    if mode == "i2v":
        top = 2 if duration <= FRAMES_END_MAX_SECONDS else 1
        if not 1 <= nrefs <= top:
            raise Flow2APIError("360p frames take 1–%d images (an end frame only up to %d s), got %d" % (top, FRAMES_END_MAX_SECONDS, nrefs))
        model = "%s-360p-i2v-%ds-%s" % (DRAFT_FAMILY, duration, side)
        return {"model": model, "mode": "i2v", "variant": model, "cfg": None}
    if nrefs > DRAFT_MAX_REFS:
        raise Flow2APIError("360p drafts take 0–%d images, got %d" % (DRAFT_MAX_REFS, nrefs))
    model = "%s-360p-%ds-%s" % (DRAFT_FAMILY, duration, side)
    return {"model": model, "mode": "auto", "variant": model, "cfg": None}


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


def build_body(kind, prompt, model, refs, cfg, source=None, source_project=None, stream=True):
    """cfg is the generationConfig payload (imageConfig / videoConfig contents), or None for explicit variant ids."""
    if not (prompt or "").strip():
        raise Flow2APIError("prompt is empty")
    parts = [image_part(r) for r in refs]
    if source:
        parts.append({"type": "image_url", "image_url": {"url": "extend://" + source + ("?project=" + urllib.parse.quote(source_project, safe="") if source_project else "")}})
    content = prompt if not parts else [{"type": "text", "text": prompt}] + parts
    body = {"model": model, "messages": [{"role": "user", "content": content}], "stream": stream}
    if cfg:
        body["generationConfig"] = {"imageConfig" if kind == "image" else "videoConfig": cfg}
    return body


# ---------------- HTTP ----------------
def _error_fields(raw):
    """(message, code, retry_after) from an error body in any of the shapes the gateway uses."""
    try:
        j = json.loads(raw)
    except Exception:
        return raw[:500], None, None
    if isinstance(j, dict):
        e = j.get("error")
        if isinstance(e, dict):
            return str(e.get("message") or e), e.get("code"), e.get("retry_after")
        if "detail" in j:
            d = j["detail"]
            return (str(d.get("message") or d) if isinstance(d, dict) else str(d)), (d.get("code") if isinstance(d, dict) else None), None
        if e:
            return str(e), None, None
    return raw[:500], None, None


def _error_message(status, raw):
    return _error_fields(raw)[0]


HINT = {401: "Kiểm tra FLOW2API_API_KEY.", 403: "Key hoặc tài khoản chưa có quyền với model này.",
        400: "Sai tổ hợp model/mode/ảnh, thiếu prompt, hoặc model đã bị Flow gỡ.", 422: "Body sai kiểu dữ liệu.",
        429: "Đang bị giới hạn.", 502: "Lỗi upstream.", 503: "Không tài khoản nào phục vụ được model này.", 504: "Upstream quá thời gian."}
CODE_HINT = {
    "credit_budget_exceeded": "Key đã dùng hết hạn mức credit tháng; không thử lại, báo người dùng (reset ngày 1 tháng sau, UTC).",
    "model_not_allowed": "Key này không được dùng model đó; chạy `check` để xem danh sách được phép.",
    "idempotency_key_reused": "Idempotency-Key đã dùng với body khác.",
}


def _retryable(status, msg, code=None):
    if code == "credit_budget_exceeded":
        return False
    return status == 429 or bool(RETRY_TEXT.search(msg or ""))


def api_error(status, raw, headers, key, after_submit=False):
    msg, code, retry_after = _error_fields(redact(raw, key))
    try:
        retry_after = float(headers.get("Retry-After") if headers is not None and headers.get("Retry-After") else retry_after)
    except (TypeError, ValueError):
        retry_after = None
    hint = CODE_HINT.get(code) or HINT.get(status, "")
    return Flow2APIError("HTTP %d: %s %s" % (status, msg, hint), status, _retryable(status, msg, code), code, retry_after, after_submit)


def http_json(root, key, method, path, body=None, headers=None, timeout=60, opener=None):
    """One JSON request. Returns (status, response headers, parsed body); raises Flow2APIError on HTTP errors and network failures."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"Authorization": "Bearer " + key, "Accept": "application/json"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    req = urllib.request.Request(root + path, data=data, method=method, headers=hdrs)
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return r.status, r.headers, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raise api_error(e.code, e.read().decode("utf-8", "replace"), e.headers, key)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Flow2APIError("lỗi kết nối: %s" % redact(str(e), key), retryable=False, code="network")


def with_retries(fn, log, attempts=MAX_BUSY_RETRIES):
    """Retry pre-submission rejections after the server's Retry-After (or 5, 15, 45 s)."""
    for n in range(attempts):
        try:
            return fn()
        except Flow2APIError as e:
            if not e.retryable or e.after_submit or n == attempts - 1:
                raise
            wait = (e.retry_after if e.retry_after is not None else (5, 15, 45)[min(n, 2)])
            wait = min(max(wait, 0), 300) * random.uniform(1.0, 1.2)
            log("bị giới hạn (%s); thử lại sau %.0f s" % (e.code or e.status, wait)); _sleep(wait)


# ---------------- SSE (servers without /v1/jobs) ----------------
def parse_sse(chunks):
    """Yield ('progress', text) | ('content', text) | ('media_id', id) | ('done', None) from byte chunks.
    Handles frames split across chunks, CRLF, a last frame without a trailing blank line, and errors inside a 200 stream."""
    buf = ""; dec = codecs.getincrementaldecoder("utf-8")()
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
            raise Flow2APIError("lỗi trong stream: %s" % m, retryable=_retryable(None, m), code=e.get("code") if isinstance(e, dict) else None)
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


def post_stream(root, key, body, on_progress, timeout=3600, opener=None):
    req = urllib.request.Request(root + "/v1/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "Accept": "text/event-stream"})
    try:
        resp = (opener or urllib.request.urlopen)(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise api_error(e.code, e.read().decode("utf-8", "replace"), e.headers, key)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Flow2APIError("lỗi kết nối: %s" % redact(str(e), key), code="network")
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


# ---------------- jobs ----------------
def poll_delay(headers):
    try:
        wait = float(headers.get("Retry-After"))
    except (TypeError, ValueError):
        wait = POLL_SECONDS[0]
    return min(max(wait, POLL_SECONDS[0]), POLL_SECONDS[1])


def job_failure(doc):
    err = doc.get("error") or {}
    msg, code = str(err.get("message") or "job failed"), err.get("code")
    if code == "server_restarted":
        return Flow2APIError("job %s bị dừng vì server khởi động lại; credit có thể đã bị trừ: xem `jobs` hoặc trang quản trị trước khi gửi lại" % doc.get("id"), code=code, after_submit=True)
    return Flow2APIError("job lỗi: %s%s" % (msg, " (%s)" % code if code else ""), err.get("status_code"), _retryable(None, msg, code), code, after_submit=True)


def job_content(doc):
    try:
        return doc["result"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return doc.get("output_url") or ""


def poll_job(root, key, job_id, log, timeout=3600):
    start, last, misses = time.monotonic(), None, 0
    while True:
        try:
            _, headers, doc = http_json(root, key, "GET", "/v1/jobs/" + urllib.parse.quote(job_id), timeout=60)
            misses = 0
        except Flow2APIError as e:
            if e.code != "network" or misses >= 4:   # polling only reads, so a flaky connection is safe to ride out
                raise
            misses += 1; headers, doc = {}, {"status": last}; _sleep(POLL_SECONDS[0] * misses)
        status = doc.get("status")
        if status != last:
            log("job %s: %s" % (job_id, status)); last = status
        if status == "succeeded":
            return doc
        if status == "failed":
            raise job_failure(doc)
        if status == "canceled":
            raise Flow2APIError("job %s đã bị huỷ" % job_id)
        if time.monotonic() - start > timeout:
            raise Flow2APIError("quá thời gian chờ; job %s vẫn có thể đang chạy trên server, lấy kết quả sau bằng: flow2api.py job %s" % (job_id, job_id))
        _sleep(poll_delay(headers))


def run_job(root, key, body, log, timeout, on_submit=None):
    """Submit through /v1/jobs and wait. The Idempotency-Key makes a repeated submission return the same job."""
    idem = uuid.uuid4().hex
    body = dict(body, stream=False)
    def submit():
        try:
            return http_json(root, key, "POST", "/v1/jobs", body, {"Idempotency-Key": idem})
        except Flow2APIError as e:
            if e.code == "network":
                e.retryable = True   # the same Idempotency-Key makes a repeated POST return the first job
            raise
    status, headers, doc = with_retries(submit, log)
    if status == 200 and headers.get("Idempotent-Replayed"):
        log("server nhận ra yêu cầu đã gửi: dùng lại job cũ, không trả phí lần hai")
    job_id = doc["id"]
    if on_submit:
        on_submit(job_id)
    log("đã nhận job %s" % job_id)
    try:
        doc = poll_job(root, key, job_id, log, timeout)
    except KeyboardInterrupt:
        raise Flow2APIError("đã dừng chờ; job %s vẫn chạy trên server, lấy kết quả bằng: flow2api.py job %s" % (job_id, job_id))
    return job_content(doc), None, job_id


# ---------------- media ----------------
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


def save_media(content, out_dir, stem, root, key, meta, mid=None):
    """Download the media named in content and write <stem>.json next to it. Returns the metadata dict."""
    mkind, url, mid2 = extract_media(content)
    mid = mid or mid2
    ext = ".mp4" if mkind == "video" else (".png" if ".png" in url.lower() or url.startswith("data:image/png") else ".jpg" if re.search(r"\.jpe?g|image/jpeg", url, re.I) else ".png")
    dest = download(url, out_dir / (stem + ext), key, root)
    head = dest.read_bytes()[:12]   # trust the bytes, not the URL: CDN links have no extension
    real = ".jpg" if head[:3] == b"\xff\xd8\xff" else ".png" if head[:8] == b"\x89PNG\r\n\x1a\n" else ".webp" if head[8:12] == b"WEBP" else ".gif" if head[:4] == b"GIF8" else ext
    if mkind == "image" and real != dest.suffix:
        dest = dest.rename(dest.with_suffix(real))
    meta = dict(meta, file=str(dest), kind=mkind, media_id=mid, source_url=url if not url.startswith("data:") else "data-uri", time=time.strftime("%Y-%m-%dT%H:%M:%S"))
    (out_dir / (stem + ".json")).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def _prompt_of(body):
    c = body["messages"][0]["content"]
    return c if isinstance(c, str) else c[0]["text"]


def generate(kind, body, out_dir, name, root, key, quiet=False, transport="auto", timeout=3600):
    """Run one paid generation with the per-kind concurrency limit. Returns the metadata dict."""
    out_dir = pathlib.Path(out_dir).expanduser(); out_dir.mkdir(parents=True, exist_ok=True)
    log = (lambda s: None) if quiet else (lambda s: print("  … " + s.strip()[:160], file=sys.stderr, flush=True))
    stem = name or time.strftime("%Y%m%d-%H%M%S") + "-" + kind
    note_job = lambda job_id: (out_dir / (stem + ".job")).write_text(json.dumps({"job_id": job_id, "model": body["model"]}), encoding="utf-8")

    def attempt():
        if transport != "stream":
            try:
                return run_job(root, key, body, log, timeout, note_job)
            except Flow2APIError as e:
                if e.status != 404 or transport == "jobs":
                    raise
                log("server chưa có /v1/jobs; dùng streaming (không có Idempotency-Key)")
        content, mid = with_retries(lambda: post_stream(root, key, dict(body, stream=True), log, timeout), log)
        return content, mid, None

    with _SEM[kind]:
        for n in range(MAX_CAPTCHA_RETRIES + 1):
            try:
                content, mid, job_id = attempt()
                break
            except Flow2APIError as e:
                if not (e.retryable and e.after_submit) or n == MAX_CAPTCHA_RETRIES:
                    raise
                wait = (5, 15, 45)[min(n, 2)] * random.uniform(0.8, 1.3)
                print("  reCAPTCHA/quota, thử lại với job mới sau %.0f s (%s)" % (wait, e), file=sys.stderr); _sleep(wait)
    meta = {"model": body["model"], "generationConfig": body.get("generationConfig"), "prompt": _prompt_of(body), "job_id": job_id}
    return save_media(content, out_dir, stem, root, key, meta, mid)


# ---------------- listing / preflight ----------------
def fetch_listing(root, key):
    """{id: description} for every model this key can see (concrete ids and families); {} when the server cannot be asked."""
    out = {}
    for path in ("/v1/models", "/v1/models/aliases"):
        try:
            _, _, j = http_json(root, key, "GET", path, timeout=20)
        except Flow2APIError:
            return {}
        for m in (j or {}).get("data", []):
            out[m.get("id")] = m.get("description") or ""
    return out


def preflight(model, listing, log):
    """Free warnings before a paid call: model not visible to this key, or retiring soon."""
    if not listing:
        return
    if model not in listing:
        log("cảnh báo: %s không có trong danh sách model của key này; server có thể trả 403/400" % model)
    for mid, desc in listing.items():
        m = re.search(r"retires (\d{4}-\d{2}-\d{2})", desc or "")
        if m and (mid == model or mid.startswith(model + "-")):
            log("cảnh báo: %s sẽ bị Flow gỡ ngày %s; nên dùng model khác" % (model, m.group(1))); break


# ---------------- commands ----------------
def cmd_check(a):
    root, key = load_config()
    print("root:", root, "| key:", "đã đặt" if key else "CHƯA ĐẶT")
    if not key:
        print("Đặt FLOW2API_API_KEY trong môi trường hoặc %s rồi chạy lại." % CONF_FILE); return 2
    listing = fetch_listing(root, key)
    if not listing:
        print("Không đọc được /v1/models: kiểm tra FLOW2API_BASE_URL, key và server."); return 1
    contract = load_contract()
    print("model thấy được: %d id" % len(listing))
    for fam, c in contract.items():
        print("  %-24s %s" % (fam, "có" if fam in listing else "KHÔNG (key không được phép hoặc server không còn)"))
    retiring = {}
    for mid, d in listing.items():
        m = re.search(r"retires (\d{4}-\d{2}-\d{2})", d or "")
        owner = max((f for f in contract if mid == f or mid.startswith(f + "-")), key=len, default=None)
        if m and owner:
            retiring.setdefault(m.group(1), set()).add(owner)
    for day, fams in sorted(retiring.items()):
        print("sắp bị gỡ %s: %s" % (day, ", ".join(sorted(fams))))
    drafts = sum(1 for mid in listing if mid.startswith(DRAFT_FAMILY + "-360p-"))
    print("360p draft (omni-1.2-flash-360p-*): %s" % ("có %d id" % drafts if drafts else "không có"))
    try:
        http_json(root, key, "GET", "/v1/jobs?limit=1", timeout=20); print("job API (/v1/jobs): có (an toàn khi mất kết nối, có Idempotency-Key)")
    except Flow2APIError as e:
        print("job API (/v1/jobs): %s" % ("chưa có, sẽ dùng streaming" if e.status == 404 else str(e)))
    return 0


def _span(values):
    values = sorted(values)
    return "%d–%d" % (values[0], values[-1]) if values == list(range(values[0], values[-1] + 1)) and len(values) > 2 else ",".join(map(str, values))


def cmd_models(a):
    contract = load_contract()
    print("ẢNH (aspect × size; số ảnh tham chiếu 0–nhiều):")
    for fam, c in contract.items():
        if c["type"] == "image":
            p = c["parameters"]
            print("  %-28s aspect %s | size %s" % (fam, ",".join(p["aspectRatio"]["values"]), ",".join(p["imageSize"]["values"])))
    print("VIDEO (mode: aspect | giây | số ảnh | mặc định):")
    for fam, c in contract.items():
        if c["type"] != "video":
            continue
        for mode, d in sorted(c["mode_defaults"].items()):
            vs = [v for v in c["variants"] if v["mode"] == mode]
            imgs = sorted({(v["min_images"], v["max_images"]) for v in vs}, key=lambda x: (x[0], x[1] or 99))
            print("  %-16s %-6s %s | %s s | %s ảnh | mặc định %d s %s" % (fam, mode, ",".join(sorted({v["aspectRatio"] for v in vs})), _span({v["durationSeconds"] for v in vs}),
                  "/".join(str(lo) if lo == hi else "%d–%s" % (lo, "nhiều" if hi is None else hi) for lo, hi in imgs), d["durationSeconds"], d["aspectRatio"]))
    print("  %-16s %-6s 16:9,9:16 | %s s | 0–%d ảnh | --draft: 1/3 credit, id tường minh omni-1.2-flash-360p-{N}s-{landscape|portrait}" % (DRAFT_FAMILY, "360p", _span(DRAFT_DURATIONS), DRAFT_MAX_REFS))
    print("Nguồn: references/contract.json (sinh từ gateway). Model sắp bị gỡ: chạy `check`. Giới hạn song song: ảnh %d, video %d" % (MAX_PAR["image"], MAX_PAR["video"]))
    return 0


def plan_request(j, contract):
    """Validate one job dict and build its request. Returns (kind, body, info); raises Flow2APIError before any network call."""
    kind = j.get("kind", "image")
    refs = j.get("ref") or []
    if kind == "image":
        model = j.get("model") or DEFAULT_IMAGE_MODEL
        cfg = validate_image(contract, model, j.get("aspect"), j.get("size"), len(refs))
        return "image", build_body("image", j["prompt"], model, refs, cfg), {"model": model}
    if j.get("draft"):
        plan = resolve_draft(j.get("aspect"), j.get("duration"), len(refs), j.get("mode"), j.get("source"))
    else:
        plan = resolve_video(contract, j.get("model") or DEFAULT_VIDEO_MODEL, j.get("mode"), j.get("aspect"), j.get("duration"), len(refs), j.get("source"))
    return "video", build_body("video", j["prompt"], plan["model"], refs, plan["cfg"], j.get("source"), j.get("source_project")), plan


def run_one(j, root, key, quiet=False, transport="auto", timeout=3600, contract=None):
    kind, body, plan = plan_request(j, contract or load_contract())
    if not quiet:
        preflight(body["model"], fetch_listing(root, key), lambda s: print("  ! " + s, file=sys.stderr))
    return generate(kind, body, j.get("out") or "flow2api-out", j.get("name"), root, key, quiet, transport, timeout)


def _printable(body):
    """The request with inline images shortened, for --dry-run."""
    shown = json.loads(json.dumps(body))
    for m in shown["messages"]:
        if isinstance(m["content"], list):
            for part in m["content"]:
                u = part.get("image_url", {}).get("url", "")
                if u.startswith("data:"):
                    part["image_url"]["url"] = u[:30] + "…(%d bytes)" % len(u)
    return shown


def _job_from_args(a, kind):
    j = {"kind": kind, "prompt": a.prompt, "model": a.model, "aspect": a.aspect, "ref": a.ref or [], "out": a.out, "name": a.name}
    if a.prompt_file:
        j["prompt"] = pathlib.Path(a.prompt_file).read_text(encoding="utf-8")
    if kind == "image":
        j["size"] = a.size
    else:
        j.update(mode=a.mode, duration=a.duration, source=a.source, source_project=a.source_project, draft=a.draft)
    return j


def cmd_gen(a, kind):
    j = _job_from_args(a, kind)
    if a.dry_run:
        try:
            _, body, plan = plan_request(j, load_contract())
        except Flow2APIError as e:
            print("LỖI: " + str(e), file=sys.stderr); return 1
        print(json.dumps({"dry_run": True, "sent": False, "plan": {k: v for k, v in plan.items() if k != "cfg"}, "request": _printable(body)}, ensure_ascii=False, indent=1)); return 0
    root, key = load_config()
    if not key:
        print("Thiếu FLOW2API_API_KEY (môi trường hoặc %s)." % CONF_FILE, file=sys.stderr); return 2
    try:
        meta = run_one(j, root, key, transport=a.transport, timeout=a.timeout)
    except Flow2APIError as e:
        print("LỖI: " + redact(str(e), key), file=sys.stderr); return 1
    print(json.dumps(meta, ensure_ascii=False, indent=1)); return 0


def cmd_job(a):
    root, key = load_config()
    if not key:
        print("Thiếu FLOW2API_API_KEY.", file=sys.stderr); return 2
    out_dir = pathlib.Path(a.out).expanduser(); out_dir.mkdir(parents=True, exist_ok=True)
    try:
        doc = poll_job(root, key, a.job_id, lambda s: print("  … " + s, file=sys.stderr, flush=True), a.timeout)
        meta = save_media(job_content(doc), out_dir, a.name or a.job_id, root, key, {"model": doc.get("model"), "job_id": a.job_id, "prompt": None})
    except Flow2APIError as e:
        print("LỖI: " + redact(str(e), key), file=sys.stderr); return 1
    print(json.dumps(meta, ensure_ascii=False, indent=1)); return 0


def cmd_jobs(a):
    root, key = load_config()
    if not key:
        print("Thiếu FLOW2API_API_KEY.", file=sys.stderr); return 2
    try:
        _, _, j = http_json(root, key, "GET", "/v1/jobs?limit=%d" % a.limit)
    except Flow2APIError as e:
        print("LỖI: " + redact(str(e), key), file=sys.stderr); return 1
    for d in (j or {}).get("data", []):
        print("%s  %-9s %s  %s" % (d.get("id"), d.get("status"), d.get("model"), time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(d["created"])) if d.get("created") else ""))
    return 0


def already_done(job):
    """The metadata of an earlier successful run of this job (same out dir and name), or None."""
    name = job.get("name")
    if not name:
        return None
    try:
        meta = json.loads((pathlib.Path(job.get("out") or "flow2api-out").expanduser() / (name + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if meta.get("file") and pathlib.Path(meta["file"]).is_file() else None


def cmd_batch(a):
    contract = load_contract()
    try:
        jobs = [json.loads(l) for l in pathlib.Path(a.jobs).read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError) as e:
        print("LỖI: không đọc được %s: %s (mỗi dòng là một JSON)" % (a.jobs, e), file=sys.stderr); return 1
    for n, j in enumerate(jobs, 1):   # validate everything before sending anything
        try:
            plan_request(j, contract)
        except (Flow2APIError, KeyError) as e:
            print("LỖI ở job #%d (%s): %s. Chưa gửi gì." % (n, j.get("name") or "không có name", e), file=sys.stderr); return 1
    todo = [i for i, j in enumerate(jobs) if a.force or not already_done(j)]
    unnamed = sum(1 for j in jobs if not j.get("name"))
    if a.dry_run:
        print("%d job hợp lệ: %d sẽ chạy, %d đã có kết quả (bỏ qua); chưa gửi gì." % (len(jobs), len(todo), len(jobs) - len(todo)))
        if unnamed:
            print("%d job không có \"name\": chạy lại sẽ tạo lại chúng. Đặt name để chạy lại được an toàn." % unnamed)
        return 0
    root, key = load_config()
    if not key:
        print("Thiếu FLOW2API_API_KEY.", file=sys.stderr); return 2
    results = [None] * len(jobs)
    log_path = pathlib.Path(a.jobs + ".results.jsonl")
    lock, stop, why = threading.Lock(), threading.Event(), []
    started = time.time()
    workers = max(1, min(a.parallel, MAX_PAR["image"] + MAX_PAR["video"]))
    FATAL = {"credit_budget_exceeded", "model_not_allowed"}

    def note(i, entry):
        entry = dict(entry, index=i, name=jobs[i].get("name"))
        with lock, open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def work(i):
        tag = "[%d/%d]" % (i + 1, len(jobs))
        done = None if a.force else already_done(jobs[i])
        if done:
            results[i] = dict(done, skipped=True); print("%s đã có, bỏ qua: %s" % (tag, done["file"]), flush=True); return
        if i in todo[:workers]:
            _sleep(0.4 * todo.index(i))   # stagger only the first wave
        if stop.is_set():
            results[i] = {"error": "chưa chạy: " + why[0], "not_started": True}; print("%s chưa chạy (%s)" % (tag, why[0]), flush=True); return
        t0 = time.time()
        try:
            results[i] = run_one(jobs[i], root, key, quiet=True, transport=a.transport, timeout=a.timeout, contract=contract)
            print("%s xong sau %ds: %s" % (tag, time.time() - t0, results[i]["file"]), flush=True)
            note(i, {"ok": True, "file": results[i]["file"], "seconds": round(time.time() - t0), "job_id": results[i].get("job_id")})
        except Exception as e:
            results[i] = {"error": redact(str(e), key)}; print("%s lỗi: %s" % (tag, results[i]["error"]), flush=True)
            note(i, {"ok": False, "error": results[i]["error"], "seconds": round(time.time() - t0)})
            # Every remaining job would fail the same way and cost a request: stop submitting.
            if getattr(e, "code", None) in FATAL or getattr(e, "status", None) == 401:
                why.append(results[i]["error"][:120]); stop.set()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, range(len(jobs))))
    ok = sum(1 for r in results if r and "error" not in r and not r.get("skipped"))
    skipped = sum(1 for r in results if r and r.get("skipped"))
    not_started = sum(1 for r in results if r and r.get("not_started"))
    failed = [jobs[i].get("name") or "#%d" % (i + 1) for i, r in enumerate(results) if r and "error" in r and not r.get("not_started")]
    print("Hoàn tất sau %ds: %d xong, %d đã có từ trước, %d lỗi, %d chưa chạy (tổng %d)." % (time.time() - started, ok, skipped, len(failed), not_started, len(jobs)))
    if failed or not_started:
        print("Chạy lại đúng lệnh này để làm nốt: job đã xong sẽ được bỏ qua, không tính phí lại. Lỗi: %s" % ", ".join(failed[:12]))
    return 0 if not failed and not not_started else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Flow2API: tạo ảnh/video (mỗi lệnh image/video là một lần tạo tính phí)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check"); sub.add_parser("models")

    def common(p):
        p.add_argument("--dry-run", action="store_true", help="kiểm tra và in request, không gửi gì (miễn phí)")
        p.add_argument("--transport", choices=["auto", "jobs", "stream"], default="auto", help="auto: job API nếu server có, không thì stream")
        p.add_argument("--timeout", type=int, default=3600, help="giây chờ kết quả")
    for kind in ("image", "video"):
        p = sub.add_parser(kind)
        p.add_argument("prompt", nargs="?", default="")
        p.add_argument("--prompt-file"); p.add_argument("--model"); p.add_argument("--aspect")
        p.add_argument("--ref", action="append", help="ảnh tham chiếu (file cục bộ hoặc https), lặp lại theo thứ tự")
        p.add_argument("--out", default="flow2api-out"); p.add_argument("--name")
        common(p)
        if kind == "image":
            p.add_argument("--size")
        else:
            p.add_argument("--mode", choices=["auto", "t2v", "i2v", "r2v", "extend", "edit"]); p.add_argument("--duration", type=int)
            p.add_argument("--draft", action="store_true", help="Omni 1.2 360p: 1/3 credit, để thử nhanh")
            p.add_argument("--source", help="media_id của video cần nối dài/sửa (mode extend|edit)")
            p.add_argument("--source-project", help="project Flow chứa video nguồn, nếu video không tạo qua server này")
    p = sub.add_parser("job"); p.add_argument("job_id"); p.add_argument("--out", default="flow2api-out"); p.add_argument("--name"); p.add_argument("--timeout", type=int, default=3600)
    p = sub.add_parser("jobs"); p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("batch"); p.add_argument("jobs"); p.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL, help="số job chạy cùng lúc (mặc định %d)" % DEFAULT_PARALLEL)
    p.add_argument("--force", action="store_true", help="tạo lại cả job đã có kết quả (mặc định bỏ qua để không trả phí hai lần)"); common(p)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        return cmd_check(a)
    if a.cmd == "models":
        return cmd_models(a)
    if a.cmd == "job":
        return cmd_job(a)
    if a.cmd == "jobs":
        return cmd_jobs(a)
    if a.cmd == "batch":
        return cmd_batch(a)
    return cmd_gen(a, a.cmd)


if __name__ == "__main__":
    sys.exit(main())
