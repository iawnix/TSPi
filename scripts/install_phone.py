"""Build the optional TS Phone server from GitHub and select its installed release."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from .install_from_github import check_phone_protocols, checkout_github
except ImportError:
    from install_from_github import check_phone_protocols, checkout_github


DEFAULT_PHONE_REPO = "https://github.com/iawnix/ts-phone.git"
INSTALL_SCHEMA = "tspi-phone-install/1"


def private_directory(path: Path) -> Path:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError(f"installation directory is not a physical directory: {path}")
    for parent in path.parents:
        if parent.is_symlink():
            raise ValueError(f"installation directory has a symbolic-link parent: {path}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def file_digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"TS Phone runtime file is missing or is not a regular file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_release(release: Path) -> dict[str, object]:
    record = json.loads((release / "installation.json").read_text(encoding="utf-8"))
    if record.get("schema_version") != INSTALL_SCHEMA or record.get("commit") != release.name:
        raise ValueError("TS Phone installation record does not match the release")
    files = record.get("files")
    required = {"package.json", "services/server/dist/index.js", "services/server/dist/cli.js"}
    if not isinstance(files, dict) or not required.issubset(files):
        raise ValueError("TS Phone installation record is missing runtime files")
    for name, digest in files.items():
        path = release / name
        if not path.resolve().is_relative_to(release.resolve()) or file_digest(path) != digest:
            raise ValueError(f"TS Phone installed file failed verification: {name}")
    return record


def prepare_phone(install_root: Path, repo: str, ref: str) -> Path:
    """Stage a complete server build; leave the active selection untouched."""
    root = private_directory(install_root)
    home = private_directory(private_directory(root / ".pi") / "ts-phone")
    releases = private_directory(home / "releases")
    node = shutil.which("node")
    npm = shutil.which("npm")
    if node is None or npm is None:
        raise ValueError("TS Phone installation requires Node.js and npm")
    version = subprocess.run([node, "-p", "process.versions.node"], capture_output=True, text=True, check=True).stdout.strip()
    if tuple(int(part) for part in version.split(".")) < (22, 19, 0):
        raise ValueError("TS Phone installation requires Node.js 22.19.0 or newer")
    with tempfile.TemporaryDirectory(prefix=".build-", dir=releases) as directory:
        source = Path(directory) / "source"
        print(f"TS Phone: fetching {repo} ({ref})", file=sys.stderr)
        commit = checkout_github(repo, ref, source)
        target = releases / commit
        if target.is_symlink():
            raise ValueError(f"TS Phone release cannot be a symbolic link: {target}")
        if target.exists():
            check_release(target)
            return target
        print("TS Phone: installing dependencies and building the server", file=sys.stderr)
        for command in ([npm, "ci", "--no-audit", "--no-fund"], [npm, "run", "build"]):
            subprocess.run(command, cwd=source, stdout=sys.stderr, stderr=sys.stderr, check=True)
        dist = source / "services/server/dist"
        for name in ("index.js", "cli.js"):
            subprocess.run([node, "--check", str(dist / name)], check=True, stdout=sys.stderr, stderr=sys.stderr)
        version = json.loads((source / "services/server/package.json").read_text(encoding="utf-8"))["version"]
        protocols = json.loads((source / "packages/protocol/versions.json").read_text(encoding="utf-8"))
        paths = [source / "package.json", source / "services/server/package.json",
                 *sorted((source / "packages/protocol").glob("*")), *sorted(dist.rglob("*"))]
        files = {path.relative_to(source).as_posix(): file_digest(path) for path in paths if not path.is_dir()}
        record = {"schema_version": INSTALL_SCHEMA, "repo": repo, "ref": ref, "commit": commit,
                  "server_version": version, "protocols": protocols, "node": node, "files": files}
        (source / "installation.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (source / "installation.json").chmod(0o600)
        # The server currently has no production npm dependencies. Keep any that a
        # subsequent release declares, while dropping the build-only toolchain.
        subprocess.run([npm, "prune", "--omit=dev", "--no-audit", "--no-fund"], cwd=source,
                       stdout=sys.stderr, stderr=sys.stderr, check=True)
        source.rename(target)
    return target


def activate_phone(install_root: Path, release: Path) -> dict[str, object]:
    root = install_root.resolve()
    home = root / ".pi/ts-phone"
    if release.parent != home / "releases" or release.is_symlink():
        raise ValueError("TS Phone release must belong to this installation")
    record = check_release(release)
    package = root / ".pi/packages/tspi/current/agent"
    check_phone_protocols(release, package)
    selections = {
        home / "current": release,
        root / "TSPhoneServer": package / "TSPi",
        root / "TSPhoneCtl": package / "TSPi",
    }
    for link in selections:
        if link.exists() and not link.is_symlink():
            raise ValueError(f"installation entrypoint already exists: {link}")
    old = {link: os.readlink(link) if link.is_symlink() else None for link in selections}
    changed: list[Path] = []
    try:
        for link, target in selections.items():
            atomic_link(link, os.path.relpath(target, link.parent))
            changed.append(link)
    except Exception:
        for link in reversed(changed):
            if old[link] is None:
                link.unlink()
            else:
                atomic_link(link, old[link])
        raise
    return {"repo": record["repo"], "commit": record["commit"], "server_version": record["server_version"],
            "root": str(release), "launcher": str(root / "TSPhoneServer")}


def atomic_link(link: Path, target: str) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{link.name}.", dir=link.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        temporary.unlink()
        temporary.symlink_to(target)
        os.replace(temporary, link)
    finally:
        temporary.unlink(missing_ok=True)
