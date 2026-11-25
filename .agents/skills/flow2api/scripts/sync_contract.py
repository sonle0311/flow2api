#!/usr/bin/env python3
"""Regenerate references/contract.json from the gateway's own model registry.

    .venv/bin/python3.11 .agents/skills/flow2api/scripts/sync_contract.py          # write the file
    .venv/bin/python3.11 .agents/skills/flow2api/scripts/sync_contract.py --check  # exit 1 if it is stale

The client (flow2api.py) validates model, aspect, duration, mode and reference-image counts against
this file, so it must follow MODEL_CONFIG. tests/test_flow2api_skill.py runs the --check logic, so a
model change in the gateway fails the suite until this file is regenerated.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TARGET = Path(__file__).resolve().parents[1] / "references" / "contract.json"


def render() -> str:
    sys.path.insert(0, str(ROOT))
    from src.core.integration_reference import get_model_parameter_contracts
    from src.services.generation_handler import MODEL_CONFIG

    return json.dumps(get_model_parameter_contracts(MODEL_CONFIG), ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="do not write; exit 1 when the file differs")
    args = parser.parse_args()
    fresh = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != fresh:
            print(f"{TARGET} is stale; run sync_contract.py without --check", file=sys.stderr)
            return 1
        print("contract.json is current")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(fresh, encoding="utf-8")
    print(f"wrote {TARGET} ({len(json.loads(fresh))} model families)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
