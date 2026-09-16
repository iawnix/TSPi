"""Resolve and verify the pinned Pi source tree used by the native app server."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "config" / "pi-source.json"
PATCH_PATH = ROOT / "config" / "pi-worker-entry.patch"
MULTI_WORKSPACE_PATCH_PATH = ROOT / "config" / "pi-multi-workspace.patch"


class PiSourceError(RuntimeError):
    pass


def _pin() -> dict[str, object]:
    value = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("commit"), str):
        raise PiSourceError(f"invalid Pi source pin: {PIN_PATH}")
    return value


def _git(source: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(source), *args], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise PiSourceError(f"cannot inspect Pi source {source}: {detail.strip()}") from exc
    return result.stdout.strip()


def verify(source: Path) -> str:
    expected = str(_pin()["commit"])
    if not source.is_dir() or not (source / ".git").exists():
        raise PiSourceError(f"Pi source is not a Git checkout: {source}")
    commit = _git(source, "rev-parse", "HEAD")
    if commit != expected:
        raise PiSourceError(f"Pi source commit mismatch: expected {expected}, found {commit}")
    if not (source / "packages" / "coding-agent" / "src" / "experimental" / "cli.ts").is_file():
        raise PiSourceError(f"Pi source does not contain the experimental CLI: {source}")
    marker = "PI_SESSION_WORKER_ENTRY"
    process_path = source / "packages" / "coding-agent" / "src" / "experimental" / "process.ts"
    if marker not in process_path.read_text(encoding="utf-8"):
        raise PiSourceError(f"Pi source is missing the TSPi Worker entrypoint patch: {source}")
    sessions_path = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "sessions.ts"
    if "tspi.workspace-directory" not in sessions_path.read_text(encoding="utf-8"):
        raise PiSourceError(f"Pi source is missing the TSPi multi-workspace patch: {source}")
    return commit


def apply_worker_patch(source: Path) -> None:
    process_path = source / "packages" / "coding-agent" / "src" / "experimental" / "process.ts"
    if "PI_SESSION_WORKER_ENTRY" in process_path.read_text(encoding="utf-8"):
        return
    try:
        subprocess.run(["git", "-C", str(source), "apply", str(PATCH_PATH)], check=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to apply TSPi Worker entrypoint patch: {exc}") from exc


def apply_multi_workspace_patch(source: Path) -> None:
    sessions_path = source / "packages" / "coding-agent" / "src" / "experimental" / "services" / "sessions.ts"
    if "tspi.workspace-directory" in sessions_path.read_text(encoding="utf-8"):
        return
    try:
        subprocess.run(["git", "-C", str(source), "apply", str(MULTI_WORKSPACE_PATCH_PATH)], check=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to apply TSPi multi-workspace patch: {exc}") from exc


def clone(destination: Path) -> Path:
    pin = _pin()
    if destination.exists():
        raise PiSourceError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["git", "clone", "--no-checkout", str(pin["repository"]), str(destination)], check=True)
        _git(destination, "fetch", "--depth", "1", "origin", str(pin["commit"]))
        _git(destination, "checkout", "--detach", str(pin["commit"]))
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to clone pinned Pi source: {exc}") from exc
    apply_worker_patch(destination)
    apply_multi_workspace_patch(destination)
    verify(destination)
    return destination


def install(install_root: Path) -> Path:
    """Install the pinned, patched Pi tree used by App Server processes."""
    commit = str(_pin()["commit"])
    destination = install_root.resolve() / ".pi" / "runtime-cache" / "pi" / commit
    if destination.exists():
        apply_worker_patch(destination)
        apply_multi_workspace_patch(destination)
        verify(destination)
        if not (destination / "node_modules").is_dir():
            _install_dependencies(destination)
        _prepare_runtime_build(destination)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".pi-source-", dir=destination.parent) as temporary:
        staged = Path(temporary) / commit
        clone(staged)
        _install_dependencies(staged)
        _prepare_runtime_build(staged)
        os.replace(staged, destination)
    return destination


def _install_dependencies(source: Path) -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise PiSourceError("npm is required to install the managed Pi App Server runtime")
    try:
        subprocess.run([npm, "ci", "--ignore-scripts"], cwd=source, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to install pinned Pi dependencies: {exc}") from exc


def _prepare_runtime_build(source: Path) -> None:
    """The source entrypoint still imports generated model data and package dist files."""
    npm = shutil.which("npm")
    if npm is None:
        raise PiSourceError("npm is required to prepare the pinned Pi runtime")
    try:
        if not (source / "packages/ai/src/providers/data/amazon-bedrock.json").is_file():
            subprocess.run([npm, "run", "hydrate:model-data"], cwd=source, check=True)
        required = ("packages/chord/dist/index.js", "packages/coding-agent/dist/bundle")
        if any(not (source / path).exists() for path in required):
            subprocess.run([npm, "run", "build:offline"], cwd=source, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to build pinned Pi runtime: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify", type=Path, metavar="SOURCE_ROOT")
    group.add_argument("--clone", type=Path, metavar="DESTINATION")
    group.add_argument("--install", type=Path, metavar="INSTALL_ROOT")
    parser.add_argument("--apply-worker-patch", action="store_true", help="apply the native Worker entrypoint patch before verification")
    args = parser.parse_args()
    try:
        if args.verify is not None:
            if args.apply_worker_patch:
                apply_worker_patch(args.verify)
            source = verify(args.verify)
        elif args.clone is not None:
            if args.apply_worker_patch:
                parser.error("--apply-worker-patch is only valid with --verify")
            source = clone(args.clone)
        else:
            if args.apply_worker_patch:
                parser.error("--apply-worker-patch is only valid with --verify")
            source = install(args.install)
    except PiSourceError as exc:
        parser.error(str(exc))
    print(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
