"""Numbers derived from the request log: the summary strip and the per-request time breakdown."""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
SUMMARY_ROW_LIMIT = 20000
BUCKET_TARGET = 24
MODEL_LIMIT = 50

# Stages of one request in the order they happen: (id, path inside the saved ``performance`` object).
# Stages overlap a little (the pipeline total contains them), so the pipeline total is not listed.
TIMING_STAGES = (
    ("token_select", ("token_select_ms",)),
    ("ensure_at", ("ensure_at_ms",)),
    ("ensure_project", ("ensure_project_ms",)),
    ("slot_wait", ("image_generation", "slot_wait_ms")),
    ("slot_wait", ("video_generation", "slot_wait_ms")),
    ("launch_queue_wait", ("image_generation", "launch_queue_wait_ms")),
    ("launch_stagger_wait", ("image_generation", "launch_stagger_wait_ms")),
    ("upload_images", ("image_generation", "upload_images_ms")),
    ("generate_api", ("image_generation", "generate_api_ms")),
    ("submit_generation", ("video_generation", "submit_generation_ms")),
    ("upsample", ("image_generation", "upsample_ms")),
)


def parse_timestamp(value: Any) -> Optional[datetime]:
    """A request log timestamp (UTC, written by SQLite's CURRENT_TIMESTAMP) as an aware datetime."""
    try:
        return datetime.strptime(str(value)[:19], TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime(TIMESTAMP_FORMAT)


def window_start(hours: float, now: Optional[datetime] = None) -> Optional[str]:
    """The UTC timestamp ``hours`` before now, or None for no limit (hours = 0)."""
    if not hours or hours <= 0:
        return None
    now = now or datetime.now(timezone.utc)
    return format_timestamp(now - timedelta(hours=hours))


def percentile(sorted_values: List[float], fraction: float) -> Optional[float]:
    """Nearest-rank percentile of an ascending list."""
    if not sorted_values:
        return None
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


def _round(value: Optional[float], digits: int = 1) -> Optional[float]:
    return None if value is None else round(value, digits)


def _durations(values: Iterable[float]) -> Dict[str, Any]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "median": _round(statistics.median(ordered)) if ordered else None,
        "p95": _round(percentile(ordered, 0.95)),
    }


def classify(status_code: Any) -> str:
    """success, failed or running, matching the list filter."""
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return "running"
    if code == 200:
        return "success"
    if code >= 400:
        return "failed"
    return "running"


def _rate(success: int, failed: int) -> Optional[float]:
    finished = success + failed
    return round(success / finished, 4) if finished else None


def summarize(
    rows: List[Dict[str, Any]],
    *,
    since: Optional[str],
    client_key_names: Optional[Dict[int, str]] = None,
    limit: int = SUMMARY_ROW_LIMIT,
) -> Dict[str, Any]:
    """Counts, durations, cache hit rate and breakdowns for the request log rows of one window."""
    client_key_names = client_key_names or {}
    counts = {"success": 0, "failed": 0, "running": 0}
    success_durations: List[float] = []
    cache_hits = cache_misses = cache_requests = 0
    accounts: Dict[Any, Dict[str, Any]] = {}
    models: Dict[str, Dict[str, Any]] = {}
    keys: Dict[Any, Dict[str, Any]] = {}

    for row in rows:
        state = classify(row.get("status_code"))
        counts[state] += 1
        duration = float(row.get("duration") or 0)

        account = accounts.setdefault(
            row.get("token_id"),
            {"token_id": row.get("token_id"), "email": row.get("token_email") or "", "requests": 0,
             "success": 0, "failed": 0, "_durations": []},
        )
        model = models.setdefault(
            row.get("model") or "",
            {"model": row.get("model") or "", "requests": 0, "success": 0, "failed": 0, "_durations": []},
        )
        key_id = int(row.get("client_key_id") or 0)
        key = keys.setdefault(
            key_id,
            {"client_key_id": key_id, "name": client_key_names.get(key_id, ""), "requests": 0, "failed": 0},
        )
        for bucket in (account, model):
            bucket["requests"] += 1
            if state in ("success", "failed"):
                bucket[state] += 1
        key["requests"] += 1
        if state == "failed":
            key["failed"] += 1

        if state == "success":
            success_durations.append(duration)
            account["_durations"].append(duration)
            model["_durations"].append(duration)
            hits, misses = row.get("cache_hits"), row.get("cache_misses")
            if hits is not None or misses is not None:
                cache_requests += 1
                cache_hits += int(hits or 0)
                cache_misses += int(misses or 0)

    def finish(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for item in items:
            stats = _durations(item.pop("_durations"))
            item["median"] = stats["median"]
            item["p95"] = stats["p95"]
            item["success_rate"] = _rate(item["success"], item["failed"])
            out.append(item)
        return sorted(out, key=lambda item: -item["requests"])

    lookups = cache_hits + cache_misses
    return {
        "since": since,
        "total": len(rows),
        "truncated": len(rows) >= limit,
        **counts,
        "success_rate": _rate(counts["success"], counts["failed"]),
        "duration": _durations(success_durations),
        "upload_cache": {
            "requests": cache_requests,
            "hits": cache_hits,
            "misses": cache_misses,
            "hit_rate": round(cache_hits / lookups, 4) if lookups else None,
        },
        "by_account": finish(accounts.values()),
        "by_model": finish(models.values())[:MODEL_LIMIT],
        "by_client_key": sorted(keys.values(), key=lambda item: -item["requests"]),
        "buckets": _buckets(rows, since),
    }


def _buckets(rows: List[Dict[str, Any]], since: Optional[str]) -> List[Dict[str, Any]]:
    """Requests per time slot, oldest first: about 24 slots for a window, one per day for all time."""
    stamped = [(parse_timestamp(row.get("created_at")), row) for row in rows]
    stamped = [(moment, row) for moment, row in stamped if moment is not None]
    if not stamped:
        return []
    start = parse_timestamp(since) if since else min(moment for moment, _ in stamped)
    end = datetime.now(timezone.utc) if since else max(moment for moment, _ in stamped)
    span = max((end - start).total_seconds(), 60.0)
    width = 86400.0 if not since else max(60.0, math.ceil(span / BUCKET_TARGET / 60) * 60)
    origin = start.timestamp()
    count = int(span // width) + 1
    slots = [{"start": format_timestamp(datetime.fromtimestamp(origin + index * width, timezone.utc)),
              "requests": 0, "failed": 0} for index in range(count)]
    for moment, row in stamped:
        index = min(count - 1, max(0, int((moment.timestamp() - origin) // width)))
        slots[index]["requests"] += 1
        if classify(row.get("status_code")) == "failed":
            slots[index]["failed"] += 1
    return slots


def _number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def extract_timings(response_body: Optional[str]) -> Optional[Dict[str, Any]]:
    """The time breakdown saved with a request, or None when the log has no performance trace.

    ``stages`` lists the measured steps in order, in milliseconds. ``other_ms`` is the part of the
    total that no step accounts for (for videos, mostly waiting for Flow to render).
    """
    try:
        body = json.loads(response_body) if response_body else None
    except (TypeError, ValueError):
        return None
    performance = body.get("performance") if isinstance(body, dict) else None
    if not isinstance(performance, dict):
        return None

    stages: List[Dict[str, Any]] = []
    for stage_id, path in TIMING_STAGES:
        node: Any = performance
        for part in path:
            node = node.get(part) if isinstance(node, dict) else None
        value = _number(node)
        if value is not None:
            stages.append({"id": stage_id, "ms": int(round(value))})
    total = _number(performance.get("total_ms"))
    measured = sum(stage["ms"] for stage in stages)
    cache = performance.get("upload_cache") if isinstance(performance.get("upload_cache"), dict) else None
    images = None
    for section in ("image_generation", "video_generation"):
        node = performance.get(section)
        if isinstance(node, dict) and _number(node.get("input_image_count")) is not None:
            images = int(node["input_image_count"])
    if not stages and total is None:
        return None
    return {
        "total_ms": None if total is None else int(round(total)),
        "stages": stages,
        "other_ms": None if total is None else max(0, int(round(total)) - measured),
        "input_images": images,
        "upload_cache": None if cache is None else {
            "hits": int(_number(cache.get("hits")) or 0),
            "misses": int(_number(cache.get("misses")) or 0),
        },
    }
