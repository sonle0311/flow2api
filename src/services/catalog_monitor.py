"""Watch Flow's model table for changes that affect this deployment.

Flow retired Veo Extend and added Omni extend/edit without announcement, and each time the
first sign was failing requests. Once a day (and on demand) this reads the same model table the
Flow web app loads (RPC HTrJv, read-only, nothing is generated), compares it with the registry
and with the previous reading, and raises alerts for what needs attention:

* a model key this server submits that Flow no longer lists (requests for it will fail),
* reference-image limits that differ from Flow's,
* models Flow added, removed or re-priced since the last reading, and
* retirement dates the local registry does not carry yet.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .flow_catalog import CatalogFormatError, compare, parse_catalog

DEFAULT_INTERVAL_HOURS = 24
FIRST_CHECK_DELAY_SECONDS = 120


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def snapshot_of(catalog) -> Dict[str, Dict[str, Any]]:
    """Model key -> what a change in it would mean to a user: its group and price."""
    return {
        key: {"group": entry.group, "credits": {str(tier): cost for tier, cost in sorted(entry.credits.items())}}
        for key, entry in sorted(catalog.entries.items())
    }


def diff_snapshots(previous: Dict[str, Dict[str, Any]], current: Dict[str, Dict[str, Any]]) -> Dict[str, List]:
    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))
    repriced = sorted(
        key for key in set(previous) & set(current) if previous[key].get("credits") != current[key].get("credits")
    )
    return {"added": added, "removed": removed, "repriced": repriced}


class CatalogMonitor:
    def __init__(
        self,
        db,
        fetch: Callable[[], Awaitable[list]],
        model_config: Callable[[], Dict[str, Dict[str, Any]]],
        alerts=None,
        *,
        interval_hours: float = DEFAULT_INTERVAL_HOURS,
    ):
        self.db = db
        self._fetch = fetch
        self._model_config = model_config
        self.alerts = alerts
        self.interval_seconds = max(0.01, float(interval_hours)) * 3600
        self._ready = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self.state: Dict[str, Any] = {
            "last_checked": None, "last_error": "", "report": None, "last_diff": None, "entries": 0,
        }

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        async with self.db._connect(write=True) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS catalog_snapshot (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    taken_at TEXT NOT NULL,
                    snapshot TEXT NOT NULL
                )
            """)
            await conn.commit()
        self._ready = True

    async def _previous(self) -> Optional[Dict[str, Dict[str, Any]]]:
        await self._ensure_table()
        async with self.db._connect() as conn:
            row = await (await conn.execute("SELECT snapshot FROM catalog_snapshot WHERE id = 1")).fetchone()
        return json.loads(row[0]) if row else None

    async def _store(self, snapshot: Dict[str, Dict[str, Any]]) -> None:
        async with self.db._connect(write=True) as conn:
            await conn.execute(
                "INSERT INTO catalog_snapshot (id, taken_at, snapshot) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET taken_at = excluded.taken_at, snapshot = excluded.snapshot",
                (_now_iso(), json.dumps(snapshot, ensure_ascii=False)),
            )
            await conn.commit()

    async def check_once(self) -> Dict[str, Any]:
        """Read the table, compare, alert. Returns the current state."""
        async with self._lock:
            self.state["last_checked"] = _now_iso()
            try:
                catalog = parse_catalog(await self._fetch())
            except (CatalogFormatError, Exception) as exc:  # noqa: BLE001 - reported, never raised into the loop
                self.state["last_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                if self.alerts is not None:
                    await self.alerts.raise_condition(
                        "catalog_unreadable", f"Cannot read Flow's model table: {self.state['last_error']}",
                        severity="warning",
                    )
                return self.state
            self.state["last_error"] = ""
            if self.alerts is not None:
                await self.alerts.clear_condition("catalog_unreadable")

            report = compare(catalog, self._model_config())
            current = snapshot_of(catalog)
            previous = await self._previous()
            diff = diff_snapshots(previous, current) if previous is not None else None
            await self._store(current)
            self.state.update(
                report={
                    "flow_entries": report["flow_entries"],
                    "obsolete_local_keys": report["obsolete_local_keys"],
                    "limit_mismatches": report["limit_mismatches"],
                    "retiring": report["retiring"],
                },
                last_diff=diff,
                entries=len(current),
            )
            await self._alert(report, diff)
            return self.state

    async def _alert(self, report: Dict[str, Any], diff: Optional[Dict[str, List]]) -> None:
        if self.alerts is None:
            return
        obsolete = report["obsolete_local_keys"]
        if obsolete:
            await self.alerts.raise_condition(
                "catalog_obsolete_keys",
                f"Flow no longer lists {len(obsolete)} model key(s) this server submits: {', '.join(obsolete[:6])}"
                + (" …" if len(obsolete) > 6 else "") + ". Requests for those models will fail.",
                severity="critical", details={"keys": obsolete},
            )
        else:
            await self.alerts.clear_condition("catalog_obsolete_keys")
        mismatches = report["limit_mismatches"]
        if mismatches:
            await self.alerts.raise_condition(
                "catalog_limit_mismatch",
                f"{len(mismatches)} reference-image limit(s) differ from Flow's (e.g. {mismatches[0]['model_id']}).",
                severity="warning", details={"rows": mismatches[:10]},
            )
        else:
            await self.alerts.clear_condition("catalog_limit_mismatch")
        untagged = [row for row in report["retiring"] if row["local_untagged"]]
        if untagged:
            await self.alerts.raise_condition(
                "catalog_retirement_untagged",
                "Flow announced a retirement the registry does not carry: "
                + ", ".join(f"{row['group']} on {row['retires_on']}" for row in untagged) + ".",
                severity="warning", details={"rows": untagged},
            )
        else:
            await self.alerts.clear_condition("catalog_retirement_untagged")
        if diff and any(diff.values()):
            parts = [f"{len(diff[name])} {name}" for name in ("added", "removed", "repriced") if diff[name]]
            await self.alerts.announce(
                "catalog_changed", "Flow's model table changed: " + ", ".join(parts) + ".",
                severity="info", details={name: values[:30] for name, values in diff.items()},
            )

    # ----- lifecycle -----

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        await asyncio.sleep(FIRST_CHECK_DELAY_SECONDS)
        while True:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                print(f"[catalog] check failed: {type(exc).__name__}: {exc}", flush=True)
            await asyncio.sleep(self.interval_seconds)

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
