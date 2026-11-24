"""Model registry changes taken from Flow's live model table (2026-11-24)."""

from datetime import date

import pytest
from fastapi import HTTPException

from src.api import routes
from src.core.model_resolver import get_model_catalog, get_model_parameter_contracts, is_model_retired
from src.services.generation_handler import MODEL_CONFIG


def test_omni_reference_limits_follow_flow():
    # Flow's table: Omni 1.2 reference-to-video 10 inputs, Omni 1.1 7. Veo stays at 3.
    for model_id, config in MODEL_CONFIG.items():
        if config.get("video_type") != "omni":
            continue
        expected = 7 if str(config["model_key"]).startswith("abra_") else 10
        assert config["max_images"] == expected, model_id
    assert MODEL_CONFIG["veo-3.1-lite-r2v-8s-landscape"]["max_images"] == 3


def test_omni_12_360p_variants_use_flows_360p_keys_for_text_and_references():
    for seconds in (3, 8, 15):
        for orientation in ("landscape", "portrait"):
            config = MODEL_CONFIG[f"omni-1.2-flash-360p-{seconds}s-{orientation}"]
            assert config["model_key"] == f"macaron_cookie_t2v_{seconds}s_360p"
            assert config["reference_model_key"] == f"macaron_cookie_r2v_{seconds}s_360p"
            assert config["listed"] is True
    # 360p is an explicit ID only: no family name that would need its own parameter table.
    assert "omni-1.2-flash-360p" not in MODEL_CONFIG
    assert all(item["id"] != "omni-1.2-flash-360p" for item in get_model_parameter_contracts(MODEL_CONFIG))


def test_nano_banana_pro_is_listed_and_uses_the_gem_pix_2_model():
    pro = {model_id: config for model_id, config in MODEL_CONFIG.items() if config.get("display_name") == "Nano Banana Pro"}
    assert len(pro) == 15 and all(model_id.startswith("gemini-3.0-pro-image-") for model_id in pro)
    assert all(config["listed"] and config["model_name"] == "GEM_PIX_2" for config in pro.values())
    assert "gemini-3.0-pro-image-landscape" in {item["id"] for item in get_model_catalog(MODEL_CONFIG)}


def test_families_leaving_flow_on_2026_12_05_are_tagged_and_the_rest_are_not():
    tagged = lambda model_id: MODEL_CONFIG[model_id].get("retires_on")  # noqa: E731
    for model_id in ("veo-3.1-fast", "veo-3.1-quality", "veo-3.1-fast-8s-landscape", "omni-1.1-flash",
                     "omni-1.1-flash-8s-landscape", "veo_3_1_t2v_fast_portrait_ultra"):
        assert tagged(model_id) == "2026-12-05", model_id
    for model_id in ("veo-3.1-lite", "veo-3.1-lite-r2v-8s-landscape", "omni-1.2-flash", "omni-1.2-flash-8s-landscape",
                     "omni-1.2-flash-360p-8s-landscape", "gemini-3.1-flash-image-landscape"):
        assert tagged(model_id) is None, model_id


def test_retirement_date_is_inclusive_and_untagged_models_never_retire():
    config = {"retires_on": "2026-12-05"}
    assert not is_model_retired(config, date(2026, 12, 4))
    assert is_model_retired(config, date(2026, 12, 5))
    assert not is_model_retired({}, date(2999, 1, 1))


def test_a_retired_model_disappears_from_listings_and_is_refused(monkeypatch):
    monkeypatch.setitem(MODEL_CONFIG["veo-3.1-fast"], "retires_on", "2000-01-01")
    assert "veo-3.1-fast" not in {item["id"] for item in routes._get_openai_model_catalog()}
    assert "veo-3.1-fast" not in routes._get_gemini_model_catalog()
    assert "veo-3.1-fast" not in {item["id"] for item in get_model_catalog(MODEL_CONFIG)}
    with pytest.raises(HTTPException) as refused:
        routes._resolve_request_model("veo-3.1-fast", object())
    assert refused.value.status_code == 400 and "2000-01-01" in refused.value.detail


def test_a_model_that_has_not_retired_yet_is_listed_with_its_date(monkeypatch):
    monkeypatch.setitem(MODEL_CONFIG["omni-1.1-flash-8s-landscape"], "retires_on", "2999-01-01")
    listed = {item["id"]: item["description"] for item in routes._get_openai_model_catalog()}
    assert listed["omni-1.1-flash-8s-landscape"].endswith("(retires 2999-01-01)")
    assert "retires" not in listed["omni-1.2-flash-8s-landscape"]
