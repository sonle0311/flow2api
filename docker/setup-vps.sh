#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
if ! command -v python3 >/dev/null 2>&1; then
    echo "Install Python 3 first (Ubuntu/Debian: sudo apt-get install python3)." >&2
    exit 1
fi
exec python3 "${project_dir}/docker/setup_vps.py" --project-dir "${project_dir}" "$@"
