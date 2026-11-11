"""Copyable agent handoffs stay client focused and agree with the local registry.

These tests run a pure JavaScript builder and mocked clients only. They never
start the application lifespan, read account data, or submit generation work.
"""

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.core.model_resolver import get_model_parameter_contracts, resolve_model_name
from src.core.models import ChatCompletionRequest, GeminiGenerateContentRequest
from src.services.generation_handler import MODEL_CONFIG


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
LOCALES = ("en", "vi", "zh-CN")
FAMILIES = {
    "gemini-3.0-pro-image", "gemini-3.1-flash-image", "gemini-3.1-flash-lite-image",
    "veo-3.1-fast", "veo-3.1-lite", "veo-3.1-quality", "omni-1.1-flash", "omni-1.2-flash",
}


def build_prompts(reference=None, root="https://example.com/proxy/flow", locales=LOCALES):
    script = """
const fs = require('fs');
global.window = {};
require('./static/integration-recipes.js');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
console.log(JSON.stringify(input.locales.map(locale =>
    window.Flow2APIIntegrationRecipes.buildAgentPrompt(input.root, locale, input.reference))));
"""
    data = {"root": root, "locales": locales, "reference": reference if reference is not None else {
        "model_parameters": get_model_parameter_contracts(MODEL_CONFIG),
        "endpoints": [{"path": "/api/tokens/DO-NOT-COPY"}],
        "schemas": {"RawSchemaSentinel": {"secret": "PRIVATE-DOCS-SENTINEL"}},
        "api_key": "PRIVATE-KEY-SENTINEL",
    }}
    result = subprocess.run([NODE, "-e", script], input=json.dumps(data), cwd=ROOT,
                            encoding="utf-8", capture_output=True, check=True)
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def prompts():
    return dict(zip(LOCALES, build_prompts()))


def table_rows(prompt, family):
    return [line.strip("| ").split(" | ") for line in prompt.splitlines()
            if line.startswith("| " + family + " | ")]


def test_handoff_is_localized_complete_and_client_focused(prompts):
    expected = {
        "en": ("existing application", "Do not stop at a plan", "Acceptance criteria", "mock"),
        "vi": ("ứng dụng hiện có", "Không dừng ở kế hoạch", "Tiêu chí nghiệm thu", "mock"),
        "zh-CN": ("现有应用", "不要停留在计划", "验收标准", "mock"),
    }
    for locale, prompt in prompts.items():
        assert len(prompt) < 80_000
        assert all(text in prompt for text in expected[locale])
        assert all(family in prompt for family in FAMILIES)
        assert "FLOW2API_BASE_URL" in prompt and "FLOW2API_API_KEY" in prompt
        assert "REPLACE_WITH_SERVER_API_KEY" in prompt
        assert "https://example.com/proxy/flow/v1beta/models/" in prompt
        assert "/api/" not in prompt
        assert all(text not in prompt for text in (
            "RawSchemaSentinel", "PRIVATE-DOCS-SENTINEL", "PRIVATE-KEY-SENTINEL",
            '"schemas":', '"variants":', '"endpoints":', '"model_parameters":',
        ))
        assert "generationConfig.videoConfig" in prompt and "generationConfig.imageConfig" in prompt
        assert "durationSeconds" in prompt and "integer" in prompt
        assert "imageSize" in prompt and "aspectRatio" in prompt
        assert "mediaGenerationId" in prompt and "extend://" in prompt
        assert "reasoning_content" in prompt and "[DONE]" in prompt
        assert "max_retries=0" in prompt and 'extra_body={"generationConfig"' in prompt
        assert "3600" in prompt and "innerHTML" in prompt
        # A small representative set of runnable examples is useful; exporting
        # every concrete model variant obscures the integration task.
        concrete = re.findall(r"(?:veo|omni)-[\w.-]+-\d+s-(?:landscape|portrait)", prompt)
        assert len(set(concrete)) < 10
        assert all(table_rows(prompt, family) for family in FAMILIES)


def test_contract_tables_preserve_exact_video_tuples_and_reference_bounds(prompts):
    contracts = get_model_parameter_contracts(MODEL_CONFIG)
    for prompt in prompts.values():
        for contract in contracts:
            if contract["type"] != "video":
                continue
            actual = set()
            for family, mode, ratios, seconds, references in table_rows(prompt, contract["id"]):
                # Video rows carry only actual correlated groups. Independent
                # lists of mode/ratio/duration would admit unsupported tuples.
                for ratio in ratios.split(", "):
                    for duration in seconds.split(", "):
                        actual.add((mode, ratio, int(duration), references))
            expected = set()
            for item in contract["variants"]:
                refs = f'{item["min_images"]}–{item["max_images"]}'
                if item["locally_validated_min_images"] != item["min_images"]:
                    refs += f' (local min {item["locally_validated_min_images"]})'
                expected.add((item["mode"], item["aspectRatio"], item["durationSeconds"], refs))
            assert actual == expected


def test_contract_tables_preserve_exact_image_tuples_and_reference_bounds(prompts):
    for prompt in prompts.values():
        for contract in get_model_parameter_contracts(MODEL_CONFIG):
            if contract["type"] != "image":
                continue
            actual = set()
            for family, ratios, sizes, references in table_rows(prompt, contract["id"]):
                for ratio in ratios.split(", "):
                    for size in sizes.split(", "):
                        actual.add((ratio, size, references))
            expected = {
                (item["aspectRatio"], item["imageSize"],
                 f'{item["min_images"]}–{item["max_images"] if item["max_images"] is not None else "unspecified"}')
                for item in contract["variants"]
            }
            assert actual == expected


def test_sparse_registry_does_not_infer_cartesian_combinations():
    contracts = copy.deepcopy(get_model_parameter_contracts(MODEL_CONFIG))
    video = next(item for item in contracts if item["id"] == "omni-1.2-flash")
    video["variants"] = [item for item in video["variants"] if
                         (item["durationSeconds"], item["aspectRatio"]) in {(3, "16:9"), (15, "9:16")}]
    image = next(item for item in contracts if item["id"] == "gemini-3.1-flash-image")
    image["variants"] = [item for item in image["variants"] if
                         (item["imageSize"], item["aspectRatio"]) in {("1K", "16:9"), ("4K", "9:16")}]
    prompt = build_prompts({"model_parameters": contracts}, locales=("en",))[0]
    assert table_rows(prompt, video["id"]) == [
        [video["id"], "auto", "16:9", "3", "0–3"],
        [video["id"], "auto", "9:16", "15", "0–3"],
    ]
    assert table_rows(prompt, image["id"]) == [
        [image["id"], "16:9", "1K", "0–unspecified"],
        [image["id"], "9:16", "4K", "0–unspecified"],
    ]


def test_unknown_reference_fields_and_invalid_defaults_are_not_copied():
    contracts = copy.deepcopy(get_model_parameter_contracts(MODEL_CONFIG))
    contracts[0]["defaults"]["aspectRatio"] = "PRIVATE-DEFAULT-SENTINEL"
    contracts[0]["variants"][0]["api_key"] = "PRIVATE-VARIANT-SENTINEL"
    prompt = build_prompts({"model_parameters": contracts}, locales=("en",))[0]
    assert "PRIVATE-DEFAULT-SENTINEL" not in prompt
    assert "PRIVATE-VARIANT-SENTINEL" not in prompt
    assert "- gemini-3.0-pro-image: unspecified" in prompt


@pytest.mark.parametrize("root", [
    "https://user:ROOT-SECRET@example.com/proxy/flow/v1/?key=QUERY-SECRET#HASH-SECRET",
    "https://example.com/proxy/flow/",
])
def test_root_keeps_proxy_prefix_without_leaking_url_credentials(root):
    prompt = build_prompts(root=root, locales=("en",))[0]
    assert "https://example.com/proxy/flow/v1beta/models/" in prompt
    assert all(secret not in prompt for secret in ("ROOT-SECRET", "QUERY-SECRET", "HASH-SECRET"))
    assert "/v1/v1" not in prompt


def test_root_is_safely_quoted_and_cannot_break_code_fences():
    prompt = build_prompts(root="https://example.com/flow/'$(```)/prefix", locales=("en",))[0]
    assert "%60%60%60" in prompt
    assert "'\\''" in prompt  # Bash single-quote escaping.
    assert "flow/''$(" in prompt  # PowerShell single-quote escaping.
    assert len(re.findall(r"^```", prompt, re.M)) % 2 == 0
    for block in re.findall(r"```javascript\n(.*?)\n```", prompt, re.S):
        subprocess.run([NODE, "--check"], input=block, encoding="utf-8", check=True, capture_output=True)


def test_examples_parse_and_resolve_against_registry(prompts):
    for prompt in prompts.values():
        video_families, modes = set(), set()
        for block in re.findall(r"```json\n(.*?)\n```", prompt, re.S):
            payload = json.loads(block)
            if "model" in payload and "messages" in payload:
                request = ChatCompletionRequest.model_validate(payload)
                assert resolve_model_name(request.model, request, MODEL_CONFIG) in MODEL_CONFIG
                if "videoConfig" in payload.get("generationConfig", {}):
                    video_families.add(request.model)
                    modes.add(payload["generationConfig"]["videoConfig"]["mode"])
            elif "contents" in payload:
                GeminiGenerateContentRequest.model_validate(payload)
        assert video_families == {family for family in FAMILIES if not family.startswith("gemini")}
        assert modes == {"t2v", "i2v", "r2v", "auto", "extend"}
        for block in re.findall(r"```python\n(.*?)\n```", prompt, re.S):
            compile(block, "agent-prompt-example", "exec")
        for block in re.findall(r"```javascript\n(.*?)\n```", prompt, re.S):
            subprocess.run([NODE, "--check"], input=block, encoding="utf-8", check=True, capture_output=True)


@pytest.mark.parametrize(("case", "expected"), [
    ("ok", "snowman ☃"),
    ("http", "HTTP 401"),
    ("stream-error", "mock generation failure"),
    ("truncated", "Stream ended before [DONE]"),
])
def test_runnable_sse_example_handles_mocked_network_chunks(prompts, case, expected):
    example = re.findall(r"```javascript\n(.*?)\n```", prompts["en"], re.S)[0]
    # The example invokes main itself. Replace only its final call to await it
    # in this entirely local harness; fetch never reaches the network.
    example = example.rsplit("main().catch", 1)[0]
    harness = """
const scenario = JSON.parse(process.argv[1]);
process.env.FLOW2API_BASE_URL = 'https://mock.invalid/prefix';
process.env.FLOW2API_API_KEY = 'MOCK-PLACEHOLDER';
global.fetch = async (url, options) => {
  if (url !== 'https://mock.invalid/prefix/v1/chat/completions') throw Error('Wrong URL');
  if (scenario === 'http') return new Response('Unauthorized', {status: 401});
  let data = scenario === 'stream-error'
    ? 'data: {"error":{"message":"mock generation failure"}}\\r\\n\\r\\n'
    : 'data: {"choices":[{"delta":{"reasoning_content":"working"}}]}\\r\\n\\r\\n' +
      'data: {"choices":[{"delta":{"content":"snowman ☃"}}]}\\r\\n\\r\\n';
  if (scenario !== 'truncated') data += 'data: [DONE]';
  const bytes = new TextEncoder().encode(data);
  const stream = new ReadableStream({start(controller) {
    for (let i=0; i<bytes.length; i++) controller.enqueue(bytes.slice(i, i+1));
    controller.close();
  }});
  return new Response(stream, {headers: {'Content-Type':'text/event-stream'}});
};
""" + example + "\nmain().then(value => console.log(value)).catch(error => console.log(error.message));"
    result = subprocess.run([NODE, "-e", harness, json.dumps(case)], cwd=ROOT,
                            encoding="utf-8", capture_output=True, check=True)
    assert expected in result.stdout
