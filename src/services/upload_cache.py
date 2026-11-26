"""Reuse the Flow media id of an input image the server already uploaded.

Every generation that takes images (reference images, a start or end frame, Veo and Omni
references) uploads each one first, which takes 16-17 s per image: a reCAPTCHA token from the
account's browser plus the upload itself. Flow answers with a media id that names the file inside
the account's project, so the same bytes uploaded again for the same account and project can reuse
that id. A character sheet sent with 38 requests is then uploaded once.

The key is (account, project, SHA-256 of the bytes): a media id only exists inside one project of
one account, so it is never shared across them. Only hashes and ids are stored, never the images.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

DEFAULT_TTL_HOURS = 24.0
MAX_ENTRIES = 5000
_DISABLE_VALUES = {"0", "off", "false", "no"}
# Flow answers a generation that names a media id it does not have with "code=[5]" (observed
# 2026-11-26: rpc=ogiZ0b, code=[5]); the same code marks a media id that polls forever.
STALE_MEDIA_MARKERS = ("code=[5]", "media not found", "public_error_media_not_found")

Key = Tuple[int, str, str]


def ttl_seconds() -> float:
    """Entry lifetime from FLOW2API_UPLOAD_CACHE_HOURS (default 24; 0 turns the cache off)."""
    raw = os.environ.get("FLOW2API_UPLOAD_CACHE_HOURS", "").strip().lower()
    if raw in _DISABLE_VALUES:
        return 0.0
    try:
        hours = float(raw) if raw else DEFAULT_TTL_HOURS
    except ValueError:
        hours = DEFAULT_TTL_HOURS
    return max(hours, 0.0) * 3600


class UploadCache:
    def __init__(self, db, ttl: Optional[float] = None, max_entries: int = MAX_ENTRIES):
        self.db = db
        self.ttl = ttl_seconds() if ttl is None else float(ttl)
        self.max_entries = max_entries
        self._ready = False
        self._inflight: Dict[Key, "asyncio.Future[str]"] = {}

    @property
    def enabled(self) -> bool:
        return self.db is not None and self.ttl > 0

    @staticmethod
    def key(token_id: int, project_id: str, data: bytes) -> Key:
        return int(token_id), str(project_id), hashlib.sha256(data).hexdigest()

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        async with self.db._connect(write=True) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS upload_cache (
                    token_id INTEGER NOT NULL,
                    project_id TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    media_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_used_at REAL NOT NULL,
                    hits INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (token_id, project_id, sha256)
                )
            """)
            await conn.commit()
        self._ready = True

    async def _lookup(self, key: Key) -> Optional[str]:
        await self._ensure_table()
        async with self.db._connect() as conn:
            row = await (await conn.execute(
                "SELECT media_id, created_at FROM upload_cache WHERE token_id = ? AND project_id = ? AND sha256 = ?", key
            )).fetchone()
        if not row:
            return None
        if time.time() - float(row[1]) > self.ttl:
            await self.forget_key(key)
            return None
        async with self.db._connect(write=True) as conn:
            await conn.execute(
                "UPDATE upload_cache SET hits = hits + 1, last_used_at = ? WHERE token_id = ? AND project_id = ? AND sha256 = ?",
                (time.time(), *key),
            )
            await conn.commit()
        return str(row[0])

    async def _store(self, key: Key, media_id: str) -> None:
        await self._ensure_table()
        now = time.time()
        async with self.db._connect(write=True) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO upload_cache (token_id, project_id, sha256, media_id, created_at, last_used_at, hits) "
                "VALUES (?, ?, ?, ?, ?, ?, 0)",
                (*key, media_id, now, now),
            )
            await conn.execute(
                "DELETE FROM upload_cache WHERE rowid IN (SELECT rowid FROM upload_cache ORDER BY last_used_at DESC LIMIT -1 OFFSET ?)",
                (self.max_entries,),
            )
            await conn.commit()

    async def forget_key(self, key: Key) -> None:
        await self._ensure_table()
        async with self.db._connect(write=True) as conn:
            await conn.execute("DELETE FROM upload_cache WHERE token_id = ? AND project_id = ? AND sha256 = ?", key)
            await conn.commit()

    async def forget_media(self, token_id: int, project_id: str, media_ids: List[str]) -> int:
        """Drop entries whose media id Flow no longer accepts. Returns how many were removed."""
        ids = [str(m) for m in media_ids if m]
        if not ids or not self.enabled:
            return 0
        await self._ensure_table()
        removed = 0
        async with self.db._connect(write=True) as conn:
            for media_id in ids:
                cursor = await conn.execute(
                    "DELETE FROM upload_cache WHERE token_id = ? AND project_id = ? AND media_id = ?",
                    (int(token_id), str(project_id), media_id),
                )
                removed += cursor.rowcount or 0
            await conn.commit()
        return removed

    async def get_or_upload(
        self,
        token_id: int,
        project_id: str,
        data: bytes,
        uploader: Callable[[], Awaitable[str]],
        *,
        use_cache: bool = True,
    ) -> Tuple[str, bool]:
        """(media_id, reused). Concurrent calls for the same image share one upload."""
        if not self.enabled or not project_id:
            return await uploader(), False
        key = self.key(token_id, project_id, data)
        for _ in range(2):
            pending = self._inflight.get(key)
            if pending is None:
                break
            try:
                return await asyncio.shield(pending), True
            except Exception:  # the first upload failed; try once on our own
                continue
        # Register as the one uploader before awaiting anything, so concurrent callers find us.
        future: "asyncio.Future[str]" = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            if use_cache:
                media_id = await self._lookup(key)
                if media_id:
                    future.set_result(media_id)
                    return media_id, True
            media_id = await uploader()
            await self._store(key, media_id)
            future.set_result(media_id)
            return media_id, False
        except BaseException as error:
            if not future.done():
                future.set_exception(error if isinstance(error, Exception) else RuntimeError("upload cancelled"))
                future.exception()  # mark retrieved: nobody may be waiting
            raise
        finally:
            if self._inflight.get(key) is future:
                del self._inflight[key]


def looks_like_stale_media(error: BaseException) -> bool:
    text = str(error or "").lower()
    return any(marker in text for marker in STALE_MEDIA_MARKERS)
