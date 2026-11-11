"""Public model families select only combinations present in the local registry."""

import asyncio

import pytest

from src.api.routes import _normalize_gemini_request, _normalize_openai_request
from src.core import model_resolver
from src.core.models import ChatCompletionRequest, GeminiGenerateContentRequest
from src.services.generation_handler import MODEL_CONFIG


def _openai(model, video_config=None, **extra):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "A slow camera pan."}],
        **extra,
    }
    if video_config is not None:
        payload["generationConfig"] = {"videoConfig": video_config}
    return ChatCompletionRequest.model_validate(payload)


@pytest.mark.parametrize("seconds,ratio,expected", [
    (3, "16:9", "omni-1.2-flash-3s-landscape"),
    (10, "16:9", "omni-1.2-flash-10s-landscape"),
    (11, "9:16", "omni-1.2-flash-11s-portrait"),
    (15, "9:16", "omni-1.2-flash-15s-portrait"),
])
def test_omni_base_selects_requested_duration_and_orientation(seconds, ratio, expected):
    request = _openai("omni-1.2-flash", {"durationSeconds": seconds, "aspectRatio": ratio})
    assert model_resolver.resolve_model_name(request.model, request, MODEL_CONFIG) == expected


@pytest.mark.parametrize("model,config,expected", [
    ("omni-1.1-flash", {"durationSeconds": 10, "aspectRatio": "9:16"}, "omni-1.1-flash-10s-portrait"),
    ("veo-3.1-fast", {"durationSeconds": 6, "aspectRatio": "9:16"}, "veo-3.1-fast-6s-portrait"),
    ("veo-3.1-quality", {"mode": "i2v", "durationSeconds": 6, "aspectRatio": "9:16"}, "veo-3.1-quality-i2v-6s-portrait"),
    ("veo-3.1-lite", {"mode": "r2v", "aspectRatio": "9:16"}, "veo-3.1-lite-r2v-8s-portrait"),
    ("veo-3.1-fast", {"mode": "extend", "aspectRatio": "9:16"}, "veo-3.1-fast-extend-8s-portrait"),
    ("veo-3.1-lite", {"mode": "i2v"}, "veo-3.1-lite-i2v-4s-landscape"),
])
def test_veo_modes_and_omni_11_use_existing_public_variants(model, config, expected):
    assert model_resolver.resolve_model_name(model, _openai(model, config), MODEL_CONFIG) == expected


@pytest.mark.parametrize("model", ["omni-1.2-flash", "omni-1.1-flash", "veo-3.1-fast", "veo-3.1-lite", "veo-3.1-quality"])
def test_public_base_defaults_keep_eight_second_landscape(model):
    request = _openai(model)
    resolved = model_resolver.resolve_model_name(model, request, MODEL_CONFIG)
    assert MODEL_CONFIG[resolved]["model_key"] == MODEL_CONFIG[model]["model_key"]
    assert MODEL_CONFIG[resolved]["aspect_ratio"] == MODEL_CONFIG[model]["aspect_ratio"]


@pytest.mark.parametrize("model,config", [
    ("omni-1.2-flash", {"durationSeconds": 11, "aspectRatio": "16:9"}),
    ("omni-1.2-flash", {"durationSeconds": 2}),
    ("omni-1.2-flash", {"durationSeconds": 16}),
    ("omni-1.2-flash", {"durationSeconds": 8.5}),
    ("omni-1.2-flash", {"durationSeconds": True}),
    ("omni-1.2-flash", {"aspectRatio": "1:1"}),
    ("omni-1.2-flash", {"aspectRatio": "nonsense"}),
    ("omni-1.2-flash", {"mode": "i2v"}),
    ("omni-1.1-flash", {"durationSeconds": 5}),
    ("veo-3.1-fast", {"durationSeconds": 5}),
    ("veo-3.1-fast", {"mode": "i2v", "durationSeconds": 8}),
    ("veo-3.1-quality", {"mode": "r2v"}),
    ("veo-3.1-fast", {"mode": "unknown"}),
])
def test_unsupported_public_combinations_are_rejected(model, config):
    with pytest.raises(ValueError):
        request = _openai(model, config)
        model_resolver.resolve_model_name(model, request, MODEL_CONFIG)


@pytest.mark.parametrize("extra", [
    {"duration_seconds": 15, "aspect_ratio": "9:16"},
    {"extra_body": {"generationConfig": {"videoConfig": {"durationSeconds": 15, "aspectRatio": "9:16"}}}},
])
def test_openai_compatibility_fields_select_the_same_variant(extra):
    request = _openai("omni-1.2-flash", **extra)
    assert model_resolver.resolve_model_name(request.model, request, MODEL_CONFIG) == "omni-1.2-flash-15s-portrait"


def test_video_config_has_priority_over_top_level_compatibility_fields():
    request = _openai("omni-1.2-flash", {"durationSeconds": 4, "aspectRatio": "16:9"}, duration_seconds=15, aspect_ratio="9:16")
    assert model_resolver.resolve_model_name(request.model, request, MODEL_CONFIG) == "omni-1.2-flash-4s-landscape"


def test_concrete_video_and_legacy_alias_behavior_is_preserved():
    concrete = "omni-1.2-flash-8s-landscape"
    assert model_resolver.resolve_model_name(concrete, _openai(concrete, {"durationSeconds": 15, "aspectRatio": "9:16"}), MODEL_CONFIG) == concrete
    legacy = _openai("veo_3_1_t2v", generationConfig={"imageConfig": {"aspectRatio": "9:16", "imageSize": "4K"}})
    assert model_resolver.resolve_model_name(legacy.model, legacy, MODEL_CONFIG) == "veo_3_1_t2v_portrait_4k"


def test_openai_and_gemini_normalize_the_same_video_configuration():
    config = {"durationSeconds": 15, "aspectRatio": "9:16"}
    openai = _openai("omni-1.2-flash", config)
    gemini = GeminiGenerateContentRequest.model_validate({
        "contents": [{"role": "user", "parts": [{"text": "A slow camera pan."}]}],
        "generationConfig": {"videoConfig": config},
    })
    normalized_openai = asyncio.run(_normalize_openai_request(openai))
    normalized_gemini = asyncio.run(_normalize_gemini_request(openai.model, gemini))
    assert normalized_openai.model == normalized_gemini.model == "omni-1.2-flash-15s-portrait"


@pytest.mark.parametrize("extra", [
    {"generationConfig": {"videoConfig": {"durationSeconds": 15, "aspectRatio": "9:16"}}},
    {"extra_body": {"generationConfig": {"videoConfig": {"durationSeconds": 15, "aspectRatio": "9:16"}}}},
    {"duration_seconds": 15, "aspect_ratio": "9:16"},
])
def test_openai_contents_preserves_video_parameters(extra):
    request = ChatCompletionRequest.model_validate({
        "model": "omni-1.2-flash",
        "contents": [{"role": "user", "parts": [{"text": "A slow camera pan."}]}],
        **extra,
    })
    assert asyncio.run(_normalize_openai_request(request)).model == "omni-1.2-flash-15s-portrait"


def test_video_config_is_a_typed_schema():
    schema = ChatCompletionRequest.model_json_schema()
    assert "VideoConfig" in schema["$defs"]
    assert set(schema["$defs"]["VideoConfig"]["properties"]) >= {"durationSeconds", "aspectRatio", "mode"}


def test_capability_combinations_come_from_the_registry():
    contracts = {item["id"]: item for item in model_resolver.get_model_parameter_contracts(MODEL_CONFIG)}
    omni = contracts["omni-1.2-flash"]
    assert omni["config_path"] == "generationConfig.videoConfig"
    assert omni["defaults"] == {"durationSeconds": 8, "aspectRatio": "16:9", "mode": "auto"}
    assert len(omni["variants"]) == 21
    assert all(item["aspectRatio"] == "9:16" for item in omni["variants"] if item["durationSeconds"] > 10)
    assert "r2v" not in contracts["veo-3.1-quality"]["parameters"]["mode"]["values"]
    for contract in contracts.values():
        for variant in contract["variants"]:
            assert variant["id"] in MODEL_CONFIG

    reduced = dict(MODEL_CONFIG)
    del reduced["omni-1.2-flash-15s-portrait"]
    reduced_contract = next(item for item in model_resolver.get_model_parameter_contracts(reduced) if item["id"] == "omni-1.2-flash")
    assert 15 not in reduced_contract["parameters"]["durationSeconds"]["values"]
    with pytest.raises(ValueError):
        model_resolver.resolve_model_name("omni-1.2-flash", _openai("omni-1.2-flash", {"durationSeconds": 15, "aspectRatio": "9:16"}), reduced)


def test_integration_reference_exposes_parameter_contracts():
    from src.core.integration_reference import build_integration_reference
    from src.main import app

    reference = build_integration_reference(app)
    assert reference["model_parameters"] == model_resolver.get_model_parameter_contracts(MODEL_CONFIG)


@pytest.mark.parametrize("wrapper", ["extra_body", "extraBody"])
@pytest.mark.parametrize("invalid", [[], "invalid", 1, True])
def test_public_video_rejects_malformed_wrapped_generation_config(wrapper, invalid):
    request = _openai("omni-1.2-flash", **{wrapper: {"generationConfig": invalid}})
    with pytest.raises(model_resolver.ModelParameterError, match="generationConfig must be an object"):
        model_resolver.resolve_model_name(request.model, request, MODEL_CONFIG)


@pytest.mark.parametrize("wrapper", ["extra_body", "extraBody"])
@pytest.mark.parametrize("invalid", [[], "invalid"])
def test_public_video_rejects_malformed_wrapper_objects(wrapper, invalid):
    request = _openai("omni-1.2-flash", **{wrapper: invalid})
    with pytest.raises(model_resolver.ModelParameterError, match="must be an object"):
        model_resolver.resolve_model_name(request.model, request, MODEL_CONFIG)


@pytest.mark.parametrize("model,wrong_config,settings", [
    ("omni-1.2-flash", "imageConfig", {"aspectRatio": "9:16"}),
    ("gemini-3.1-flash-image", "videoConfig", {"durationSeconds": 8}),
])
@pytest.mark.parametrize("wrapped", [False, True])
def test_public_families_reject_meaningful_options_for_the_other_media_type(model, wrong_config, settings, wrapped):
    extra = {"generationConfig": {wrong_config: settings}}
    if wrapped:
        extra = {"extra_body": extra}
    request = _openai(model, **extra)
    with pytest.raises(model_resolver.ModelParameterError, match=wrong_config):
        model_resolver.resolve_model_name(model, request, MODEL_CONFIG)


@pytest.mark.parametrize("model,empty_config,expected", [
    ("omni-1.2-flash", "imageConfig", "omni-1.2-flash-8s-landscape"),
    ("gemini-3.1-flash-image", "videoConfig", "gemini-3.1-flash-image-landscape"),
])
@pytest.mark.parametrize("settings", [None, {}, {"aspectRatio": None}])
def test_empty_other_media_options_keep_default_behavior(model, empty_config, expected, settings):
    request = _openai(model, generationConfig={empty_config: settings})
    assert model_resolver.resolve_model_name(model, request, MODEL_CONFIG) == expected


@pytest.mark.parametrize("generation_config", [None, {}])
def test_empty_wrapped_generation_config_keeps_public_video_defaults(generation_config):
    request = _openai("omni-1.2-flash", extra_body={"generationConfig": generation_config})
    assert model_resolver.resolve_model_name(request.model, request, MODEL_CONFIG) == "omni-1.2-flash-8s-landscape"
