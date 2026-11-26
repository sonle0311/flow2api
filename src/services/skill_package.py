"""The flow2api client skill as a zip, built from the copy that ships with this server.

Agents on other machines install it from the console (Agent skill tab). Building it on request
keeps the model table inside (references/contract.json) the same as the one this server serves.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Optional

SKILLS_ROOT = Path(__file__).resolve().parents[2] / ".agents" / "skills"
# Only the client skill is meant to be installed elsewhere; flow2api-gateway-ops works on this repository.
DOWNLOADABLE = ("flow2api",)
_SKIPPED_DIRS = {"__pycache__", "evals"}
_SKIPPED_SUFFIXES = {".pyc", ".pyo"}


def build_skill_zip(name: str, root: Optional[Path] = None) -> Optional[bytes]:
    """Zip of skill `name` with the skill folder as the single top-level entry, or None when unknown."""
    if name not in DOWNLOADABLE:
        return None
    base = (root or SKILLS_ROOT) / name
    if not (base / "SKILL.md").is_file():
        return None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(base.rglob("*")):
            relative = path.relative_to(base)
            if not path.is_file() or path.suffix in _SKIPPED_SUFFIXES or _SKIPPED_DIRS & set(relative.parts):
                continue
            info = zipfile.ZipInfo(f"{name}/{relative.as_posix()}", date_time=(2026, 1, 1, 0, 0, 0))
            # Keep scripts runnable after unzip; everything else is plain data.
            info.external_attr = (0o755 if path.suffix == ".py" else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue()
