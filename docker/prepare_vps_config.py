"""Create container-local settings from the example and initial environment."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path


def _secret(environ, name):
    value = environ.get(name, "")
    if len(value) < 16 or not value.isprintable() or value != value.strip():
        raise ValueError(f"{name} must contain at least 16 printable characters without surrounding spaces")
    return value


def prepare_config(example_path, target_path, environ=None):
    environ = os.environ if environ is None else environ
    password = _secret(environ, "FLOW2API_INITIAL_ADMIN_PASSWORD")
    api_key = _secret(environ, "FLOW2API_INITIAL_API_KEY")
    username = environ.get("FLOW2API_INITIAL_ADMIN_USERNAME", "admin")
    if not username or len(username) > 128 or not username.isprintable() or username != username.strip():
        raise ValueError("FLOW2API_INITIAL_ADMIN_USERNAME must be a nonempty printable username")
    replacements = {
        "global": {"admin_username": username, "admin_password": password, "api_key": api_key},
        "server": {"host": "0.0.0.0", "port": 8000},
    }
    section = None
    seen = set()
    output = []
    for line in Path(example_path).read_text(encoding="utf-8").splitlines():
        heading = re.fullmatch(r"\s*\[([^\]]+)\]\s*", line)
        if heading:
            section = heading[1]
        assignment = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if assignment and assignment[1] in replacements.get(section, {}):
            key = assignment[1]
            line = f"{key} = {json.dumps(replacements[section][key], ensure_ascii=False)}"
            seen.add((section, key))
        output.append(line)
    expected = {(section, key) for section, values in replacements.items() for key in values}
    if seen != expected:
        raise ValueError("The example configuration is missing required global/server settings")
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, prefix=".vps-settings-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write("\n".join(output) + "\n")
        temporary.chmod(0o600)
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    try:
        prepare_config(root / "config/setting_example.toml", root / "config/setting.toml")
    except (OSError, ValueError) as exc:
        print(f"[vps] Configuration preparation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
