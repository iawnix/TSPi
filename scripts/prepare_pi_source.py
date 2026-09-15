"""Resolve and verify the pinned Pi source tree used by the native app server."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "config" / "pi-source.json"
PATCH_PATH = ROOT / "config" / "pi-worker-entry.patch"


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
    return commit


def apply_worker_patch(source: Path) -> None:
    process_path = source / "packages" / "coding-agent" / "src" / "experimental" / "process.ts"
    if "PI_SESSION_WORKER_ENTRY" in process_path.read_text(encoding="utf-8"):
        return
    try:
        subprocess.run(["git", "-C", str(source), "apply", str(PATCH_PATH)], check=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PiSourceError(f"failed to apply TSPi Worker entrypoint patch: {exc}") from exc


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
    verify(destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify", type=Path, metavar="SOURCE_ROOT")
    group.add_argument("--clone", type=Path, metavar="DESTINATION")
    parser.add_argument("--apply-worker-patch", action="store_true", help="apply the native Worker entrypoint patch before verification")
    args = parser.parse_args()
    try:
        if args.verify is not None:
            if args.apply_worker_patch:
                apply_worker_patch(args.verify)
            source = verify(args.verify)
        else:
            if args.apply_worker_patch:
                parser.error("--apply-worker-patch is only valid with --verify")
            source = clone(args.clone)
    except PiSourceError as exc:
        parser.error(str(exc))
    print(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
