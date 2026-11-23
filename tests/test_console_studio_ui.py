"""Static guarantees for the console: complete locales, no inline code, no key leakage."""
import json
import re
from pathlib import Path

from src.core.model_resolver import get_model_parameter_contracts
from src.services.generation_handler import MODEL_CONFIG

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "static" / "console"
SOURCES = {item.name: item.read_text(encoding="utf-8") for item in CONSOLE.iterdir() if item.is_file() and item.suffix != ".json"}
LOCALES = json.loads((CONSOLE / "locales.json").read_text(encoding="utf-8"))
SCRIPTS = {name: text for name, text in SOURCES.items() if name.endswith(".js")}


def test_locales_cover_the_same_keys_with_real_text():
    assert set(LOCALES) == {"en", "vi", "zh-CN"}
    keys = set(LOCALES["en"])
    for language, catalogue in LOCALES.items():
        assert set(catalogue) == keys, language
        assert all(isinstance(value, str) and value.strip() for value in catalogue.values()), language
        for key, value in catalogue.items():
            assert set(re.findall(r"\{(\w+)\}", value)) == set(re.findall(r"\{(\w+)\}", LOCALES["en"][key])), (language, key)


def test_every_key_used_by_the_console_exists():
    keys = set(LOCALES["en"])
    used = set(re.findall(r"data-t(?:-title|-aria-label)?=\"([^\"]+)\"", SOURCES["index.html"]))
    for text in SCRIPTS.values():
        used |= set(re.findall(r"\bt\('([a-zA-Z_.]+)'", text))
        used |= set(re.findall(r"return '(studio\.block\.[a-zA-Z]+)'", text))
    used = {key for key in used if not key.endswith(".")}  # Prefixes are checked below.
    assert used, "no locale keys were found in the console sources"
    assert used <= keys, sorted(used - keys)
    # Keys assembled at runtime from a fixed prefix.
    contracts = get_model_parameter_contracts(MODEL_CONFIG)
    modes = {mode for contract in contracts for mode in contract["parameters"].get("mode", {}).get("values", [])}
    names = {name for contract in contracts for name in contract["parameters"]}
    assert {"mode." + mode for mode in modes} <= keys
    assert {"param." + name for name in names} <= keys
    assert {"type.image", "type.video"} <= keys
    assert {"error." + code for code in ("invalid_stream", "stream_ended", "no_result", "missing_api_key")} <= keys


def test_page_has_no_inline_code_and_loads_only_local_assets():
    page = SOURCES["index.html"]
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", page)
    assert "<style" not in page and " style=" not in page
    assert not re.search(r"\son[a-z]+=", page)
    for url in re.findall(r"(?:src|href)=\"([^\"]+)\"", page):
        assert url.startswith(("/", "#")), url
    for text in SOURCES.values():
        assert "http://" not in text.replace("http://www.w3.org/2000/svg", "") and "https://" not in text


def test_form_never_names_a_variant_model():
    variants = {variant["id"] for contract in get_model_parameter_contracts(MODEL_CONFIG) for variant in contract["variants"]}
    for name, text in SOURCES.items():
        assert not [variant for variant in variants if variant in text], name


def test_api_key_stays_in_memory():
    for name, text in SCRIPTS.items():
        for line in text.splitlines():
            if re.search(r"localStorage|sessionStorage|console\.|document\.cookie", line):
                assert not re.search(r"api_?key", line, re.IGNORECASE), (name, line)
    # Only the language preference is ever stored.
    stored = [line for text in SCRIPTS.values() for line in text.splitlines() if "Storage.setItem" in line or ".setItem(" in line]
    assert stored and all("STORAGE_KEY" in line for line in stored)
    assert "apiKey" not in SCRIPTS["studio.js"] and "apiKey" not in SCRIPTS["request-preview.js"]
    assert "innerHTML" not in SCRIPTS["app.js"] and SCRIPTS["studio.js"].count("innerHTML") == 1


def test_classic_pages_lead_into_the_console():
    static = ROOT / "static"
    login = (static / "login.html").read_text(encoding="utf-8")
    assert login.count("location.href='/console'") == 2 and "location.href='/manage'" not in login
    assert "['studio','tabTestPage','/console']" in (static / "instrument-shell.js").read_text(encoding="utf-8")
    # The classic pages share the console palette.
    assert "--instrument-bg:#0b0d12" in (static / "instrument.css").read_text(encoding="utf-8")
    assert "--instrument-accent:#34d399" in (static / "instrument.css").read_text(encoding="utf-8")
