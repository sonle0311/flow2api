"""Decode Flow's live model table and compare it with MODEL_CONFIG.

The Flow web app loads its model table with the batchexecute RPC ``HTrJv``. The payload is a
positional (protobuf-style) array, so field meaning is by index (observed 2026-11-24):

    payload[0][3]   alias map: [[model_key, [display name]], ...]
    payload[0][4]   video groups;  payload[0][5] image groups
    group           [display_name, [entry, ...], ..., enabled, family_key, ..., [y, m, d]]
                    the optional [y, m, d] is the date Flow retires the group
    entry           [0] model key, [4] credits per service tier, [9] max input media,
                    [16] seconds

Entry index 9 is read as "max reference inputs". It matches independently published limits:
Veo 3.1 reference-to-video 3, Omni 1.2 extend 3 (Flow help page) and Omni 1.2 reference-to-video
10 (seen in the Flow UI). A positional format can change without notice, so parsing is strict:
anything unexpected raises CatalogFormatError instead of producing a partial answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

RPC_ID = "HTrJv"
_SECTIONS = {4: "video", 5: "image", 7: "other"}


class CatalogFormatError(ValueError):
    """The response is not the model table layout this module understands."""


@dataclass
class CatalogEntry:
    key: str
    group: str
    section: str
    max_inputs: Optional[int]
    seconds: Optional[int]
    credits: Dict[int, Optional[int]] = field(default_factory=dict)


@dataclass
class CatalogGroup:
    name: str
    family: Optional[str]
    section: str
    retires_on: Optional[str]
    keys: List[str]


@dataclass
class FlowCatalog:
    entries: Dict[str, CatalogEntry]
    groups: List[CatalogGroup]
    alias_keys: set


def extract_payload(text: str, rpc_id: str = RPC_ID) -> list:
    """Return the decoded payload of ``rpc_id`` from a batchexecute response body."""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("[["):
            continue
        try:
            frames = json.loads(line)
        except ValueError:
            continue
        for frame in frames:
            if isinstance(frame, list) and len(frame) > 2 and frame[0] == "wrb.fr" and frame[1] == rpc_id:
                if not isinstance(frame[2], str):
                    raise CatalogFormatError(f"{rpc_id} returned no payload")
                try:
                    return json.loads(frame[2])
                except ValueError as exc:
                    raise CatalogFormatError(f"{rpc_id} payload is not JSON") from exc
    raise CatalogFormatError(f"{rpc_id} not found in response")


def _credits(raw: Any) -> Dict[int, Optional[int]]:
    result: Dict[int, Optional[int]] = {}
    for item in raw or []:
        tier, value = item[0], item[1]
        cost = None
        if isinstance(value, list) and value and isinstance(value[0], list) and len(value[0]) > 1:
            cost = value[0][1] if isinstance(value[0][1], int) else None
        result[tier] = cost
    return result


def _at(row: list, index: int) -> Any:
    return row[index] if len(row) > index else None


def parse_catalog(payload: list) -> FlowCatalog:
    try:
        body = payload[0]
        alias_keys = {row[0] for row in (body[3] or [])}
        entries: Dict[str, CatalogEntry] = {}
        groups: List[CatalogGroup] = []
        for index, section in _SECTIONS.items():
            for raw in body[index] or []:
                name, raw_entries = raw[0], raw[1]
                tail = raw[2:]
                retires = next(
                    (f"{item[0]:04d}-{item[1]:02d}-{item[2]:02d}" for item in tail
                     if isinstance(item, list) and len(item) == 3 and all(isinstance(n, int) for n in item)),
                    None,
                )
                family = next((item for item in tail if isinstance(item, str)), None)
                keys = []
                for entry in raw_entries:
                    key = entry[0]
                    max_inputs, seconds = _at(entry, 9), _at(entry, 16)
                    entries[key] = CatalogEntry(
                        key=key, group=name, section=section,
                        max_inputs=max_inputs if isinstance(max_inputs, int) else None,
                        seconds=seconds if isinstance(seconds, int) else None,
                        credits=_credits(_at(entry, 4)),
                    )
                    keys.append(key)
                groups.append(CatalogGroup(name, family, section, retires, keys))
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise CatalogFormatError(f"unexpected model table layout: {exc}") from exc
    if not entries:
        raise CatalogFormatError("model table has no entries")
    return FlowCatalog(entries=entries, groups=groups, alias_keys=alias_keys)


def _local_keys(model_config: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    """Flow model key -> local model IDs that submit it."""
    used: Dict[str, List[str]] = {}
    for model_id, config in model_config.items():
        keys = [config.get("model_key"), config.get("reference_model_key")]
        if config.get("type") == "image":
            keys = [config.get("model_name")]
            upsample = str(config.get("upsample") or "")
            if upsample.endswith(("2K", "4K")):
                # Flow has one shared image upsampler (GEM_PIX_2_UPSAMPLE_2K/4K) for every image model.
                keys.append(f"GEM_PIX_2_UPSAMPLE_{upsample[-2:]}")
        for key in keys:
            if key:
                used.setdefault(key, []).append(model_id)
    return used


def compare(catalog: FlowCatalog, model_config: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Differences between Flow's table and the local registry."""
    used = _local_keys(model_config)
    unused: Dict[str, List[str]] = {}
    for entry in catalog.entries.values():
        if entry.key not in used:
            unused.setdefault(entry.group, []).append(entry.key)
    known = set(catalog.entries) | catalog.alias_keys
    obsolete = sorted(key for key in used if key not in known)

    limit_mismatches = []
    for entry in catalog.entries.values():
        if entry.max_inputs is None:
            continue
        for model_id in used.get(entry.key, []):
            config = model_config[model_id]
            reference = config.get("reference_model_key") == entry.key or config.get("video_type") == "r2v"
            if config.get("type") != "video" or not reference:
                continue
            if config.get("max_images") != entry.max_inputs:
                limit_mismatches.append({
                    "flow_key": entry.key, "model_id": model_id,
                    "local_max_images": config.get("max_images"), "flow_max_inputs": entry.max_inputs,
                })

    retiring = []
    for group in catalog.groups:
        if group.retires_on:
            local = [model_config[i] for i in sorted({i for key in group.keys for i in used.get(key, [])})]
            retiring.append({
                "group": group.name, "retires_on": group.retires_on,
                "local_models": len(local),
                "local_untagged": sum(1 for config in local if config.get("retires_on") != group.retires_on),
            })
    return {
        "flow_entries": len(catalog.entries),
        "local_keys": len(used),
        "unused_by_flow_group": {group: sorted(keys) for group, keys in unused.items()},
        "obsolete_local_keys": obsolete,
        "limit_mismatches": sorted(limit_mismatches, key=lambda row: (row["flow_key"], row["model_id"])),
        "retiring": retiring,
    }


def format_report(report: Dict[str, Any]) -> str:
    lines = [f"Flow entries: {report['flow_entries']}   local Flow keys: {report['local_keys']}"]
    unused = report["unused_by_flow_group"]
    lines.append(f"\nIn Flow, not used locally ({sum(len(v) for v in unused.values())}):")
    for group, keys in unused.items():
        preview = ", ".join(keys[:4]) + (f", ... (+{len(keys) - 4})" if len(keys) > 4 else "")
        lines.append(f"  {group}: {len(keys)}  {preview}")
    lines.append(f"\nUsed locally, unknown to Flow ({len(report['obsolete_local_keys'])}):")
    lines.extend(f"  {key}" for key in report["obsolete_local_keys"])
    lines.append(f"\nReference-image limit differences ({len(report['limit_mismatches'])}):")
    lines.extend(
        f"  {row['model_id']} ({row['flow_key']}): local {row['local_max_images']} / Flow {row['flow_max_inputs']}"
        for row in report["limit_mismatches"]
    )
    lines.append("\nRetiring families:")
    for row in report["retiring"]:
        flag = "ok" if not row["local_untagged"] else f"{row['local_untagged']} local models lack retires_on"
        lines.append(f"  {row['group']}: {row['retires_on']} ({row['local_models']} local models, {flag})")
    return "\n".join(lines)
