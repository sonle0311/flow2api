"""Create a source deployment archive without local accounts, sessions or keys."""

import argparse
import fnmatch
import os
from pathlib import Path
import tarfile


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "env", "ENV", "__pycache__", ".pytest_cache",
    "data", "tmp", "logs", "dist", "backups", "backup", "browser_data", "browser_data_rt",
    "node_modules", ".idea", ".vscode",
}


def deployment_files(root):
    for directory, folders, files in os.walk(root):
        folders[:] = sorted(name for name in folders if name not in EXCLUDED_DIRS and not (Path(directory) / name).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(root)
            if path.is_symlink() or name.startswith(".env") or name in {"logs.txt", ".DS_Store"} or name.endswith((".pyc", ".log", ".bak", ".har")) or any(fnmatch.fnmatch(name, pattern) for pattern in ("*.db*", "*.sqlite*")):
                continue
            if relative.parts[0] == "config" and not name.endswith("_example.toml"):
                continue
            yield path, relative.as_posix()


def create_archive(source, destination):
    root = Path(source).resolve()
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for path, relative in deployment_files(root):
            if path.resolve() == output:
                continue
            info = archive.gettarinfo(str(path), arcname=relative)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o755 if path.suffix == ".sh" else 0o644
            with path.open("rb") as content:
                archive.addfile(info, content)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/flow2api-vps.tar.gz")
    args = parser.parse_args()
    print(create_archive(ROOT, args.output))
