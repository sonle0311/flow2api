"""Flow's model table decoder and its comparison with the local registry (no network)."""

import json

import pytest

from src.services.flow_catalog import (
    CatalogFormatError,
    compare,
    extract_payload,
    format_report,
    parse_catalog,
)


def entry(key, credit=None, max_inputs=None, seconds=None):
    """One positional entry in the layout Flow sends (see the module docstring)."""
    cost = [[None, credit]] if credit is not None else [None, []]
    row = [key, None, None, None, [[1, cost], [2, [[None, credit]] if credit is not None else [None, []]]],
           None, None, [[[[1]]]], None, max_inputs, True, None, [[2, 1]], None, 120, None, seconds]
    return row


def group(name, entries, family, retires=None):
    tail = [True, family]
    if retires:
        tail += [None, None, list(retires)]
    return [name, entries, *tail]


def payload():
    video = [
        group("Omni 1.2 Flash", [
            entry("macaron_cookie_t2v_8s", 24, None, 8),
            entry("macaron_cookie_r2v_8s", 24, 10, 8),
            entry("macaron_cookie_r2v_8s_360p", 8, 10, 8),
            entry("macaron_cookie_extend_10s", 30, 3, 10),
        ], "macaron_cookie"),
        group("Omni 1.1 Flash", [entry("abra_t2v_8s", 24, None, 8), entry("abra_r2v_8s", 24, 7, 8)],
              "abra", retires=(2026, 12, 5)),
        group("Veo 3.1 - Lite", [entry("veo_3_1_r2v_lite", 20, 3)], "veo_3_1_lite"),
    ]
    image = [group("Nano Banana Pro", [entry("GEM_PIX_2")], "nano_banana_pro")]
    return [[None, None, [], [["veo_3_1_t2v_fast_4s_relaxed", ["Veo 3.1 - Fast"]]], video, image, None, None]]


def response_text(inner):
    frames = [["wrb.fr", "HTrJv", json.dumps(inner), None, None, None, "generic"]]
    return ")]}'\n\n123\n" + json.dumps(frames) + "\n25\n" + json.dumps([["di", 12], ["af.httprm", 12, "x", 1]])


def test_decodes_keys_inputs_seconds_credits_and_retirement():
    catalog = parse_catalog(extract_payload(response_text(payload())))
    r2v = catalog.entries["macaron_cookie_r2v_8s_360p"]
    assert (r2v.max_inputs, r2v.seconds, r2v.credits) == (10, 8, {1: 8, 2: 8})
    assert catalog.entries["macaron_cookie_t2v_8s"].max_inputs is None
    free_tier_blocked = entry("macaron_cookie_t2v_15s", None, None, 15)
    assert parse_catalog([[None, None, [], [], [group("G", [free_tier_blocked], "g")], [], None, None]]) \
        .entries["macaron_cookie_t2v_15s"].credits == {1: None, 2: None}
    retiring = {g.name: g.retires_on for g in catalog.groups}
    assert retiring["Omni 1.1 Flash"] == "2026-12-05" and retiring["Omni 1.2 Flash"] is None
    assert "veo_3_1_t2v_fast_4s_relaxed" in catalog.alias_keys


def local_registry(**overrides):
    registry = {
        "omni-1.2-flash-8s-landscape": {"type": "video", "video_type": "omni", "model_key": "macaron_cookie_t2v_8s",
                                       "reference_model_key": "macaron_cookie_r2v_8s", "max_images": 10},
        "omni-1.1-flash-8s-landscape": {"type": "video", "video_type": "omni", "model_key": "abra_t2v_8s",
                                       "reference_model_key": "abra_r2v_8s", "max_images": 7,
                                       "retires_on": "2026-12-05"},
        "veo-r2v": {"type": "video", "video_type": "r2v", "model_key": "veo_3_1_r2v_lite", "max_images": 3},
        "veo-old": {"type": "video", "video_type": "t2v", "model_key": "veo_3_1_t2v_fast_4s_relaxed"},
        "gone": {"type": "video", "video_type": "extend", "model_key": "veo_3_1_extend_landscape"},
        "image": {"type": "image", "model_name": "GEM_PIX_2"},
    }
    registry.update(overrides)
    return registry


def test_report_lists_unused_obsolete_and_retiring_without_false_alarms():
    report = compare(parse_catalog(payload()), local_registry())
    assert report["limit_mismatches"] == []
    # The "relaxed" key is only an alias in Flow's table, so it is known and not obsolete.
    assert report["obsolete_local_keys"] == ["veo_3_1_extend_landscape"]
    assert report["unused_by_flow_group"] == {
        "Omni 1.2 Flash": ["macaron_cookie_extend_10s", "macaron_cookie_r2v_8s_360p"],
    }
    assert report["retiring"] == [{"group": "Omni 1.1 Flash", "retires_on": "2026-12-05",
                                   "local_models": 1, "local_untagged": 0}]


def test_reports_reference_limit_differences_and_untagged_retiring_models():
    registry = local_registry()
    registry["omni-1.2-flash-8s-landscape"]["max_images"] = 3
    del registry["omni-1.1-flash-8s-landscape"]["retires_on"]
    report = compare(parse_catalog(payload()), registry)
    assert report["limit_mismatches"] == [{"flow_key": "macaron_cookie_r2v_8s", "model_id": "omni-1.2-flash-8s-landscape",
                                           "local_max_images": 3, "flow_max_inputs": 10}]
    assert report["retiring"][0]["local_untagged"] == 1
    text = format_report(report)
    assert "local 3 / Flow 10" in text and "lack retires_on" in text


@pytest.mark.parametrize("text", [
    "", ")]}'\n\n5\n[[\"di\",1]]", response_text([[None, None, [], [], [], [], None, None]]),
    response_text([["unexpected"]]), response_text("not a table"),
])
def test_unrecognised_responses_raise_instead_of_returning_a_partial_answer(text):
    with pytest.raises(CatalogFormatError):
        parse_catalog(extract_payload(text))
