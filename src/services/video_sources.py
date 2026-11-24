"""Which project and account own a generated Flow video.

Omni Extend and Omni Edit must run in the project that holds the source video, on the account
that owns it. A client only has the media ID from an earlier result, so every successful video
generation records where it lives; ``extend://MEDIA_ID?project=PROJECT_ID`` names the project
explicitly for a video that was not generated through this server.
"""

from __future__ import annotations

from typing import Optional, Tuple
from urllib.parse import parse_qs


def parse_source(raw: Optional[str]) -> Tuple[str, Optional[str]]:
    """Split ``MEDIA_ID`` or ``MEDIA_ID?project=PROJECT_ID`` into (media_id, project_id)."""
    media_id, _, query = str(raw or "").strip().partition("?")
    project = (parse_qs(query).get("project") or [""])[0].strip()
    return media_id.strip(), project or None


class VideoSourceStore:
    def __init__(self, db):
        self.db = db
        self._ready = False

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        async with self.db._connect(write=True) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS video_sources (
                    media_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    token_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.commit()
        self._ready = True

    async def record(self, media_id: str, project_id: str, token_id: int) -> None:
        if not media_id or not project_id:
            return
        await self._ensure_table()
        async with self.db._connect(write=True) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO video_sources (media_id, project_id, token_id) VALUES (?, ?, ?)",
                (media_id, project_id, token_id),
            )
            await conn.commit()

    async def project_of(self, media_id: str) -> Optional[str]:
        await self._ensure_table()
        async with self.db._connect() as conn:
            row = await (await conn.execute(
                "SELECT project_id FROM video_sources WHERE media_id = ?", (media_id,)
            )).fetchone()
        return row[0] if row else None
