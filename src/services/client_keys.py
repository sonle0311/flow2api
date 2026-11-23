"""Per-client API keys with a request-rate limit, a concurrency limit and a model allow-list.

The key is shown once at creation; only its SHA-256 hash is stored. Keys carry
high entropy, so an unsalted hash is enough and lets authentication be a
dictionary lookup. Limits live in process memory and reset on restart.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

import aiosqlite

KEY_PREFIX = "sk-flow-"
DISPLAY_PREFIX_LENGTH = len(KEY_PREFIX) + 4
RATE_WINDOW_SECONDS = 60
CONCURRENCY_RETRY_AFTER_SECONDS = 5
DEFAULT_RATE_LIMIT_PER_MINUTE = 60
DEFAULT_MAX_CONCURRENT = 3
MAX_RATE_LIMIT_PER_MINUTE = 100000
MAX_CONCURRENT = 1000
MAX_NAME_LENGTH = 64
FLUSH_INTERVAL_SECONDS = 30
MAX_ALLOWED_MODELS = 200
MAX_MODEL_PATTERN_LENGTH = 100
TYPE_PATTERN_PREFIX = "type:"
MODEL_TYPES = ("image", "video")
_MODEL_PATTERN_RE = re.compile(r"type:(?:image|video)|[A-Za-z0-9._*-]+")


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ClientKey:
    id: int
    name: str
    key_prefix: str
    is_active: bool
    rate_limit_per_minute: int
    max_concurrent: int
    total_requests: int
    created_at: str
    last_used_at: Optional[str]
    allowed_models: list[str] = field(default_factory=list)


class ClientLimitExceeded(Exception):
    """A client key is over its rate or concurrency limit; answer HTTP 429."""

    def __init__(self, reason: str, limit: int, retry_after: int):
        super().__init__(reason)
        self.reason = reason  # "rate_limit" or "concurrency"
        self.limit = limit
        self.retry_after = retry_after

    @property
    def code(self) -> str:
        return "rate_limit_exceeded" if self.reason == "rate_limit" else "concurrency_limit_exceeded"

    @property
    def message(self) -> str:
        if self.reason == "rate_limit":
            return f"已超过该 API Key 的速率限制（每分钟 {self.limit} 次），请 {self.retry_after} 秒后重试"
        return f"已超过该 API Key 的并发上限（{self.limit} 个进行中的请求），请 {self.retry_after} 秒后重试"


class ModelNotAllowed(Exception):
    """The client key may not use the requested model; answer HTTP 403."""

    code = "model_not_allowed"

    def __init__(self, model: str):
        super().__init__(model)
        self.model = model

    @property
    def message(self) -> str:
        return f"该 API Key 无权使用模型 {self.model}"


class Lease:
    """One admitted in-flight request; release() is idempotent."""

    def __init__(self, release: Optional[Callable[[], None]] = None):
        self._release = release

    def release(self) -> None:
        release, self._release = self._release, None
        if release is not None:
            release()


NO_LEASE = Lease()


def _validated_int(value: Any, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 0 and {maximum}")
    return value


def _validated_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name or len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"name must be 1-{MAX_NAME_LENGTH} characters")
    return name


@lru_cache(maxsize=512)
def _compiled_pattern(pattern: str) -> "re.Pattern[str]":
    """Only ``*`` is a wildcard; everything else matches literally."""
    return re.compile(".*".join(re.escape(part) for part in pattern.split("*")))


def _decode_models(raw: Any) -> list[str]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else []
    except ValueError:
        return []
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _validated_models(value: Any, known_models: Optional[Iterable[str]]) -> list[str]:
    """Normalise an allow-list. Entries are model names, ``*`` patterns or ``type:image|video``."""
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > MAX_ALLOWED_MODELS:
        raise ValueError(f"allowed_models must be a list of at most {MAX_ALLOWED_MODELS} entries")
    patterns: list[str] = []
    for item in value:
        pattern = item.strip() if isinstance(item, str) else ""
        if (
            not pattern
            or len(pattern) > MAX_MODEL_PATTERN_LENGTH
            or _MODEL_PATTERN_RE.fullmatch(pattern) is None
        ):
            raise ValueError(f"invalid allowed_models entry: {item!r}")
        if pattern not in patterns:
            patterns.append(pattern)
    if known_models is not None:
        names = list(known_models)
        for pattern in patterns:
            if pattern.startswith(TYPE_PATTERN_PREFIX):
                continue
            if not any(_compiled_pattern(pattern).fullmatch(name) for name in names):
                raise ValueError(f"allowed_models entry matches no known model: {pattern}")
    return patterns


class ClientKeyService:
    def __init__(self, db, clock: Callable[[], float] = time.monotonic):
        self.db = db
        self._clock = clock
        self._by_hash: dict[str, ClientKey] = {}
        self._by_id: dict[int, ClientKey] = {}
        self._hits: dict[int, deque] = {}
        self._inflight: dict[int, int] = {}
        self._pending: dict[int, int] = {}
        self._flusher: Optional[asyncio.Task] = None
        # Returns every model name a client may reference; set by the application so
        # allow-list entries can be validated. None disables validation.
        self.known_models: Optional[Callable[[], Iterable[str]]] = None

    async def initialize(self) -> None:
        async with self.db._connect(write=True) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS client_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    key_prefix TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    rate_limit_per_minute INTEGER NOT NULL DEFAULT 0,
                    max_concurrent INTEGER NOT NULL DEFAULT 0,
                    total_requests INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    allowed_models TEXT NOT NULL DEFAULT '[]'
                )
            """)
            columns = {row[1] for row in await (await conn.execute("PRAGMA table_info(client_keys)")).fetchall()}
            if "allowed_models" not in columns:
                await conn.execute("ALTER TABLE client_keys ADD COLUMN allowed_models TEXT NOT NULL DEFAULT '[]'")
            await conn.commit()
        async with self.db._connect() as conn:
            conn.row_factory = aiosqlite.Row
            rows = await (await conn.execute("SELECT * FROM client_keys")).fetchall()
        self._by_hash.clear()
        self._by_id.clear()
        for row in rows:
            record = self._record(row)
            self._by_id[record.id] = record
            self._by_hash[row["key_hash"]] = record

    @staticmethod
    def _record(row) -> ClientKey:
        return ClientKey(
            id=row["id"], name=row["name"], key_prefix=row["key_prefix"],
            is_active=bool(row["is_active"]),
            rate_limit_per_minute=row["rate_limit_per_minute"],
            max_concurrent=row["max_concurrent"],
            total_requests=row["total_requests"],
            created_at=row["created_at"], last_used_at=row["last_used_at"],
            allowed_models=_decode_models(row["allowed_models"]),
        )

    # ----- authentication and limits (synchronous: no await, so no races) -----

    def authenticate(self, api_key: str) -> Optional[ClientKey]:
        if not api_key or not api_key.startswith(KEY_PREFIX):
            return None
        record = self._by_hash.get(hash_key(api_key))
        return record if record is not None and record.is_active else None

    @staticmethod
    def model_allowed(key: ClientKey, names: Iterable[str], media_type: Optional[str]) -> bool:
        """True when any of ``names`` (e.g. requested and resolved model) is permitted.

        An empty allow-list means every model. ``type:image`` / ``type:video`` allow a whole kind.
        """
        if not key.allowed_models:
            return True
        names = tuple(names)
        for pattern in key.allowed_models:
            if pattern.startswith(TYPE_PATTERN_PREFIX):
                if pattern[len(TYPE_PATTERN_PREFIX):] == media_type:
                    return True
            elif any(_compiled_pattern(pattern).fullmatch(name) for name in names):
                return True
        return False

    def admit(self, key: ClientKey) -> Lease:
        """Count one request against the key or raise ClientLimitExceeded."""
        now = self._clock()
        hits = self._hits.setdefault(key.id, deque())
        while hits and now - hits[0] >= RATE_WINDOW_SECONDS:
            hits.popleft()
        inflight = self._inflight.get(key.id, 0)
        if key.max_concurrent > 0 and inflight >= key.max_concurrent:
            raise ClientLimitExceeded("concurrency", key.max_concurrent, CONCURRENCY_RETRY_AFTER_SECONDS)
        if key.rate_limit_per_minute > 0 and len(hits) >= key.rate_limit_per_minute:
            retry_after = max(1, math.ceil(hits[0] + RATE_WINDOW_SECONDS - now))
            raise ClientLimitExceeded("rate_limit", key.rate_limit_per_minute, retry_after)
        hits.append(now)
        self._inflight[key.id] = inflight + 1
        key.total_requests += 1
        key.last_used_at = _now_iso()
        self._pending[key.id] = self._pending.get(key.id, 0) + 1
        return Lease(lambda: self._release(key.id))

    def _release(self, key_id: int) -> None:
        remaining = self._inflight.get(key_id, 0) - 1
        if remaining > 0:
            self._inflight[key_id] = remaining
        else:
            self._inflight.pop(key_id, None)

    # ----- administration -----

    def describe(self, key: ClientKey) -> dict:
        now = self._clock()
        recent = sum(1 for hit in self._hits.get(key.id, ()) if now - hit < RATE_WINDOW_SECONDS)
        return {
            "id": key.id,
            "name": key.name,
            "key_prefix": key.key_prefix,
            "is_active": key.is_active,
            "rate_limit_per_minute": key.rate_limit_per_minute,
            "max_concurrent": key.max_concurrent,
            "allowed_models": list(key.allowed_models),
            "total_requests": key.total_requests,
            "created_at": key.created_at,
            "last_used_at": key.last_used_at,
            "in_flight": self._inflight.get(key.id, 0),
            "requests_last_minute": recent,
        }

    def list(self) -> list[dict]:
        return [self.describe(key) for key in sorted(self._by_id.values(), key=lambda key: key.id)]

    def get(self, key_id: int) -> Optional[ClientKey]:
        return self._by_id.get(key_id)

    def _validate_models(self, value: Any) -> list[str]:
        return _validated_models(value, self.known_models() if self.known_models else None)

    async def create(
        self,
        name: str,
        rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        allowed_models: Optional[list[str]] = None,
    ) -> tuple[dict, str]:
        """Create a key and return (description, plaintext key shown only now)."""
        name = _validated_name(name)
        rate = _validated_int(rate_limit_per_minute, "rate_limit_per_minute", MAX_RATE_LIMIT_PER_MINUTE)
        concurrent = _validated_int(max_concurrent, "max_concurrent", MAX_CONCURRENT)
        models = self._validate_models(allowed_models)
        api_key = generate_key()
        created_at = _now_iso()
        async with self.db._connect(write=True) as conn:
            cursor = await conn.execute(
                "INSERT INTO client_keys (name, key_hash, key_prefix, is_active, rate_limit_per_minute,"
                " max_concurrent, created_at, allowed_models) VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
                (name, hash_key(api_key), api_key[:DISPLAY_PREFIX_LENGTH], rate, concurrent, created_at,
                 json.dumps(models)),
            )
            key_id = cursor.lastrowid
            await conn.commit()
        record = ClientKey(
            id=key_id, name=name, key_prefix=api_key[:DISPLAY_PREFIX_LENGTH], is_active=True,
            rate_limit_per_minute=rate, max_concurrent=concurrent, total_requests=0,
            created_at=created_at, last_used_at=None, allowed_models=models,
        )
        self._by_id[key_id] = record
        self._by_hash[hash_key(api_key)] = record
        return self.describe(record), api_key

    async def update(
        self,
        key_id: int,
        *,
        name: Optional[str] = None,
        is_active: Optional[bool] = None,
        rate_limit_per_minute: Optional[int] = None,
        max_concurrent: Optional[int] = None,
        allowed_models: Optional[list[str]] = None,
    ) -> Optional[dict]:
        record = self._by_id.get(key_id)
        if record is None:
            return None
        changes: dict[str, Any] = {}
        if name is not None:
            changes["name"] = _validated_name(name)
        if is_active is not None:
            changes["is_active"] = bool(is_active)
        if rate_limit_per_minute is not None:
            changes["rate_limit_per_minute"] = _validated_int(
                rate_limit_per_minute, "rate_limit_per_minute", MAX_RATE_LIMIT_PER_MINUTE
            )
        if max_concurrent is not None:
            changes["max_concurrent"] = _validated_int(max_concurrent, "max_concurrent", MAX_CONCURRENT)
        if allowed_models is not None:
            changes["allowed_models"] = self._validate_models(allowed_models)
        if changes:
            assignments = ", ".join(f"{column} = ?" for column in changes)
            stored = [
                json.dumps(v) if column == "allowed_models" else int(v) if isinstance(v, bool) else v
                for column, v in changes.items()
            ]
            async with self.db._connect(write=True) as conn:
                await conn.execute(f"UPDATE client_keys SET {assignments} WHERE id = ?", (*stored, key_id))
                await conn.commit()
            for field_name, value in changes.items():
                setattr(record, field_name, value)
        return self.describe(record)

    async def rotate(self, key_id: int) -> Optional[tuple[dict, str]]:
        """Replace the key's secret; the old one stops working at once."""
        record = self._by_id.get(key_id)
        if record is None:
            return None
        api_key = generate_key()
        old_hash = next((h for h, r in self._by_hash.items() if r is record), None)
        async with self.db._connect(write=True) as conn:
            await conn.execute(
                "UPDATE client_keys SET key_hash = ?, key_prefix = ? WHERE id = ?",
                (hash_key(api_key), api_key[:DISPLAY_PREFIX_LENGTH], key_id),
            )
            await conn.commit()
        if old_hash is not None:
            del self._by_hash[old_hash]
        self._by_hash[hash_key(api_key)] = record
        record.key_prefix = api_key[:DISPLAY_PREFIX_LENGTH]
        return self.describe(record), api_key

    async def delete(self, key_id: int) -> bool:
        record = self._by_id.get(key_id)
        if record is None:
            return False
        async with self.db._connect(write=True) as conn:
            await conn.execute("DELETE FROM client_keys WHERE id = ?", (key_id,))
            await conn.commit()
        del self._by_id[key_id]
        for key_hash in [h for h, r in self._by_hash.items() if r is record]:
            del self._by_hash[key_hash]
        self._hits.pop(key_id, None)
        self._pending.pop(key_id, None)
        return True

    # ----- usage persistence -----

    async def flush_usage(self) -> None:
        pending, self._pending = self._pending, {}
        if not pending:
            return
        async with self.db._connect(write=True) as conn:
            for key_id, count in pending.items():
                record = self._by_id.get(key_id)
                if record is None:
                    continue
                await conn.execute(
                    "UPDATE client_keys SET total_requests = total_requests + ?, last_used_at = ? WHERE id = ?",
                    (count, record.last_used_at, key_id),
                )
            await conn.commit()

    def start(self) -> None:
        if self._flusher is None or self._flusher.done():
            self._flusher = asyncio.create_task(self._flush_loop())

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            try:
                await self.flush_usage()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    async def close(self) -> None:
        if self._flusher is not None:
            self._flusher.cancel()
            try:
                await self._flusher
            except asyncio.CancelledError:
                pass
            self._flusher = None
        await self.flush_usage()
