"""Studio's base-model-plus-parameters logic agrees with the server's model registry.

Runs the console's pure JavaScript in Node against the real parameter contracts.
Nothing here starts the application, reads accounts or submits generation work.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.core.model_resolver import get_model_parameter_contracts, resolve_model_name
from src.core.models import ChatCompletionRequest
from src.services.generation_handler import MODEL_CONFIG

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
CONTRACTS = get_model_parameter_contracts(MODEL_CONFIG)
pytestmark = pytest.mark.skipif(NODE is None, reason="node is required for console script tests")


def run(script, payload, tmp_path):
    """Copy the browser modules to .mjs so Node loads them as ES modules."""
    for name in ("models", "request-preview", "api"):
        source = (ROOT / "static" / "console" / f"{name}.js").read_text(encoding="utf-8")
        (tmp_path / f"{name}.mjs").write_text(source, encoding="utf-8")
    (tmp_path / "run.mjs").write_text(
        "import fs from 'node:fs';\n"
        "import * as M from './models.mjs';\nimport * as P from './request-preview.mjs';\nimport * as A from './api.mjs';\n"
        "const input = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
        f"const result = await (async () => {{ {script} }})();\n"
        "console.log(JSON.stringify(result));\n", encoding="utf-8")
    done = subprocess.run([NODE, str(tmp_path / "run.mjs")], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_only_listed_base_models_are_offered_and_grouped(tmp_path):
    groups = run("return M.listModels(input.contracts);", {"contracts": CONTRACTS}, tmp_path)
    offered = {item["id"] for kind in groups.values() for item in kind}
    assert offered == {contract["id"] for contract in CONTRACTS if contract["listed"]}
    assert {item["id"] for item in groups["image"]} == {c["id"] for c in CONTRACTS if c["listed"] and c["type"] == "image"}
    assert all(item["label"] for kind in groups.values() for item in kind)
    variant_ids = {variant["id"] for contract in CONTRACTS for variant in contract["variants"]}
    assert not offered & variant_ids


def test_every_variant_is_reachable_and_resolves_on_the_server(tmp_path):
    script = """
    const out = [];
    for (const contract of input.contracts) {
        for (const variant of contract.variants) {
            const selection = {};
            for (const name of M.parameterNames(contract)) selection[name] = variant[name];
            const found = M.findVariant(contract, selection);
            const body = M.buildBody(contract, selection, {prompt: 'x', images: [], mediaId: 'm'});
            out.push({expected: variant.id, found: found && found.id, body});
        }
    }
    return out;"""
    results = run(script, {"contracts": CONTRACTS}, tmp_path)
    assert len(results) == sum(len(contract["variants"]) for contract in CONTRACTS) > 100
    for item in results:
        assert item["found"] == item["expected"]
        body = item["body"]
        assert body["stream"] is True and body["model"] != item["expected"]
        request = ChatCompletionRequest(**body)
        assert resolve_model_name(body["model"], request, MODEL_CONFIG) == item["expected"]


def test_defaults_and_offered_values_always_name_a_real_variant(tmp_path):
    script = """
    const problems = [];
    for (const contract of input.contracts) {
        const names = M.parameterNames(contract);
        const modes = contract.parameters.mode ? contract.parameters.mode.values : [undefined];
        for (const mode of modes) {
            let selection = M.initialSelection(contract, mode);
            if (!M.findVariant(contract, selection)) problems.push(['initial', contract.id, mode]);
            if (mode && selection.mode !== mode) problems.push(['mode', contract.id, mode]);
            // Walk every value of every control from every reachable state one step deep.
            for (const name of names) {
                for (const value of M.validValues(contract, selection, name)) {
                    const step = M.applyChange(contract, selection, name, value);
                    if (step.selection[name] !== value) problems.push(['kept', contract.id, name, value]);
                    if (!M.findVariant(contract, step.selection)) problems.push(['dead', contract.id, name, value]);
                    for (const other of names) {
                        if (other !== name && step.selection[other] !== selection[other] && !step.changed.includes(other)) {
                            problems.push(['silent', contract.id, name, value, other]);
                        }
                    }
                }
            }
        }
        const rejected = M.applyChange(contract, M.initialSelection(contract), names[0], '__nope__');
        if (rejected.changed.length || !M.findVariant(contract, rejected.selection)) problems.push(['reject', contract.id]);
    }
    return problems;"""
    assert run(script, {"contracts": CONTRACTS}, tmp_path) == []


def test_mode_change_applies_the_servers_mode_defaults(tmp_path):
    contract = next(c for c in CONTRACTS if len(c.get("mode_defaults", {})) > 1)
    mode = sorted(contract["mode_defaults"])[-1]
    script = "const c = input.contract; return M.applyChange(c, M.initialSelection(c), 'mode', input.mode).selection;"
    selection = run(script, {"contract": contract, "mode": mode}, tmp_path)
    assert selection == contract["mode_defaults"][mode]


def test_reference_rules_and_blocking_follow_the_variant(tmp_path):
    script = """
    return input.contracts.flatMap(contract => contract.variants.map(variant => {
        const selection = {};
        for (const name of M.parameterNames(contract)) selection[name] = variant[name];
        return {
            id: variant.id, rules: M.referenceRules(contract, selection),
            empty: M.blockingReason(contract, selection, {prompt: ' ', images: []}),
            bare: M.blockingReason(contract, selection, {prompt: 'x', images: [], mediaId: ''}),
        };
    }));"""
    variants = {variant["id"]: variant for contract in CONTRACTS for variant in contract["variants"]}
    for item in run(script, {"contracts": CONTRACTS}, tmp_path):
        variant, rules = variants[item["id"]], item["rules"]
        assert item["empty"] == "studio.block.prompt"
        assert rules["needsMediaId"] == (variant.get("mode") in {"extend", "edit"})
        assert rules["minImages"] == variant["locally_validated_min_images"]
        if variant["max_images"] is not None:
            assert rules["maxImages"] == variant["max_images"]
        if not variant["supports_images"]:
            assert rules["images"] is False
        if rules["needsMediaId"]:
            assert item["bare"] == "studio.block.mediaId"
        elif rules["images"] and rules["minImages"] > 0:
            assert item["bare"] == "studio.block.minImages"
        else:
            assert item["bare"] is None


def test_body_carries_references_only_where_the_variant_accepts_them(tmp_path):
    script = """
    const picture = 'data:image/png;base64,' + 'A'.repeat(4096);
    return input.contracts.map(contract => {
        const selection = M.initialSelection(contract);
        const rules = M.referenceRules(contract, selection);
        const body = M.buildBody(contract, selection, {prompt: ' hi ', images: Array(20).fill(picture), mediaId: 'abc'});
        return {rules, content: body.messages[0].content, json: P.toJson(body), curl: P.toCurl('http://h', body)};
    });"""
    for item in run(script, {"contracts": CONTRACTS}, tmp_path):
        content, rules = item["content"], item["rules"]
        images = [] if isinstance(content, str) else [part for part in content if part["type"] == "image_url"]
        assert len(images) == (rules["maxImages"] if rules["images"] else 0)
        assert (content if isinstance(content, str) else content[0]["text"]) == "hi"
        assert "AAAAAAAA" not in item["json"] and "AAAAAAAA" not in item["curl"]
        assert "$FLOW2API_API_KEY" in item["curl"] and "/v1/chat/completions" in item["curl"]


def test_count_is_capped_by_reported_capacity(tmp_path):
    script = """
    return [M.maxCount({image: {recommended_max_parallel_requests: 9}}, 'image'),
            M.maxCount({image: {recommended_max_parallel_requests: 2}}, 'image'),
            M.maxCount({image: {recommended_max_parallel_requests: 0}}, 'image'),
            M.maxCount({}, 'video'), M.maxCount(null, 'video')];"""
    assert run(script, {}, tmp_path) == [4, 2, 0, 0, 0]


def test_stream_parser_handles_split_frames_progress_and_errors(tmp_path):
    script = """
    const chunk = (delta) => 'data: ' + JSON.stringify({choices: [{delta}]}) + '\\n\\n';
    const text = chunk({reasoning_content: 'step 1\\nstep 2'}) + chunk({content: '![a](http://h/a.png)'})
        + chunk({content: "<video src='/tmp/v.mp4' controls>"}) + 'data: [DONE]\\n\\n';
    const parser = A.createStreamParser();
    for (let index = 0; index < text.length; index += 7) parser.push(text.slice(index, index + 7));
    let failure = '';
    try { A.createStreamParser().push('data: {"error":{"message":"quota"}}\\n\\n'); } catch (error) { failure = error.message; }
    return {state: parser.state, media: A.extractMedia(parser.state.content), failure,
            unsafe: A.extractMedia('![x](javascript:alert(1)) ![y](data:text/html;base64,AA)')};"""
    result = run(script, {}, tmp_path)
    assert result["state"]["done"] is True and result["state"]["progress"] == "step 2"
    assert result["media"] == [{"kind": "image", "url": "http://h/a.png"}, {"kind": "video", "url": "/tmp/v.mp4"}]
    assert result["failure"] == "quota"
    assert result["unsafe"] == []
