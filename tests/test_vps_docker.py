"""VPS bootstrap configuration must never inherit workstation credentials."""

import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest
import tomli


ROOT = Path(__file__).resolve().parents[1]


def config_module():
    path = ROOT / "docker" / "prepare_vps_config.py"
    spec = importlib.util.spec_from_file_location("prepare_vps_config", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def credentials(**updates):
    return {
        "FLOW2API_INITIAL_ADMIN_PASSWORD": 'private-password-"with-quote',
        "FLOW2API_INITIAL_API_KEY": "private-api-key-1234567890",
        "FLOW2API_INITIAL_ADMIN_USERNAME": "operator",
        **updates,
    }


def test_generated_config_uses_initial_credentials_and_keeps_other_settings(tmp_path):
    target = tmp_path / "setting.toml"
    config_module().prepare_config(ROOT / "config/setting_example.toml", target, credentials())
    with target.open("rb") as handle:
        config = tomli.load(handle)
    assert config["global"]["admin_password"] == credentials()["FLOW2API_INITIAL_ADMIN_PASSWORD"]
    assert config["global"]["api_key"] == credentials()["FLOW2API_INITIAL_API_KEY"]
    assert config["global"]["admin_username"] == "operator"
    assert config["server"] == {"host": "0.0.0.0", "port": 8000}
    assert config["flow"]["labs_base_url"] == "https://flow.google.com"
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize("name,value", [
    ("FLOW2API_INITIAL_ADMIN_PASSWORD", ""),
    ("FLOW2API_INITIAL_ADMIN_PASSWORD", "admin"),
    ("FLOW2API_INITIAL_API_KEY", "han1234"),
    ("FLOW2API_INITIAL_API_KEY", "private-key-with\nline-break"),
])
def test_invalid_initial_secrets_do_not_create_or_replace_config(tmp_path, name, value):
    target = tmp_path / "setting.toml"
    target.write_text("unchanged", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        config_module().prepare_config(ROOT / "config/setting_example.toml", target, credentials(**{name: value}))
    assert name in str(exc.value)
    assert value not in str(exc.value) if value else True
    assert target.read_text(encoding="utf-8") == "unchanged"


def test_regeneration_does_not_read_a_local_config_or_print_secrets(tmp_path, capsys):
    target = tmp_path / "setting.toml"
    target.write_text('[global]\napi_key="LOCAL-WORKSTATION-SECRET"\n', encoding="utf-8")
    config_module().prepare_config(ROOT / "config/setting_example.toml", target, credentials())
    assert "LOCAL-WORKSTATION-SECRET" not in target.read_text(encoding="utf-8")
    output = capsys.readouterr()
    assert credentials()["FLOW2API_INITIAL_API_KEY"] not in output.out + output.err


def test_seccomp_permits_chrome_namespaces_without_allowing_everything():
    profile = json.loads((ROOT / "docker/seccomp.chrome.json").read_text(encoding="utf-8"))
    assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
    allowed = {name for entry in profile["syscalls"] if entry["action"] == "SCMP_ACT_ALLOW" for name in entry["names"]}
    assert {"clone", "setns", "unshare"} <= allowed


def test_vps_runtime_uses_nonroot_named_volumes_and_only_the_app_port():
    compose = (ROOT / "docker-compose.vps.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.vps").read_text(encoding="utf-8")
    assert "USER app" in dockerfile
    assert "google-chrome-stable" in dockerfile
    assert "FLOW2API_DESKTOP_ENABLED" in compose
    assert "127.0.0.1" in compose
    assert ":5900" not in compose and ":6080" not in compose
    assert "flow2api-vps-data:/app/data" in compose
    assert "flow2api-vps-tmp:/app/tmp" in compose
    assert "privileged:" not in compose
    assert "SYS_ADMIN" not in compose
