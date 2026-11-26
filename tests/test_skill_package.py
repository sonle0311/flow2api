"""The console's skill download: what is in the zip and who may fetch it."""

import io
import stat
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import admin
from src.services import skill_package


def _names(archive: bytes) -> list:
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        return zf.namelist()


def test_the_client_skill_unzips_into_one_folder_with_runnable_scripts():
    archive = skill_package.build_skill_zip("flow2api")
    names = _names(archive)
    assert "flow2api/SKILL.md" in names
    assert {"flow2api/scripts/flow2api.py", "flow2api/references/contract.json"} <= set(names)
    assert all(name.startswith("flow2api/") for name in names)
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        mode = zf.getinfo("flow2api/scripts/flow2api.py").external_attr >> 16
        assert mode & stat.S_IXUSR
        assert zf.read("flow2api/SKILL.md").startswith(b"---\nname: flow2api\n")


def test_caches_and_eval_data_are_left_out(tmp_path: Path):
    skill = tmp_path / "flow2api"
    (skill / "scripts" / "__pycache__").mkdir(parents=True)
    (skill / "evals").mkdir()
    (skill / "SKILL.md").write_text("---\nname: flow2api\n---\n", encoding="utf-8")
    (skill / "scripts" / "run.py").write_text("print(1)\n", encoding="utf-8")
    (skill / "scripts" / "__pycache__" / "run.cpython-311.pyc").write_bytes(b"\0")
    (skill / "evals" / "evals.json").write_text("{}", encoding="utf-8")
    assert _names(skill_package.build_skill_zip("flow2api", root=tmp_path)) == ["flow2api/SKILL.md", "flow2api/scripts/run.py"]


@pytest.mark.parametrize("name", ["flow2api-gateway-ops", "../flow2api", "nope", ""])
def test_only_the_client_skill_can_be_packaged(name):
    assert skill_package.build_skill_zip(name) is None


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(admin.router)
    return app, TestClient(app)


def test_download_needs_an_admin_session(client):
    _, http = client
    assert http.get("/api/admin/skills/flow2api/download").status_code == 401


def test_admin_downloads_the_zip_and_unknown_names_are_404(client):
    app, http = client
    app.dependency_overrides[admin.verify_admin_token] = lambda: "admin"
    response = http.get("/api/admin/skills/flow2api/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert 'filename="flow2api-skill.zip"' in response.headers["content-disposition"]
    assert "flow2api/SKILL.md" in _names(response.content)
    assert http.get("/api/admin/skills/flow2api-gateway-ops/download").status_code == 404
