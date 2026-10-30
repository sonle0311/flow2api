import importlib.util
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "docker" / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_setup_generates_private_credentials_once_and_preserves_them(tmp_path):
    setup = module("setup_vps")
    env = setup.prepare_environment(tmp_path)
    first = env.read_text()
    values = setup.read_environment(env)
    assert len(values["FLOW2API_INITIAL_ADMIN_PASSWORD"]) >= 32
    assert len(values["FLOW2API_INITIAL_API_KEY"]) >= 32
    assert values["FLOW2API_INITIAL_ADMIN_PASSWORD"] != values["FLOW2API_INITIAL_API_KEY"]
    assert values["FLOW2API_BIND_ADDRESS"] == "127.0.0.1"
    assert values["FLOW2API_PORT"] == "8000"
    setup.prepare_environment(tmp_path)
    assert env.read_text() == first
    if os.name != "nt":
        assert env.stat().st_mode & 0o777 == 0o600


def test_setup_rejects_weak_existing_secrets_without_overwriting_them(tmp_path):
    setup = module("setup_vps")
    env = tmp_path / ".env.vps"
    before = "FLOW2API_INITIAL_ADMIN_PASSWORD=admin\nFLOW2API_INITIAL_API_KEY=weak\n"
    env.write_text(before)
    with pytest.raises(ValueError, match=".env.vps"):
        setup.prepare_environment(tmp_path)
    assert env.read_text() == before


@pytest.mark.parametrize("port,bind", [(0, "127.0.0.1"), (65536, "127.0.0.1"), (8000, "$(bad)")])
def test_setup_rejects_invalid_listen_configuration(tmp_path, port, bind):
    setup = module("setup_vps")
    with pytest.raises(ValueError):
        setup.prepare_environment(tmp_path, port=port, bind=bind)
    assert not (tmp_path / ".env.vps").exists()


def test_prepare_only_does_not_start_docker_or_print_secrets(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "docker/setup_vps.py"), "--project-dir", str(tmp_path), "--prepare-only"],
        text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    values = module("setup_vps").read_environment(tmp_path / ".env.vps")
    assert values["FLOW2API_INITIAL_ADMIN_PASSWORD"] not in result.stdout
    assert values["FLOW2API_INITIAL_API_KEY"] not in result.stdout


def test_deployment_archive_excludes_profiles_credentials_and_runtime_data(tmp_path):
    package = module("package_vps")
    source = tmp_path / "source"
    files = {
        "src/main.py": "app = True",
        "Dockerfile.vps": "FROM python",
        "docker-compose.vps.yml": "services: {}",
        "config/setting_example.toml": "[global]",
        "config/setting.toml": "PRIVATE_PASSWORD",
        ".env.vps": "PRIVATE_PASSWORD",
        "data/flow.db": "PRIVATE_COOKIE",
        "data/managed_browser_profiles/token-1/Cookies": "PRIVATE_COOKIE",
        "browser_data/Profile/Cookies": "PRIVATE_COOKIE",
        ".git/config": "PRIVATE_REMOTE",
        "tmp/result.png": "PRIVATE_OUTPUT",
        "logs.txt": "PRIVATE_LOG",
        "session.db-wal": "PRIVATE_WAL",
    }
    for name, value in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    archive = package.create_archive(source, tmp_path / "deploy.tar.gz")
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
        assert {"src/main.py", "Dockerfile.vps", "docker-compose.vps.yml", "config/setting_example.toml"} <= names
        assert not any(name.startswith(("data/", "tmp/", "browser_data/", ".git/")) for name in names)
        assert ".env.vps" not in names and "config/setting.toml" not in names
        assert "logs.txt" not in names and "session.db-wal" not in names
        assert all(not name.startswith("/") and ".." not in Path(name).parts for name in names)
