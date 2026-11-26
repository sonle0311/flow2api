"""Credits spent per client key and model.

Flow deducts credits when a generation is submitted, and the submit response states the balance
left. Each submission is therefore charged the drop from the previous balance of that account,
which stays exact however many requests run at once. Images answer synchronously without a
balance, so their balance is read once after they finish. The figures are measured from Flow's own
balance, not a price list; a first request after a restart starts from a freshly read balance.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from ..core.account_tiers import is_balance_collapse

MASTER_KEY_ID = 0  # usage by the master API key


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class CreditLedger:
    def __init__(self, db, token_manager, client_keys=None):
        self.db = db
        self.token_manager = token_manager
        self.client_keys = client_keys
        self.last_known: Dict[int, int] = {}
        self._locks: Dict[int, asyncio.Lock] = {}
        self._ready = False
        self._tasks: set = set()

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        async with self.db._connect(write=True) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS credit_usage (
                    day TEXT NOT NULL,
                    client_key_id INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    credits INTEGER NOT NULL DEFAULT 0,
                    requests INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (day, client_key_id, model)
                )
            """)
            await conn.commit()
        self._ready = True

    def _lock(self, token_id: int) -> asyncio.Lock:
        return self._locks.setdefault(token_id, asyncio.Lock())

    # ----- measuring -----

    async def ensure_baseline(self, token) -> None:
        """Know the balance before the first submission of this process (read once per account)."""
        if token.id in self.last_known:
            return
        stored = getattr(token, "credits", None)
        balance = None
        try:
            balance = int(await asyncio.wait_for(self.token_manager.refresh_credits(token.id, raise_on_error=True), timeout=10))
        except Exception:  # noqa: BLE001 - fall back to the stored balance; accounting must never block a request
            balance = stored if isinstance(stored, int) else None
        if balance is not None:
            self.last_known.setdefault(token.id, balance)

    def observe(self, token_id: int, credits_after: Any, *, client_key_id: int, model: str, kind: str) -> int:
        """Charge the drop in this account's balance to the request that caused it."""
        if isinstance(credits_after, bool) or not isinstance(credits_after, int) or credits_after < 0:
            return 0
        before = self.last_known.get(token_id)
        self.last_known[token_id] = credits_after
        if before is not None and is_balance_collapse(before, credits_after):
            # A plan change or reset, not spending; TokenManager.refresh_credits reports it.
            return 0
        spent = before - credits_after if before is not None and credits_after < before else 0
        if spent > 0:
            self._spawn(self.record(client_key_id, model, spent))
        return spent

    async def observe_after_completion(self, token, *, client_key_id: int, model: str, kind: str) -> None:
        """Images: read the balance once the request has finished and charge the difference."""
        try:
            async with self._lock(token.id):
                balance = int(await asyncio.wait_for(self.token_manager.refresh_credits(token.id, raise_on_error=True), timeout=15))
                self.observe(token.id, balance, client_key_id=client_key_id, model=model, kind=kind)
        except Exception:  # noqa: BLE001 - best effort; never affects the generation
            return

    def _spawn(self, coroutine) -> None:
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ----- storage -----

    async def record(self, client_key_id: int, model: str, credits: int) -> None:
        try:
            await self._ensure_table()
            async with self.db._connect(write=True) as conn:
                await conn.execute(
                    "INSERT INTO credit_usage (day, client_key_id, model, credits, requests) VALUES (?, ?, ?, ?, 1) "
                    "ON CONFLICT(day, client_key_id, model) DO UPDATE SET credits = credits + excluded.credits, "
                    "requests = requests + 1",
                    (_today(), client_key_id, model or "unknown", credits),
                )
                await conn.commit()
            if client_key_id != MASTER_KEY_ID and self.client_keys is not None:
                await self.client_keys.add_spend(client_key_id, credits)
        except Exception as exc:  # noqa: BLE001
            print(f"[credits] could not record usage: {type(exc).__name__}: {exc}", flush=True)

    async def report(self, days: int = 7) -> Dict[str, Any]:
        await self._ensure_table()
        days = max(1, min(int(days), 90))
        since = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        async with self.db._connect() as conn:
            rows = await (await conn.execute(
                "SELECT day, client_key_id, model, credits, requests FROM credit_usage WHERE day >= ? ORDER BY day", (since,)
            )).fetchall()
        names = {}
        if self.client_keys is not None:
            names = {key["id"]: key["name"] for key in self.client_keys.list()}
        by_day: Dict[str, int] = {}
        by_key: Dict[int, Dict[str, Any]] = {}
        by_model: Dict[str, Dict[str, int]] = {}
        for day, key_id, model, credits, requests in rows:
            by_day[day] = by_day.get(day, 0) + credits
            entry = by_key.setdefault(key_id, {"client_key_id": key_id, "name": "master key" if key_id == MASTER_KEY_ID else names.get(key_id, f"key {key_id} (deleted)"), "credits": 0, "requests": 0})
            entry["credits"] += credits
            entry["requests"] += requests
            model_entry = by_model.setdefault(model, {"credits": 0, "requests": 0})
            model_entry["credits"] += credits
            model_entry["requests"] += requests
        return {
            "days": days,
            "total_credits": sum(by_day.values()),
            "by_day": [{"day": day, "credits": credits} for day, credits in sorted(by_day.items())],
            "by_key": sorted(by_key.values(), key=lambda item: -item["credits"]),
            "by_model": sorted(({"model": model, **values} for model, values in by_model.items()), key=lambda item: -item["credits"]),
        }
