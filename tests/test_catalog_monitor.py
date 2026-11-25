"""Flow model-table monitor: what it alerts on, and when it stays quiet."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.core.database import Database
from src.services.catalog_monitor import CatalogMonitor, diff_snapshots
from src.services.flow_catalog import CatalogEntry, CatalogGroup, FlowCatalog


def catalog(prices, retires=None):
    entries = {key: CatalogEntry(key=key, group="Omni", section="video", max_inputs=None, seconds=None, credits={1: cost}) for key, cost in prices.items()}
    return FlowCatalog(entries=entries, groups=[CatalogGroup("Omni", None, "video", retires, list(entries))], alias_keys=set())


REGISTRY = {"local-a": {"type": "video", "model_key": "k1"}}


class CatalogMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(str(Path(self.temp.name) / "flow.db"))
        await self.db.init_db()
        self.table = catalog({"k1": 10, "k2": 20})
        self.alerts = SimpleNamespace(raise_condition=AsyncMock(), clear_condition=AsyncMock(), announce=AsyncMock())
        self.fetch = AsyncMock(return_value=["payload"])
        patcher = patch("src.services.catalog_monitor.parse_catalog", side_effect=lambda payload: self.table)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.registry = dict(REGISTRY)
        self.monitor = CatalogMonitor(self.db, self.fetch, lambda: self.registry, self.alerts)

    def raised(self):
        return [call.args[0] for call in self.alerts.raise_condition.await_args_list]

    async def test_first_reading_only_sets_the_baseline(self):
        state = await self.monitor.check_once()
        self.assertIsNone(state["last_diff"])
        self.assertEqual(2, state["entries"])
        self.alerts.announce.assert_not_awaited()
        self.assertEqual([], self.raised())

    async def test_added_removed_and_repriced_models_are_announced_once(self):
        await self.monitor.check_once()
        self.table = catalog({"k1": 12, "k3": 5})  # k2 gone, k3 new, k1 re-priced
        state = await self.monitor.check_once()
        self.assertEqual({"added": ["k3"], "removed": ["k2"], "repriced": ["k1"]}, state["last_diff"])
        self.alerts.announce.assert_awaited_once()
        message = self.alerts.announce.await_args.args[1]
        self.assertIn("1 added", message)
        self.assertIn("1 removed", message)
        self.assertIn("1 repriced", message)
        await self.monitor.check_once()  # nothing changed since: no second announcement
        self.alerts.announce.assert_awaited_once()

    async def test_a_model_key_flow_dropped_is_critical_and_clears_when_fixed(self):
        self.registry["local-b"] = {"type": "video", "model_key": "veo_3_1_extend_gone"}
        state = await self.monitor.check_once()
        self.assertEqual(["veo_3_1_extend_gone"], state["report"]["obsolete_local_keys"])
        call = next(c for c in self.alerts.raise_condition.await_args_list if c.args[0] == "catalog_obsolete_keys")
        self.assertEqual("critical", call.kwargs["severity"])
        self.assertIn("veo_3_1_extend_gone", call.args[1])
        del self.registry["local-b"]
        await self.monitor.check_once()
        self.alerts.clear_condition.assert_any_await("catalog_obsolete_keys")

    async def test_a_retirement_the_registry_does_not_carry_is_reported(self):
        self.table = catalog({"k1": 10}, retires="2026-12-05")
        await self.monitor.check_once()
        self.assertIn("catalog_retirement_untagged", self.raised())
        self.registry["local-a"]["retires_on"] = "2026-12-05"
        await self.monitor.check_once()
        self.alerts.clear_condition.assert_any_await("catalog_retirement_untagged")

    async def test_unreadable_table_is_reported_without_raising_and_recovers(self):
        self.fetch.side_effect = RuntimeError("no active account with a Google session")
        state = await self.monitor.check_once()
        self.assertIn("no active account", state["last_error"])
        self.assertIn("catalog_unreadable", self.raised())
        self.fetch.side_effect = None
        state = await self.monitor.check_once()
        self.assertEqual("", state["last_error"])
        self.alerts.clear_condition.assert_any_await("catalog_unreadable")

    async def test_snapshot_survives_a_restart(self):
        await self.monitor.check_once()
        self.table = catalog({"k1": 10, "k2": 20, "k9": 1})
        restarted = CatalogMonitor(self.db, self.fetch, lambda: self.registry, self.alerts)
        state = await restarted.check_once()
        self.assertEqual(["k9"], state["last_diff"]["added"])

    def test_diff_ignores_key_order_and_unchanged_prices(self):
        old = {"a": {"group": "g", "credits": {"1": 5}}, "b": {"group": "g", "credits": {}}}
        self.assertEqual({"added": [], "removed": [], "repriced": []}, diff_snapshots(old, dict(reversed(list(old.items())))))


if __name__ == "__main__":
    unittest.main()
