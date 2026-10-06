"""Explicit, resumable file transfer manifests.

This module is intentionally separate from the Research State registry.  A
caller chooses the files to export; the manifest makes that choice auditable
and the receiver verifies every chunk before atomically publishing a file.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Iterable
import re


SCHEMA_VERSION = "tspi-artifact-transfer/1"
DEFAULT_CHUNK_SIZE = 1024 * 1024
MAX_CHUNK_SIZE = 16 * 1024 * 1024
_FORBIDDEN_PREFIXES = (
    ".pi/app-server-host",
    ".pi/sessions",
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class TransferManifestError(ValueError):
    """Raised when a transfer manifest or path is unsafe."""


@dataclass(frozen=True)
class Chunk:
    offset: int
    size: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {"offset": self.offset, "size": self.size, "sha256": self.sha256}


def build_manifest(root: str | os.PathLike[str], paths: Iterable[str | os.PathLike[str]], *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict[str, object]:
    """Build a digest manifest for an explicit set of regular files."""
    root_path = _root(root)
    size = _chunk_size(chunk_size)
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for value in paths:
        relative = _relative_path(value)
        if relative in seen:
            raise TransferManifestError(f"duplicate transfer path: {relative}")
        seen.add(relative)
        source = _safe_join(root_path, relative)
        _validate_regular(source, "transfer source")
        entries.append(_file_entry(source, relative, size))
    entries.sort(key=lambda item: str(item["path"]))
    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "chunk_size": size,
        "entries": entries,
    }
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    return manifest


def apply_manifest(
    source_root: str | os.PathLike[str],
    destination_root: str | os.PathLike[str],
    manifest: dict[str, object],
    *,
    resume: bool = True,
) -> dict[str, object]:
    """Copy manifest files with chunk verification and atomic publication."""
    source = _root(source_root)
    destination = _root(destination_root, create=True)
    normalized = validate_manifest(manifest)
    copied = 0
    skipped = 0
    for entry in normalized["entries"]:
        relative = str(entry["path"])
        source_path = _safe_join(source, relative)
        target = _safe_join(destination, relative)
        _validate_regular(source_path, "transfer source")
        expected = str(entry["sha256"])
        if target.exists() or target.is_symlink():
            _validate_regular(target, "transfer destination")
            if _digest_file(target) == expected:
                skipped += 1
                continue
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _reject_symlink_parents(destination, target.parent)
        partial = target.with_name(f".{target.name}.tspi-part")
        _copy_entry(source_path, partial, entry, resume=resume)
        os.replace(partial, target)
        target.chmod(0o600)
        copied += 1
    return {"schema_version": SCHEMA_VERSION, "copied": copied, "skipped": skipped, "entries": len(normalized["entries"])}


def validate_manifest(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"schema_version", "chunk_size", "entries", "manifest_sha256"}:
        raise TransferManifestError("transfer manifest has an invalid shape")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise TransferManifestError("unsupported transfer manifest schema")
    size = _chunk_size(value.get("chunk_size"))
    entries = value.get("entries")
    if not isinstance(entries, list):
        raise TransferManifestError("transfer manifest entries must be a list")
    previous = ""
    for entry in entries:
        _validate_entry(entry, size)
        path = str(entry["path"])
        if path <= previous:
            raise TransferManifestError("transfer manifest paths must be unique and sorted")
        previous = path
    digest = value.get("manifest_sha256")
    if not isinstance(digest, str) or digest != _manifest_digest({key: value[key] for key in ("schema_version", "chunk_size", "entries")}):
        raise TransferManifestError("transfer manifest digest mismatch")
    return value


def _file_entry(path: Path, relative: str, chunk_size: int) -> dict[str, object]:
    chunks: list[dict[str, object]] = []
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            chunk_digest = hashlib.sha256(chunk).hexdigest()
            digest.update(chunk)
            chunks.append(Chunk(total, len(chunk), f"sha256:{chunk_digest}").as_dict())
            total += len(chunk)
    return {"path": relative, "size": total, "sha256": f"sha256:{digest.hexdigest()}", "chunks": chunks}


def _copy_entry(source: Path, partial: Path, entry: dict[str, object], *, resume: bool) -> None:
    chunks = entry["chunks"]
    assert isinstance(chunks, list)
    if partial.is_symlink():
        raise TransferManifestError(f"transfer partial path is a symbolic link: {partial}")
    offset = partial.stat().st_size if resume and partial.exists() else 0
    expected_size = int(entry["size"])
    first_chunk_size = int(chunks[0]["size"]) if chunks else 1
    if offset > expected_size or (offset and offset % first_chunk_size):
        offset = 0
    if offset:
        with partial.open("rb") as handle:
            prefix = handle.read(offset)
        if not _verify_prefix(prefix, chunks):
            offset = 0
    if offset == 0:
        partial.unlink(missing_ok=True)
    with source.open("rb") as origin, partial.open("ab" if offset else "wb") as target:
        origin.seek(offset)
        target.seek(offset)
        for chunk in chunks:
            chunk_offset = int(chunk["offset"])
            if chunk_offset + int(chunk["size"]) <= offset:
                continue
            origin.seek(chunk_offset)
            data = origin.read(int(chunk["size"]))
            if len(data) != int(chunk["size"]) or _sha256(data) != chunk["sha256"]:
                raise TransferManifestError(f"source changed during transfer: {entry['path']}")
            target.write(data)
        target.flush()
        os.fsync(target.fileno())
    if partial.stat().st_size != expected_size or _digest_file(partial) != entry["sha256"]:
        raise TransferManifestError(f"transferred file digest mismatch: {entry['path']}")


def _verify_prefix(data: bytes, chunks: list[object]) -> bool:
    consumed = 0
    for value in chunks:
        chunk = value if isinstance(value, dict) else {}
        size = int(chunk.get("size", 0))
        if consumed + size > len(data):
            return True
        if _sha256(data[consumed:consumed + size]) != chunk.get("sha256"):
            return False
        consumed += size
        if consumed == len(data):
            return True
    return consumed == len(data)


def _validate_entry(entry: object, chunk_size: int) -> None:
    if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256", "chunks"}:
        raise TransferManifestError("transfer entry has an invalid shape")
    relative = _relative_path(entry.get("path"))
    if relative != entry["path"]:
        raise TransferManifestError("transfer entry path is not normalized")
    if not isinstance(entry["size"], int) or entry["size"] < 0:
        raise TransferManifestError("transfer entry size is invalid")
    if not isinstance(entry["sha256"], str) or not _DIGEST.fullmatch(entry["sha256"]):
        raise TransferManifestError("transfer entry digest is invalid")
    chunks = entry["chunks"]
    if not isinstance(chunks, list):
        raise TransferManifestError("transfer entry chunks must be a list")
    offset = 0
    total = 0
    for chunk in chunks:
        if not isinstance(chunk, dict) or set(chunk) != {"offset", "size", "sha256"}:
            raise TransferManifestError("transfer chunk has an invalid shape")
        if chunk["offset"] != offset or not isinstance(chunk["size"], int) or not 0 < chunk["size"] <= chunk_size:
            raise TransferManifestError("transfer chunk boundaries are invalid")
        if not isinstance(chunk["sha256"], str) or not _DIGEST.fullmatch(chunk["sha256"]):
            raise TransferManifestError("transfer chunk digest is invalid")
        offset += chunk["size"]
        total += chunk["size"]
    if total != entry["size"] or (entry["size"] == 0 and chunks):
        raise TransferManifestError("transfer chunk sizes do not match entry size")


def _manifest_digest(value: dict[str, object]) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _sha256(payload)


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(DEFAULT_CHUNK_SIZE):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _chunk_size(value: object) -> int:
    if not isinstance(value, int) or not 1 <= value <= MAX_CHUNK_SIZE:
        raise TransferManifestError("chunk_size is invalid")
    return value


def _root(value: str | os.PathLike[str], *, create: bool = False) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or path.is_symlink():
        raise TransferManifestError(f"transfer root must be an absolute physical directory: {path}")
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise TransferManifestError(f"transfer root must be a directory: {path}")
    return path.resolve()


def _relative_path(value: object) -> str:
    if not isinstance(value, (str, os.PathLike)):
        raise TransferManifestError("transfer path must be a relative path")
    raw = os.fspath(value).replace(os.sep, "/")
    candidate = PurePosixPath(raw)
    if not raw or candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
        raise TransferManifestError(f"transfer path is unsafe: {raw}")
    normalized = candidate.as_posix()
    if any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in _FORBIDDEN_PREFIXES):
        raise TransferManifestError(f"transfer path is protected: {normalized}")
    return normalized


def _safe_join(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise TransferManifestError(f"transfer path escaped root: {relative}")
    _reject_symlink_parents(root, target.parent)
    return target


def _reject_symlink_parents(root: Path, path: Path) -> None:
    current = path
    while current != root:
        if current.is_symlink():
            raise TransferManifestError(f"transfer path contains a symbolic link: {current}")
        current = current.parent


def _validate_regular(path: Path, label: str) -> None:
    if path.is_symlink() or not path.exists() or not stat.S_ISREG(path.lstat().st_mode):
        raise TransferManifestError(f"{label} must be a regular file: {path}")


__all__ = ["DEFAULT_CHUNK_SIZE", "SCHEMA_VERSION", "TransferManifestError", "apply_manifest", "build_manifest", "validate_manifest"]
