"""Prepare private first-run settings and start the Linux VPS Compose stack."""

import argparse
import ipaddress
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SECRET_KEYS = ("FLOW2API_INITIAL_ADMIN_PASSWORD", "FLOW2API_INITIAL_API_KEY")


def read_environment(path):
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _validate_listen(port, bind):
    try:
        valid_address = ipaddress.ip_address(bind).version == 4
    except ValueError:
        valid_address = False
    if not isinstance(port, int) or not 1 <= port <= 65535 or not valid_address:
        raise ValueError("Use a port from 1 to 65535 and an IPv4 bind address.")


def prepare_environment(project_dir, *, port=8000, bind="127.0.0.1"):
    _validate_listen(port, bind)
    root = Path(project_dir).resolve()
    path = root / ".env.vps"
    if not path.exists():
        values = {
            "FLOW2API_INITIAL_ADMIN_USERNAME": "admin",
            "FLOW2API_INITIAL_ADMIN_PASSWORD": secrets.token_urlsafe(32),
            "FLOW2API_INITIAL_API_KEY": secrets.token_urlsafe(32),
            "FLOW2API_BIND_ADDRESS": bind,
            "FLOW2API_PORT": str(port),
        }
        root.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            # Two setup invocations must never rotate each other's credentials.
            descriptor = None
        if descriptor is not None:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write("# Private initial credentials; keep this file on the VPS.\n")
                stream.writelines(f"{key}={value}\n" for key, value in values.items())
    values = read_environment(path)
    if any(len(values.get(key, "")) < 16 or values[key].lower() in {"admin", "han1234", "changeme"} for key in SECRET_KEYS):
        raise ValueError(".env.vps must contain a strong initial admin password and API key (at least 16 characters).")
    try:
        _validate_listen(int(values.get("FLOW2API_PORT", "8000")), values.get("FLOW2API_BIND_ADDRESS", "127.0.0.1"))
    except ValueError:
        raise ValueError("Invalid listen configuration in .env.vps.") from None
    if os.name == "posix":
        path.chmod(0o600)
    return path


def verify_docker():
    if not shutil.which("docker"):
        raise RuntimeError("Install Docker Engine and the Docker Compose v2 plugin first; see docs/DEPLOY_VPS_VI.md.")
    try:
        version = subprocess.run(["docker", "compose", "version", "--short"], check=True, capture_output=True, text=True).stdout.strip().lstrip("v")
        numbers = version.split(".")
        if tuple(int(item) for item in numbers[:2]) < (2, 20):
            raise RuntimeError("Docker Compose v2.20 or newer is required.")
        architecture = subprocess.run(["docker", "info", "--format", "{{.Architecture}}"], check=True, capture_output=True, text=True).stdout.strip()
    except (subprocess.CalledProcessError, ValueError):
        raise RuntimeError("Docker Engine must be running and accessible, with Docker Compose v2.20 or newer.") from None
    if architecture not in {"x86_64", "amd64"}:
        raise RuntimeError("This Chrome-based stack requires a Linux amd64/x86_64 Docker host; ARM64 is not supported.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, default=ROOT)
    parser.add_argument("--prepare-only", action="store_true", help="Generate .env.vps without starting Docker")
    parser.add_argument("--show-credentials", action="store_true", help="Explicitly display the initial credentials saved in .env.vps")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args()
    root = args.project_dir.resolve()
    try:
        if args.show_credentials:
            values = read_environment(root / ".env.vps")
            for key in ("FLOW2API_INITIAL_ADMIN_USERNAME", *SECRET_KEYS):
                print(f"{key}={values.get(key, '')}")
            return 0
        if not args.prepare_only:
            verify_docker()
        env = prepare_environment(root, port=args.port, bind=args.bind)
        print("Private initial credentials are saved in .env.vps; existing values are preserved.")
        if args.prepare_only:
            return 0
        command = ["docker", "compose", "--env-file", str(env), "-f", str(root / "docker-compose.vps.yml")]
        subprocess.run([*command, "config", "--quiet"], cwd=root, check=True)
        subprocess.run([*command, "up", "-d", "--build", "--wait", "--wait-timeout", "180"], cwd=root, check=True)
        print("Flow2API is running. View initial credentials: python3 docker/setup_vps.py --show-credentials")
        print("Access instructions and SSH tunnel: docs/DEPLOY_VPS_VI.md")
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        # Do not dump Compose's rendered configuration or environment secrets.
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
