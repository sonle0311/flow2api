"""The flow2api client skill must follow the gateway's model registry.

The skill (.agents/skills/flow2api) validates requests against references/contract.json, which is
generated from MODEL_CONFIG. A model change that is not followed by sync_contract.py fails here, so
the client can never keep accepting a combination the gateway dropped or reject a new one.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "flow2api"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sync():
    return _load("flow2api_sync_contract", SKILL / "scripts" / "sync_contract.py")


@pytest.fixture(scope="module")
def client():
    return _load("flow2api_client", SKILL / "scripts" / "flow2api.py")


def test_contract_file_matches_the_gateway_registry(sync):
    current = (SKILL / "references" / "contract.json").read_text(encoding="utf-8")
    assert current == sync.render(), "run .agents/skills/flow2api/scripts/sync_contract.py"


def test_client_accepts_every_variant_the_registry_lists(client):
    contract = client.load_contract()
    checked = 0
    for family in (c for c in contract.values() if c["type"] == "video"):
        for variant in family["variants"]:
            mode = variant["mode"]
            plan = client.resolve_video(
                contract, family["id"], mode, variant["aspectRatio"], variant["durationSeconds"],
                variant["min_images"], "SOURCE.1" if mode in ("extend", "edit") else None,
            )
            assert plan["variant"] == variant["id"]
            checked += 1
    assert checked > 100


def test_the_skills_own_suite_passes():
    result = subprocess.run(
        [sys.executable, str(SKILL / "scripts" / "test_flow2api.py")],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
