"""Command line entrypoint for explicit Research Agent artifact transfers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

from artifact_store.transfer import (
    DEFAULT_CHUNK_SIZE,
    TransferManifestError,
    apply_manifest,
    build_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ResearchAgent artifact",
        description="Create and apply explicit, resumable artifact transfer manifests.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="digest an explicit list of files")
    manifest.add_argument("--root", required=True, help="absolute source directory")
    manifest.add_argument(
        "--path",
        action="append",
        required=True,
        metavar="RELATIVE_PATH",
        help="relative file path to include; repeat for each file",
    )
    manifest.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"chunk size in bytes (default: {DEFAULT_CHUNK_SIZE})",
    )
    manifest.add_argument("--output", required=True, help="manifest path (written atomically)")

    apply = sub.add_parser("apply", help="verify and materialize a transfer manifest")
    apply.add_argument("--source-root", required=True, help="absolute source directory")
    apply.add_argument("--destination-root", required=True, help="absolute destination directory")
    apply.add_argument("--manifest", required=True, help="manifest JSON path")
    apply.add_argument(
        "--no-resume",
        action="store_true",
        help="discard partial files instead of resuming them",
    )
    return parser


def _regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise TransferManifestError(f"{label} must be a regular file: {path}")


def _write_manifest(path_value: str, manifest: dict[str, object]) -> None:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        raise TransferManifestError(f"manifest output must be an absolute path: {path}")
    if path.is_symlink():
        raise TransferManifestError(f"manifest output cannot be a symbolic link: {path}")
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise TransferManifestError(f"manifest output parent must be a directory: {parent}")

    payload = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=parent,
            prefix=f".{path.name}.",
            suffix=".tspi-tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        # os.replace preserves the temporary file's owner-only mode.  Sync the
        # directory as well so a completed command has a durable name update.
        directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_manifest(path_value: str) -> dict[str, object]:
    path = Path(path_value).expanduser()
    if path.is_symlink() or not path.is_absolute():
        raise TransferManifestError(f"manifest path must be an absolute regular file: {path}")
    _regular_file(path, "manifest")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TransferManifestError(f"cannot read manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TransferManifestError("manifest JSON must contain an object")
    return value


def _run(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "manifest":
        manifest = build_manifest(args.root, args.path, chunk_size=args.chunk_size)
        _write_manifest(args.output, manifest)
        return {
            "command": "manifest",
            "manifest": str(Path(args.output).expanduser()),
            "entries": len(manifest["entries"]),
            "manifest_sha256": manifest["manifest_sha256"],
        }
    manifest = _read_manifest(args.manifest)
    result = apply_manifest(
        args.source_root,
        args.destination_root,
        manifest,
        resume=not args.no_resume,
    )
    return {"command": "apply", "manifest": str(Path(args.manifest).expanduser()), **result}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # Keep the parent launcher callable from tests and embedding code while
        # retaining argparse's normal help and usage output.
        return int(exc.code or 0)
    try:
        result = _run(args)
    except (TransferManifestError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


__all__ = ["main"]
