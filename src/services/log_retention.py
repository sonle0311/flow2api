"""How long request logs are kept: a stored setting and a periodic cleanup."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from .log_insights import format_timestamp

MAX_RETENTION_DAYS = 3650
CLEANUP_INTERVAL_SECONDS = 3600


class LogRetention:
    """``days`` = 0 keeps every log. Otherwise logs older than that many days are deleted hourly."""

    def __init__(self, db, *, clock: Callable[[], float] = time.time, interval: float = CLEANUP_INTERVAL_SECONDS):
        self.db = db
        self._clock = clock
        self._interval = interval
        self._ready = False
        self._task: Optional[asyncio.Task] = None
        self._last_purged = 0
        self._last_run_at: Optional[float] = None

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        async with self.db._connect(write=True) as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS log_retention ("
                "id INTEGER PRIMARY KEY CHECK (id = 1), days INTEGER NOT NULL DEFAULT 0)"
            )
            await conn.execute("INSERT OR IGNORE INTO log_retention (id, days) VALUES (1, 0)")
            await conn.commit()
        self._ready = True

    async def get_days(self) -> int:
        await self._ensure_table()
        async with self.db._connect() as conn:
            row = await (await conn.execute("SELECT days FROM log_retention WHERE id = 1")).fetchone()
        return int(row[0]) if row else 0

    async def set_days(self, days: int) -> int:
        """Store the setting and apply it now. Returns how many logs the cleanup deleted."""
        if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= MAX_RETENTION_DAYS:
            raise ValueError(f"retention_days must be a whole number from 0 to {MAX_RETENTION_DAYS}")
        await self._ensure_table()
        async with self.db._connect(write=True) as conn:
            await conn.execute("UPDATE log_retention SET days = ? WHERE id = 1", (days,))
            await conn.commit()
        return await self.run_once()

    async def run_once(self) -> int:
        days = await self.get_days()
        self._last_run_at = self._clock()
        if days <= 0:
            self._last_purged = 0
            return 0
        cutoff = datetime.fromtimestamp(self._clock(), timezone.utc) - timedelta(days=days)
        self._last_purged = await self.db.purge_request_logs(format_timestamp(cutoff))
        return self._last_purged

    async def status(self) -> dict:
        return {
            "retention_days": await self.get_days(),
            "last_run_at": None if self._last_run_at is None
            else datetime.fromtimestamp(self._last_run_at, timezone.utc).isoformat(),
            "last_purged": self._last_purged,
        }

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - try again next hour
                print(f"[log-retention] cleanup failed: {type(exc).__name__}: {exc}", flush=True)
            await asyncio.sleep(self._interval)
