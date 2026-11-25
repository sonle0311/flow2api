"""Asynchronous generation jobs: submit, poll, cancel, and replay a retry by Idempotency-Key.

A job runs the same generation as POST /v1/chat/completions in the background, so a client can
disconnect and come back for the result. Jobs are persisted in SQLite so results survive a
restart; a job that was still running when the server stopped is marked failed (its upstream
work may have been submitted and paid for). Prompts and images are not stored.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

JOB_RETENTION_SECONDS = 7 * 24 * 3600
CLEANUP_INTERVAL_SECONDS = 3600
MAX_ACTIVE_JOBS = 100
MAX_IDEMPOTENCY_KEY_LENGTH = 128
POLL_HINT_SECONDS = 5

ACTIVE_STATUSES = ("queued", "running")
FINAL_STATUSES = ("succeeded", "failed", "canceled")


class JobLimitExceeded(Exception):
    """Too many jobs are running at once; answer HTTP 429."""

    retry_after = POLL_HINT_SECONDS * 2


class IdempotencyConflict(Exception):
    """The Idempotency-Key was already used for a different request."""


def _now() -> float:
    return time.time()


class JobManager:
    def __init__(self, db):
        self.db = db
        self._tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._ready = False
        self._cleanup_task: Optional[asyncio.Task] = None
        self._closing = False

    # ---------- storage ----------

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        async with self.db._connect(write=True) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    idempotency_key TEXT,
                    fingerprint TEXT,
                    model TEXT,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    result TEXT,
                    error TEXT
                )
            """)
            await conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency ON jobs(owner, idempotency_key) "
                "WHERE idempotency_key IS NOT NULL"
            )
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_owner_created ON jobs(owner, created_at)")
            await conn.commit()
        self._ready = True

    @staticmethod
    def _document(row) -> Dict[str, Any]:
        (job_id, _owner, _key, _fingerprint, model, status, created, started, finished, result, error) = row
        document: Dict[str, Any] = {
            "id": job_id,
            "object": "job",
            "status": status,
            "model": model,
            "created": int(created),
            "started": int(started) if started else None,
            "finished": int(finished) if finished else None,
        }
        if result:
            document["result"] = json.loads(result)
        if error:
            document["error"] = json.loads(error)
        return document

    _COLUMNS = "id, owner, idempotency_key, fingerprint, model, status, created_at, started_at, finished_at, result, error"

    async def _fetch(self, conn, where: str, params: tuple):
        cursor = await conn.execute(f"SELECT {self._COLUMNS} FROM jobs WHERE {where}", params)
        return await cursor.fetchone()

    async def _update(self, job_id: str, **fields) -> None:
        assignments = ", ".join(f"{name} = ?" for name in fields)
        async with self.db._connect(write=True) as conn:
            await conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", (*fields.values(), job_id))
            await conn.commit()

    # ---------- lifecycle ----------

    async def start(self) -> None:
        await self._ensure_table()
        self._closing = False
        async with self.db._connect(write=True) as conn:
            await conn.execute(
                "UPDATE jobs SET status = 'failed', finished_at = ?, error = ? WHERE status IN ('queued', 'running')",
                (_now(), json.dumps({
                    "message": "The server restarted while this job was running; generation may still have been submitted upstream.",
                    "type": "server_error",
                    "code": "server_restarted",
                    "status_code": 503,
                })),
            )
            await conn.commit()
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def close(self) -> None:
        self._closing = True
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except BaseException:  # noqa: BLE001 - shutting down; each task records its own outcome
                pass

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await self.purge_expired()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[jobs] cleanup failed: {type(exc).__name__}: {exc}", flush=True)
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)

    async def purge_expired(self) -> int:
        await self._ensure_table()
        async with self.db._connect(write=True) as conn:
            cursor = await conn.execute(
                "DELETE FROM jobs WHERE status IN ('succeeded', 'failed', 'canceled') AND finished_at < ?",
                (_now() - JOB_RETENTION_SECONDS,),
            )
            await conn.commit()
            return cursor.rowcount or 0

    # ---------- operations ----------

    async def find_replay(self, owner: str, idempotency_key: Optional[str], fingerprint: str) -> Optional[Dict[str, Any]]:
        """The job already created for this key, or None. Raises IdempotencyConflict on a different body."""
        if not idempotency_key:
            return None
        await self._ensure_table()
        async with self.db._connect() as conn:
            row = await self._fetch(conn, "owner = ? AND idempotency_key = ?", (owner, idempotency_key))
        if row is None:
            return None
        if row[3] != fingerprint:
            raise IdempotencyConflict(idempotency_key)
        return self._document(row)

    async def submit(
        self,
        *,
        owner: str,
        idempotency_key: Optional[str],
        fingerprint: str,
        model: str,
        work: Callable[[], Awaitable[str]],
        release: Callable[[], None],
    ) -> Tuple[Dict[str, Any], bool]:
        """Create a job and start it. Returns (document, replayed).

        ``release`` is called exactly once when the job ends, or at once for a replay.
        """
        await self._ensure_table()
        async with self._lock:
            try:
                replay = await self.find_replay(owner, idempotency_key, fingerprint)
            except IdempotencyConflict:
                release()
                raise
            if replay is not None:
                release()
                return replay, True
            if len(self._tasks) >= MAX_ACTIVE_JOBS:
                release()
                raise JobLimitExceeded()
            job_id = "job_" + uuid.uuid4().hex
            created = _now()
            async with self.db._connect(write=True) as conn:
                await conn.execute(
                    "INSERT INTO jobs (id, owner, idempotency_key, fingerprint, model, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, 'queued', ?)",
                    (job_id, owner, idempotency_key or None, fingerprint, model, created),
                )
                await conn.commit()
            self._tasks[job_id] = asyncio.create_task(self._run(job_id, work, release))
        return await self.get(owner, job_id), False  # type: ignore[return-value]

    async def _run(self, job_id: str, work: Callable[[], Awaitable[str]], release: Callable[[], None]) -> None:
        try:
            await self._update(job_id, status="running", started_at=_now())
            raw = await work()
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                payload = {"result": raw}
            error = payload.get("error") if isinstance(payload, dict) else None
            if error:
                await self._update(
                    job_id, status="failed", finished_at=_now(),
                    error=json.dumps(error if isinstance(error, dict) else {"message": str(error)}, ensure_ascii=False),
                )
            else:
                await self._update(job_id, status="succeeded", finished_at=_now(), result=json.dumps(payload, ensure_ascii=False))
        except asyncio.CancelledError:
            reason = "shutdown" if self._closing else "canceled"
            await self._finish_after_cancel(job_id, reason)
            raise
        except Exception as exc:  # noqa: BLE001 - the failure is reported on the job
            await self._update(
                job_id, status="failed", finished_at=_now(),
                error=json.dumps({"message": str(exc) or type(exc).__name__, "type": "server_error", "code": "generation_failed", "status_code": 500}, ensure_ascii=False),
            )
        finally:
            self._tasks.pop(job_id, None)
            release()

    async def _finish_after_cancel(self, job_id: str, reason: str) -> None:
        # The task is being cancelled; finish the bookkeeping without being cancelled again.
        if reason == "shutdown":
            error = {"message": "The server shut down while this job was running; generation may still have been submitted upstream.",
                     "type": "server_error", "code": "server_restarted", "status_code": 503}
            fields = dict(status="failed", finished_at=_now(), error=json.dumps(error))
        else:
            fields = dict(status="canceled", finished_at=_now())
        await asyncio.shield(self._update(job_id, **fields))

    async def get(self, owner: str, job_id: str) -> Optional[Dict[str, Any]]:
        await self._ensure_table()
        async with self.db._connect() as conn:
            row = await self._fetch(conn, "id = ? AND owner = ?", (job_id, owner))
        return self._document(row) if row else None

    async def list(self, owner: str, limit: int = 50) -> List[Dict[str, Any]]:
        await self._ensure_table()
        limit = max(1, min(int(limit), 200))
        async with self.db._connect() as conn:
            cursor = await conn.execute(
                f"SELECT {self._COLUMNS} FROM jobs WHERE owner = ? ORDER BY created_at DESC LIMIT ?", (owner, limit)
            )
            rows = await cursor.fetchall()
        return [self._document(row) for row in rows]

    async def cancel(self, owner: str, job_id: str) -> Optional[Dict[str, Any]]:
        """Stop waiting for a job. Work already submitted upstream is not recalled."""
        document = await self.get(owner, job_id)
        if document is None:
            return None
        task = self._tasks.get(job_id)
        if task is not None and document["status"] in ACTIVE_STATUSES:
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):  # noqa: BLE001
                pass
            document = await self.get(owner, job_id)
        return document

    @property
    def active_jobs(self) -> int:
        return len(self._tasks)
